/* Odin's Share + Pinpoint — barcode scan overlay.
   Loaded only when the scan button is tapped (idle pages do no scanning work at all). It pulls in Vault's camera
   engine (scan-engine.js; ZXing is fetched on top of that only where the browser has no native BarcodeDetector,
   i.e. iPhones) and calls back with the code. Callers: ODKScan.open(function(code){ … }). */
(function () {
  "use strict";
  var here = document.currentScript && document.currentScript.src;
  var ENGINE_V = "f72bad731d";
  var engineP = null, css = false, ui = null;

  function sib(name, v) { return new URL(name + (v ? "?v=" + v : ""), here || location.href).href; }

  function loadEngine() {
    if (window.SKScan) return Promise.resolve();
    window.SK_ZXING_SRC = sib("zxing.min.js");
    return engineP || (engineP = new Promise(function (ok, no) {
      var s = document.createElement("script");
      s.src = sib("scan-engine.js", ENGINE_V);
      s.onload = ok;
      s.onerror = function () { engineP = null; no(new Error("Could not load the scanner")); };
      document.head.appendChild(s);
    }));
  }

  function style() {
    if (css) return; css = true;
    var el = document.createElement("style");
    el.textContent =
      ".odk-scan{position:fixed;inset:0;z-index:2147483000;background:#0b0d14;color:#e9eef5;display:flex;flex-direction:column;" +
      "font:500 15px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;overscroll-behavior:contain;touch-action:none}" +
      ".odk-scan video{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}" +
      ".odk-scan .aim{box-shadow:0 0 0 100vmax rgba(7,9,15,.5);border-radius:12px;position:absolute;left:50%;top:50%;width:min(86vw,26rem);height:min(30vw,9rem);min-height:6.5rem;" +
      "translate:-50% -50%;pointer-events:none}" +
      ".odk-scan .aim i{position:absolute;width:2.1rem;height:2.1rem;border:3px solid #d4af37;border-radius:6px;" +
      "filter:drop-shadow(0 0 6px rgba(212,175,55,.45))}" +
      ".odk-scan .aim i:nth-child(1){left:0;top:0;border-right:0;border-bottom:0}" +
      ".odk-scan .aim i:nth-child(2){right:0;top:0;border-left:0;border-bottom:0}" +
      ".odk-scan .aim i:nth-child(3){left:0;bottom:0;border-right:0;border-top:0}" +
      ".odk-scan .aim i:nth-child(4){right:0;bottom:0;border-left:0;border-top:0}" +
      ".odk-scan .aim b{position:absolute;left:6%;right:6%;top:50%;height:2px;background:#d4af37;opacity:.85;" +
      "box-shadow:0 0 10px #d4af37;animation:odkSweep 1.7s ease-in-out infinite alternate}" +
      "@keyframes odkSweep{from{top:12%}to{top:88%}}" +
      ".odk-scan .top{position:relative;display:flex;align-items:center;justify-content:space-between;gap:.6rem;" +
      "padding:max(.9rem,env(safe-area-inset-top)) .9rem .5rem}" +
      ".odk-scan .ttl{font-family:Marcellus,Georgia,serif;font-size:1.1rem;letter-spacing:.04em;text-shadow:0 1px 8px #000}" +
      ".odk-scan button{border:1px solid rgba(255,255,255,.22);background:rgba(20,24,38,.62);color:inherit;" +
      "-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px);height:2.8rem;min-width:2.8rem;padding:0 .9rem;" +
      "border-radius:999px;font:inherit;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;gap:.4rem}" +
      ".odk-scan button:active{transform:scale(.94)}" +
      ".odk-scan button[aria-pressed=true]{background:#d4af37;color:#1a1608;border-color:#d4af37}" +
      ".odk-scan .row{display:flex;gap:.5rem}" +
      ".odk-scan .msg{position:relative;margin:auto 1.2rem max(1.6rem,env(safe-area-inset-bottom));text-align:center;" +
      "text-shadow:0 1px 8px #000;padding:.7rem 1rem;border-radius:1rem;background:rgba(20,24,38,.62);" +
      "-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px)}" +
      ".odk-scan .msg.err{background:rgba(120,30,40,.8)}" +
      "@media (prefers-reduced-motion:reduce){.odk-scan .aim b{animation:none}}";
    document.head.appendChild(el);
  }

  function build() {
    var root = document.createElement("div");
    root.className = "odk-scan";
    root.setAttribute("role", "dialog");
    root.setAttribute("aria-modal", "true");
    root.setAttribute("aria-label", "Scan a barcode");
    root.innerHTML =
      '<video playsinline muted></video>' +
      '<div class="aim"><i></i><i></i><i></i><i></i><b></b></div>' +
      '<div class="top"><span class="ttl">Scan a bottle</span><div class="row">' +
      '<button type="button" class="torch" aria-pressed="false" aria-label="Torch" hidden>' +
      '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 2h10l-2 8H9zM9 10v4l-1 8h8l-1-8v-4"/></svg></button>' +
      '<button type="button" class="close" aria-label="Close">✕</button></div></div>' +
      '<p class="msg" aria-live="polite">Point at the barcode</p>';
    return {
      root: root,
      video: root.querySelector("video"),
      msg: root.querySelector(".msg"),
      torch: root.querySelector(".torch"),
      close: root.querySelector(".close")
    };
  }

  function open(onCode) {
    if (ui) return;
    style();
    var u = ui = build(), ctl = null, done = false, prevFocus = document.activeElement, prevOverflow = document.documentElement.style.overflow;
    document.body.appendChild(u.root);
    document.documentElement.style.overflow = "hidden";
    u.close.focus();

    function shut() {
      if (done) return; done = true;
      try { ctl && ctl.stop(); } catch (_) {}
      document.removeEventListener("keydown", onKey, true);
      u.root.remove();
      document.documentElement.style.overflow = prevOverflow;
      ui = null;
      try { prevFocus && prevFocus.focus && prevFocus.focus({ preventScroll: true }); } catch (_) {}
    }
    function onKey(e) { if (e.key === "Escape") { e.preventDefault(); shut(); } }
    function fail(text) { u.msg.textContent = text; u.msg.classList.add("err"); }
    document.addEventListener("keydown", onKey, true);
    u.close.addEventListener("click", shut);
    u.root.addEventListener("click", function (e) { if (e.target === u.root || e.target === u.video) shut(); });

    loadEngine().then(function () {
      if (done) return;
      return window.SKScan.start({
        video: u.video,
        formats: "1d",
        confirm: 2,
        onCode: function (code) { shut(); onCode(code); },
        onReject: function () { u.msg.textContent = "Hold steady — that read looked off"; }
      }).then(function (c) {
        if (done) { c.stop(); return; }
        ctl = c;
        if (c.caps && c.caps.torch) {
          u.torch.hidden = false;
          u.torch.addEventListener("click", function () {
            var on = u.torch.getAttribute("aria-pressed") !== "true";
            c.setTorch(on).then(function () { u.torch.setAttribute("aria-pressed", String(on)); }, function () {});
          });
        }
      });
    }).catch(function (e) {
      if (done) return;
      fail(window.SKScan ? window.SKScan.cameraProblem(e) : (e && e.message) || "Could not start the scanner");
    });
  }

  window.ODKScan = { open: open };
})();
