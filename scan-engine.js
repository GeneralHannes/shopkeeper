// Odin's Vault — camera barcode engine. Used by the scan overlay (scanCamera in vault.js) and by the Scan test tab.
//
// Speed:    decodes only the aiming band (smaller image = faster), only on a NEW video frame, never two decodes at
//           once; the native BarcodeDetector when the browser has it, ZXing (loaded on demand) when it doesn't.
// Accuracy: a retail code is accepted only when its CHECK DIGIT is valid AND the same value is read on consecutive
//           frames — so a smudged or half-seen code is dropped instead of becoming a wrong item. QR carries its own
//           error correction, so it is accepted on the first read. Nothing a camera does can promise 0 wrong reads;
//           this makes a wrong one require a valid check digit twice in a row.
// Also loads in Node/Bun (the pure functions below are unit-tested in src/scanner.test.ts).

(function(root){
'use strict';

// ---- check digits ----------------------------------------------------------------------------------------------
// GS1 mod-10: digits weighted 3,1,3,1… from the right (the check digit itself excluded).
function gs1Valid(s){
  if(!/^\d+$/.test(s)) return false;
  let sum=0;
  for(let i=s.length-2, w=3; i>=0; i--, w=4-w) sum += (s.charCodeAt(i)-48)*w;
  return (10 - sum%10)%10 === s.charCodeAt(s.length-1)-48;
}
// UPC-E is a squeezed UPC-A: expand it, then check the UPC-A.
function upcEToA(e){
  const d=e.slice(1,7), n=e[0], c=e[7], last=d[5];
  let body;
  if(last==='0'||last==='1'||last==='2') body = d.slice(0,2)+last+'0000'+d.slice(2,5);
  else if(last==='3') body = d.slice(0,3)+'00000'+d.slice(3,5);
  else if(last==='4') body = d.slice(0,4)+'00000'+d[4];
  else body = d.slice(0,5)+'0000'+last;
  return n+body+c;
}
// 'ok' = valid or no check digit to test; 'bad' = a check digit that does not match.
function checkCode(value, format){
  const v=String(value||'').trim();
  if(!v) return 'bad';
  switch(format){
    case 'ean_13':  return v.length===13 && gs1Valid(v) ? 'ok' : 'bad';
    case 'ean_8':   return v.length===8  && gs1Valid(v) ? 'ok' : 'bad';
    case 'upc_a':   return (v.length===12 && gs1Valid(v)) || (v.length===13 && v[0]==='0' && gs1Valid(v)) ? 'ok' : 'bad';
    case 'upc_e':   return v.length===8 && /^[01]/.test(v) && gs1Valid(upcEToA(v)) ? 'ok' : 'bad';
    case 'itf':     return (v.length===14 ? (gs1Valid(v) ? 'ok' : 'bad') : (v.length%2===0 && /^\d+$/.test(v) ? 'ok' : 'bad'));
    default:        return 'ok';     // code_128 verifies its own checksum while decoding; code_39 / QR have none to test here
  }
}

// ---- formats ---------------------------------------------------------------------------------------------------
const BD_1D = ['ean_13','ean_8','upc_a','upc_e','code_128','code_39','itf'];
const BD_ALL = BD_1D.concat('qr_code');
const formatsFor = f => f==='qr' ? ['qr_code'] : f==='1d' ? BD_1D : BD_ALL;
const ZX_NAME = { EAN_13:'ean_13', EAN_8:'ean_8', UPC_A:'upc_a', UPC_E:'upc_e', CODE_128:'code_128', CODE_39:'code_39', ITF:'itf', QR_CODE:'qr_code' };

// ---- agreement: accept a value only after it repeats ------------------------------------------------------------
// reads that disagree reset the streak; a gap longer than `windowMs` also resets it (a stale glimpse is not agreement).
function makeVoter(need, windowMs){
  let last=null, n=0, t=0;
  return function vote(value, now){
    if(value===last && now-t<=windowMs) n++; else { last=value; n=1; }
    t=now;
    if(n>=need){ last=null; n=0; return true; }
    return false;
  };
}

// ---- the engine ------------------------------------------------------------------------------------------------
// start({ video, formats:'all'|'1d'|'qr', confirm:2, continuous:false, rearmMs:900, camera:'environment'|deviceId,
//         onCode(code, info), onReject(info), onStats(stats) })  ->  Promise<controller>
// controller: { stop(), caps, setTorch(on), setZoom(z), refocus(), switchCamera(), stats() }
async function start(opts){
  const video=opts.video;
  const fmts=formatsFor(opts.formats), need=Math.max(1, opts.confirm==null ? 2 : opts.confirm);
  const rearm=opts.rearmMs==null ? 900 : opts.rearmMs;     // continuous mode: a code already accepted counts again only after it has been out of view this long
  const t0=performance.now();

  // -- camera
  let stream=null, track=null, camPref=opts.camera||'environment';
  const open=async()=>{
    if(stream) stream.getTracks().forEach(t=>t.stop());
    const vid = camPref==='environment' || camPref==='user'
      ? { facingMode:{ideal:camPref}, width:{ideal:1280}, height:{ideal:720}, frameRate:{ideal:30}, focusMode:{ideal:'continuous'} }
      : { deviceId:{exact:camPref}, width:{ideal:1280}, height:{ideal:720}, frameRate:{ideal:30} };
    try{ stream=await navigator.mediaDevices.getUserMedia({video:vid}); }
    catch(e){
      if(e && (e.name==='NotAllowedError'||e.name==='SecurityError')) throw e;
      stream=await navigator.mediaDevices.getUserMedia({video:true});     // a stricter constraint failed — take any camera
    }
    video.srcObject=stream; video.muted=true; video.setAttribute('playsinline','');
    await video.play().catch(()=>{});
    track=stream.getVideoTracks()[0];
    try{ if(track.getCapabilities?.().focusMode?.includes('continuous')) await track.applyConstraints({advanced:[{focusMode:'continuous'}]}); }catch(_){}
  };
  await open();

  // -- decoder: native if it can read what we asked for, else ZXing
  let det=null, zx=null, decoder='';
  if('BarcodeDetector' in root){
    try{
      const supported = BarcodeDetector.getSupportedFormats ? await BarcodeDetector.getSupportedFormats() : fmts;
      const use = fmts.filter(f=>supported.includes(f));
      if(use.length===fmts.length || (use.length && opts.formats!=='qr')){ det=new BarcodeDetector({formats:use}); decoder='native'; }
    }catch(_){ det=null; }
  }
  if(!det){
    await loadZXing();
    const Z=root.ZXing;
    if(!(Z && Z.MultiFormatReader)) throw new Error('No barcode decoder available in this browser');
    const hints=new Map(), F=Z.BarcodeFormat;
    hints.set(Z.DecodeHintType.POSSIBLE_FORMATS, fmts.map(f=>F[Object.keys(ZX_NAME).find(k=>ZX_NAME[k]===f)]).filter(x=>x!=null));
    zx=new Z.MultiFormatReader(); zx.setHints(hints); decoder='zxing';
  }

  // -- loop
  const work=document.createElement('canvas'), ctx=work.getContext('2d',{willReadFrequently:true});
  const vote=makeVoter(need, 600);
  const held=new Map();                           // continuous mode: accepted code -> last time it was still in view (a code you keep holding is not re-counted)
  const st={ decoder, frames:0, decodes:0, accepted:0, rejected:0, decodeMs:0, fps:0, width:0, height:0, roi:'band' };
  let stopped=false, busy=false, fpsT=performance.now(), fpsN=0, miss=0;

  // The aiming band (what the on-screen frame shows) is tried first; if nothing reads for a moment the whole frame is
  // tried too, so a code held off-centre still works. Wide-and-short suits 1D codes, taller suits QR.
  function region(vw, vh, full){
    if(full) return [0,0,vw,vh];
    const w=vw*0.9, h=vh*(opts.formats==='qr' ? 0.8 : 0.5);
    return [(vw-w)/2,(vh-h)/2,w,h];
  }
  async function decodeOnce(){
    const vw=video.videoWidth, vh=video.videoHeight;
    if(!vw||!vh) return null;
    st.width=vw; st.height=vh;
    const full = miss>=6 && miss%2===0;           // every other try after ~6 empty frames
    st.roi = full ? 'full' : 'band';
    const [sx,sy,sw,sh]=region(vw,vh,full);
    const k=Math.min(1, 960/sw);                   // never decode more pixels than needed
    work.width=Math.max(1,Math.round(sw*k)); work.height=Math.max(1,Math.round(sh*k));
    ctx.drawImage(video,sx,sy,sw,sh,0,0,work.width,work.height);
    const a=performance.now();
    let out=null;
    try{
      if(det){
        const r=await det.detect(work);
        if(r.length) out={ value:r[0].rawValue, format:r[0].format };
      } else {
        const Z=root.ZXing;
        const bmp=new Z.BinaryBitmap(new Z.HybridBinarizer(new Z.HTMLCanvasElementLuminanceSource(work)));
        try{ const r=zx.decodeWithState(bmp); out={ value:r.getText(), format:ZX_NAME[Z.BarcodeFormat[r.getBarcodeFormat()]]||'unknown' }; }
        catch(e){ /* NotFoundException = nothing in this frame */ }
      }
    }catch(_){}
    st.decodes++; st.decodeMs = st.decodeMs ? st.decodeMs*0.8+(performance.now()-a)*0.2 : performance.now()-a;
    return out;
  }
  async function tick(){
    if(stopped) return;
    if(busy){ schedule(); return; }
    busy=true;
    try{
      st.frames++; fpsN++;
      const now=performance.now();
      if(now-fpsT>=1000){ st.fps=fpsN*1000/(now-fpsT); fpsN=0; fpsT=now; opts.onStats&&opts.onStats(snapshot()); }
      const r=await decodeOnce();
      if(!r){ miss++; }
      else {
        miss=0;
        const value=String(r.value).trim(), format=r.format;
        if(checkCode(value, format)==='bad'){ st.rejected++; opts.onReject&&opts.onReject({ value, format, reason:'check digit does not match' }); }
        else {
          const key=format+':'+value, now2=performance.now(), h=held.get(key);
          if(opts.continuous && h!=null){
            if(now2-h<rearm) held.set(key, now2);       // still the same code in view: do nothing, just remember it is still here
            else held.delete(key);                      // it left and came back: it can count again
          }
          if(!held.has(key) && vote(key, now2)){
            if(opts.continuous) held.set(key, now2);
            st.accepted++;
            feedback();
            opts.onCode(value, { format, ms:Math.round(performance.now()-t0), decoder, checked: format==='qr_code'||format==='code_128'||format==='code_39' ? 'self' : 'check digit' });
            if(!opts.continuous){ stop(); return; }
          }
        }
      }
    }finally{ busy=false; }
    schedule();
  }
  function schedule(){
    if(stopped) return;
    if(video.requestVideoFrameCallback) video.requestVideoFrameCallback(()=>tick());   // one decode per NEW frame
    else requestAnimationFrame(tick);
  }
  const snapshot=()=>Object.assign({}, st, { camera: track && track.label || '', uptimeMs:Math.round(performance.now()-t0) });

  // -- feedback: a beep and a buzz, so a worker knows without looking
  let ac=null;
  function feedback(){
    try{ navigator.vibrate&&navigator.vibrate(50); }catch(_){}
    try{
      ac = ac || new (root.AudioContext||root.webkitAudioContext)();
      const o=ac.createOscillator(), g=ac.createGain();
      o.frequency.value=1760; g.gain.value=0.08; o.connect(g); g.connect(ac.destination); o.start(); o.stop(ac.currentTime+0.07);
    }catch(_){}
  }

  function stop(){
    if(stopped) return; stopped=true;
    try{ stream&&stream.getTracks().forEach(t=>t.stop()); }catch(_){}
    try{ video.srcObject=null; }catch(_){}
    try{ ac&&ac.close(); }catch(_){}
    document.removeEventListener('visibilitychange', onVis);
  }
  const onVis=()=>{ if(document.hidden) stop(); };      // a backgrounded page must give the camera back
  document.addEventListener('visibilitychange', onVis);

  schedule();
  const caps=(track&&track.getCapabilities)?track.getCapabilities():{};
  return {
    stop, caps, stats:snapshot,
    decoder,
    async setTorch(on){ await track.applyConstraints({advanced:[{torch:!!on}]}); },
    async setZoom(z){ await track.applyConstraints({advanced:[{zoom:z}]}); },
    async refocus(){ try{ await track.applyConstraints({advanced:[{focusMode:'single-shot'}]}); }
                     catch(_){ try{ await track.applyConstraints({advanced:[{focusMode:'continuous'}]}); }catch(_){} } },
    async cameras(){ try{ return (await navigator.mediaDevices.enumerateDevices()).filter(d=>d.kind==='videoinput'); }catch(_){ return []; } },
    async switchCamera(id){ camPref=id; await open(); },
  };
}

let zxLoad=null;
function loadZXing(){
  if(root.ZXing) return Promise.resolve();
  return zxLoad || (zxLoad=new Promise((ok,no)=>{
    const s=document.createElement('script'); s.src=root.SK_ZXING_SRC||'/static/vendor/zxing.min.js';
    s.onload=ok; s.onerror=()=>{ zxLoad=null; no(new Error('Could not load the barcode decoder')); }; document.head.appendChild(s); }));
}

// Why can't the camera open? A phone browser only allows it on HTTPS (or localhost) — the most common cause here.
function cameraProblem(e){
  if(!root.isSecureContext) return 'The camera needs a secure (https) address. Open the Vault over https, not http.';
  if(!navigator.mediaDevices?.getUserMedia) return 'This browser has no camera access.';
  switch(e && e.name){
    case 'NotAllowedError': case 'SecurityError': return 'Camera is blocked — allow it for this site in the browser settings, then try again.';
    case 'NotFoundError': case 'OverconstrainedError': return 'No camera found on this device.';
    case 'NotReadableError': return 'The camera is busy — another app or tab is using it.';
    default: return 'Camera error: '+(e && e.message || e);
  }
}

const api={ start, checkCode, gs1Valid, upcEToA, makeVoter, formatsFor, cameraProblem, loadZXing };
if(typeof module!=='undefined' && module.exports) module.exports=api; else root.SKScan=api;
})(typeof window!=='undefined' ? window : globalThis);
