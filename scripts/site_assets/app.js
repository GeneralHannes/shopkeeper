/* shopkeeper public catalogue — filtering, sorting, detail view.
   Cards are already in the HTML; this only shows/hides and reorders them, so
   the page is fully readable (and crawlable) with JavaScript switched off. */
(function () {
  "use strict";
  var grid   = document.getElementById("grid"),
      cards  = Array.prototype.slice.call(grid.querySelectorAll(".card")),
      qEl    = document.getElementById("q"),
      sortEl = document.getElementById("sort"),
      countEl= document.getElementById("count"),
      emptyEl= document.getElementById("empty"),
      chips  = Array.prototype.slice.call(document.querySelectorAll(".chip")),
      dlg    = document.getElementById("dlg"),
      fam = "", shelf = "", term = "";

  function slug(v) { return v.toLowerCase().replace(/[^a-z0-9]+/g, "-"); }

  // Mark the document as scripted, then immediately settle any image the browser
  // already decoded — otherwise those would flash visible and re-fade.
  document.documentElement.classList.add("js");
  var calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  // The reveal is scrubbed by hand for every browser alike. Native scroll
  // timelines would be cheaper where they exist, but they do not exist in Gecko
  // by default or in older WebKit, and a reveal that feels different depending
  // on the phone is worse than one that costs a little. Only the few cards
  // actually mid-reveal are touched per frame, so the cost stays small.
  var band = [], scrubQueued = false;
  function requestScrub() {
    if (scrubQueued || !band.length) return;
    scrubQueued = true;
    requestAnimationFrame(paintScrub);
  }
  function paintScrub() {
    scrubQueued = false;
    var n = band.length;
    if (!n) return;
    var h = window.innerHeight || document.documentElement.clientHeight;
    var i, ps = new Array(n);
    for (i = 0; i < n; i++) {                 // every read first, so writing
      var r = band[i].getBoundingClientRect(); // below cannot force a reflow
      var travel = (r.height * 0.75) || 1;     // same 75%-of-itself as the CSS
      var p = (h - r.top) / travel;
      ps[i] = p < 0 ? 0 : p > 1 ? 1 : p;
    }
    for (i = 0; i < n; i++) {                 // then every write
      var el = band[i], q = ps[i];
      if (el._p === q) continue;              // nothing moved; skip the style set
      el._p = q;
      if (q >= 1) { el.style.opacity = ""; el.style.translate = ""; }
      else {
        el.style.opacity = String(q);
        el.style.translate = "0 " + ((1 - q) * 20).toFixed(1) + "px";
      }
    }
  }

  // A rolling estimate of scroll speed in px/ms, smoothed so one stuttery event
  // cannot flip the mode on its own.
  var scrollV = 0, lastT = 0;
  function flicking() {
    // no scroll event for a moment means it has stopped — that is not a flick
    if (!lastT || (performance.now() - lastT) > 120) return false;
    return scrollV > 1.2;
  }
  function watchImage(img) {
    if (img.complete && img.naturalWidth) { img.classList.add("ready"); return; }
    img.addEventListener("load", function () { img.classList.add("ready"); }, { once: true });
    img.addEventListener("error", function () { img.classList.add("ready"); }, { once: true });
  }
  Array.prototype.forEach.call(grid.querySelectorAll(".shot img"), watchImage);

  // Re-run the rise-in on the cards that survived a filter change. The stagger is
  // capped so the 170th card doesn't wait two seconds for its turn.
  // One observer, cards unobserved once seen — no scroll handler, no per-frame work.
  if (!calm && "IntersectionObserver" in window) {
    grid.classList.add("reveal");
    cards.forEach(function (c) { c.classList.add("veil"); });
    var seen = new IntersectionObserver(function (entries, obs) {
      entries.forEach(function (en) {
        var el = en.target;
        if (!en.isIntersecting) {             // left the screen; stop scrubbing it
          var k = band.indexOf(el);
          if (k > -1) band.splice(k, 1);
          return;
        }
        el.classList.remove("veil");
        // A flick brings dozens of cards past at once; scrubbing them all is
        // both pointless — they are gone before you could watch one — and the
        // thing that makes a fast scroll stutter. So a deliberate scroll gets
        // the scrubbed reveal that tracks the finger, and a flick gets the
        // plain timed one. Whichever it picks is latched, so a card never
        // switches mode halfway through its own animation.
        if (calm || flicking()) {             // a flick: plain timed reveal
          el.classList.add("shown");
          obs.unobserve(el);
        } else {                              // scrubbed against scroll position
          if (band.indexOf(el) < 0) { el._p = -1; band.push(el); }
          requestScrub();                     // stays observed, so it can reverse
        }
      });
    }, { rootMargin: "80px 0px", threshold: 0.01 });
    cards.forEach(function (c) { seen.observe(c); });
    // safety net: anything still veiled after 3s is shown regardless
    setTimeout(function () {
      cards.forEach(function (c) {
        c.classList.remove("veil");
        // a card mid-scrub owns its own opacity; .shown would fight it
        if (band.indexOf(c) < 0) c.classList.add("shown");
      });
    }, 3000);
  }

  var RISE_MAX = 24;              // roughly a screenful; beyond that nobody sees it
  function settle() {
    band.length = 0;
    cards.forEach(function (c) {
      c.classList.remove("rise");
      c.style.opacity = ""; c.style.translate = ""; c._p = -1;
    });
    var first = [];
    for (var i = 0; i < cards.length && first.length < RISE_MAX; i++) {
      if (!cards[i].hidden) first.push(cards[i]);
    }
    void grid.offsetWidth;          // reflow, so the animation restarts
    first.forEach(function (c, n) { c.style.setProperty("--i", n); c.classList.add("rise"); });
  }

  function apply() {
    var shown = 0, t = term.trim().toLowerCase();
    cards.forEach(function (c) {
      var ok = (!fam   || c.dataset.fam === fam)
            && (!shelf || c.dataset.shelf === shelf)
            && (!t     || c.dataset.q.indexOf(t) > -1);
      c.hidden = !ok;
      if (ok) shown++;
    });
    setCount(shown, (shown === 1 ? " bottle" : " bottles")
      + (shelf ? " · " + shelf : "") + (fam ? " · " + fam : "")
      + (t ? ' · "' + term.trim() + '"' : ""));
    emptyEl.hidden = shown > 0;
    var pick = shelf || fam;
    history.replaceState(null, "", pick ? "#" + slug(pick) : " ");
  }

  // Tween the tally so a filter reads as a change rather than a jump cut.
  var countShown = cards.length, countRAF = null;
  function setCount(target, label) {
    if (countRAF) { cancelAnimationFrame(countRAF); countRAF = null; }
    if (calm || countShown === target) {
      countShown = target; countEl.textContent = target + label; return;
    }
    var from = countShown, t0 = performance.now(), dur = 340;
    (function tick(now) {
      var p = Math.min(1, (now - t0) / dur);
      var v = Math.round(from + (target - from) * (1 - Math.pow(1 - p, 3)));
      countEl.textContent = v + label;
      if (p < 1) { countRAF = requestAnimationFrame(tick); }
      else { countRAF = null; countShown = target; }
    })(t0);
  }

  function sortBy(mode) {
    cards.slice().sort(function (a, b) {
      var ap = parseFloat(a.dataset.price), bp = parseFloat(b.dataset.price),
          aa = parseFloat(a.dataset.abv),   ba = parseFloat(b.dataset.abv);
      // unpriced / unknown-strength bottles always sort last, never as zero
      if (mode === "price-asc")  return (ap < 0) - (bp < 0) || ap - bp;
      if (mode === "price-desc") return (ap < 0) - (bp < 0) || bp - ap;
      if (mode === "abv")        return (aa < 0) - (ba < 0) || ba - aa;
      return a.dataset.name.localeCompare(b.dataset.name);
    }).forEach(function (c) { grid.appendChild(c); });
  }

  var timer;
  qEl.addEventListener("input", function () {
    clearTimeout(timer);
    timer = setTimeout(function () { term = qEl.value; apply(); }, 110);
  });
  sortEl.addEventListener("change", function () { sortBy(sortEl.value); settle(); });

  chips.forEach(function (ch) {
    ch.addEventListener("click", function () {
      chips.forEach(function (o) { o.classList.remove("on"); o.setAttribute("aria-selected", "false"); });
      ch.classList.add("on"); ch.setAttribute("aria-selected", "true");
      shelf = ch.dataset.shelf || "";
      fam   = ch.dataset.fam   || "";
      catLabel.textContent = ch.querySelector("span").textContent || "All";
      closePicker();
      apply();
      settle();
      // after narrowing the list, don't leave the reader stranded below it
      var top = grid.getBoundingClientRect().top;
      if (top < -40) {
        window.scrollTo({ top: window.scrollY + top - 90, behavior: "smooth" });
      }
    });
  });

  // ---- mobile: the category picker the bottom island opens ----
  var chipsNav = document.getElementById("chips"),
      catBtn   = document.getElementById("catbtn"),
      catLabel = document.getElementById("catbtn-label"),
      scrim    = document.getElementById("scrim"),
      phoneMQ  = window.matchMedia("(max-width: 640px)");

  // Sort lives inside the picker at every size — the drawer is where someone is
  // already choosing how to look at the list.
  var sortWrap = sortEl.parentNode;
  function placeSort() {
    if (sortWrap.parentNode !== chipsNav) chipsNav.insertBefore(sortWrap, chipsNav.firstChild);
  }
  placeSort();

  // The category is its own floating island at every size, so it has to leave the
  // search island in the DOM as well as on screen: .tools carries a
  // backdrop-filter, and that makes it the containing block for any
  // position:fixed descendant — a category pinned to a corner from inside it
  // would anchor to the search capsule rather than to the viewport.
  var topEl = document.querySelector(".top");
  if (topEl && catBtn.parentNode !== topEl) topEl.appendChild(catBtn);
  // #chips ships inside <header class="top">, which is itself position:fixed
  // with its own z-index (30) — that makes .top a stacking context, so every
  // descendant's z-index (including #chips's 32) is compared to the rest of
  // the page using .top's z-index, not its own. #scrim sits at the body level
  // at z-index 31, so it painted OVER the entire header, picker included,
  // and silently ate every click on a category chip. Move #chips out to the
  // body too, the same way catBtn already is, so its z-index actually competes
  // against #scrim's in the same (root) stacking context.
  if (document.body && chipsNav.parentNode !== document.body) document.body.appendChild(chipsNav);

  phoneMQ.addEventListener("change", closePicker);

  function openPicker() {
    chipsNav.classList.add("open");
    catBtn.setAttribute("aria-expanded", "true");
    document.body.classList.add("picker-open");
    document.body.classList.remove("bar-hidden");
    scrim.hidden = false;
    void scrim.offsetWidth;                 // let the scrim paint before fading it in
    scrim.classList.add("open");
  }
  function closePicker() {
    chipsNav.classList.remove("open");
    chipsNav.style.transition = ""; chipsNav.style.transform = "";
    catBtn.setAttribute("aria-expanded", "false");
    document.body.classList.remove("picker-open");
    scrim.classList.remove("open");
    setTimeout(function () { if (!chipsNav.classList.contains("open")) scrim.hidden = true; }, 240);
  }
  function togglePicker() {
    chipsNav.classList.contains("open") ? closePicker() : openPicker();
  }
  // The island slides away while you scroll down and returns on the way up, so
  // it never sits on top of what you are reading. Passive + direction-only, so
  // there is no per-frame work while scrolling.
  var lastY = window.scrollY || 0;
  window.addEventListener("scroll", function (e) {
    var y = window.scrollY || 0;
    var now = e.timeStamp || performance.now();
    if (lastT) {
      var dt = Math.max(1, now - lastT);
      scrollV = scrollV * 0.6 + (Math.abs(y - lastY) / dt) * 0.4;
    }
    lastT = now;
    requestScrub();
    // Collapsing the field while it holds the caret hides what is being typed,
    // so scrolling only shrinks the island when the search is idle.
    if (y > lastY + 6 && y > 140 && !document.body.classList.contains("searching"))
      document.body.classList.add("bar-hidden");
    else if (y < lastY - 6 || y < 80) document.body.classList.remove("bar-hidden");
    // the floating header deepens its shadow once the catalogue is under it
    document.body.classList.toggle("scrolled", y > 8);
    lastY = y;
  }, { passive: true });

  // ---- keyboard-proof search ----
  // The island lives at the bottom of the screen, which is exactly where the
  // keyboard opens over it — so you type into a field you cannot see. Measuring
  // the keyboard and sitting just above it is the obvious fix and it is not
  // reliable: iOS does not shrink the layout viewport, it scrolls the visual one
  // independently, and the numbers arrive late, once, or not at all.
  //
  // So the island does not try to dodge the keyboard. While the field has focus
  // it moves to the TOP of the screen, which is the one place a keyboard can
  // never cover, and it travels by transform, so the move is composited and the
  // existing .tools transition animates it for free.
  var toolsEl = document.querySelector(".tools");
  var TOP_GAP = 10;
  function liftIsland() {
    if (!toolsEl) return;
    if (!phoneMQ.matches || !document.body.classList.contains("searching")) {
      document.documentElement.style.removeProperty("--lift");
      return;
    }
    var vv = window.visualViewport;
    var cs = getComputedStyle(toolsEl);
    // Landscape moors the island at the top already, where no keyboard reaches.
    // Without this the "auto" would read as 0 and the island would be flung off
    // the top of the screen.
    if (cs.bottom === "auto") {
      document.documentElement.style.removeProperty("--lift");
      return;
    }
    var r = toolsEl.getBoundingClientRect();
    // rect.height is unaffected by the transform, so this stays correct even
    // when the island is already lifted and we are only re-measuring
    var bottomPx = parseFloat(cs.bottom) || 0;
    var restingTop = window.innerHeight - bottomPx - r.height;
    // if the engine scrolled the visual viewport to reveal the field, the top of
    // what is actually on screen is no longer the top of the layout viewport
    var visibleTop = vv ? vv.offsetTop : 0;
    var lift = restingTop - visibleTop - TOP_GAP;
    document.documentElement.style.setProperty("--lift", Math.max(0, Math.round(lift)) + "px");
  }
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", liftIsland);
    window.visualViewport.addEventListener("scroll", liftIsland);
  }
  window.addEventListener("orientationchange", function () { setTimeout(liftIsland, 120); });

  qEl.addEventListener("focus", function () {
    document.body.classList.add("searching");
    document.body.classList.remove("bar-hidden");   // undo any collapse in progress
    liftIsland();
  });
  qEl.addEventListener("blur", function () {
    document.body.classList.remove("searching");
    liftIsland();                                   // drops --lift, island falls back
  });

  // A droplet of light blooms from where the finger lands and spreads across the
  // glass. Sized to cover the control so it reads as the surface reacting, not a dot.
  function droplet(e) {
    if (calm) return;
    var el = e.currentTarget, r = el.getBoundingClientRect();
    var p = e.touches ? e.touches[0] : e;
    var d = Math.max(r.width, r.height) * 2.2;
    var n = document.createElement("span");
    n.className = "droplet";
    n.style.setProperty("--x", ((p.clientX - r.left) || r.width / 2) + "px");
    n.style.setProperty("--y", ((p.clientY - r.top) || r.height / 2) + "px");
    n.style.setProperty("--d", d + "px");
    el.appendChild(n);
    setTimeout(function () { n.remove(); }, 640);
  }
  function dropletOn(el) {
    if (!el) return;
    el.addEventListener("touchstart", droplet, { passive: true });
    el.addEventListener("mousedown", droplet);
  }
  chips.forEach(dropletOn);
  dropletOn(catBtn);

  catBtn.addEventListener("click", togglePicker);

  // Swipe the drawer back off the right edge. Axis is locked on the first few
  // pixels so flicking down the list never drags it sideways.
  var dx0 = 0, dy0 = 0, drawerAxis = null, drawerDrag = false;
  chipsNav.addEventListener("touchstart", function (e) {
    if (e.touches.length !== 1) { drawerDrag = false; return; }
    dx0 = e.touches[0].clientX; dy0 = e.touches[0].clientY;
    drawerAxis = null; drawerDrag = true;
  }, { passive: true });
  chipsNav.addEventListener("touchmove", function (e) {
    if (!drawerDrag || e.touches.length !== 1) return;
    var dx = e.touches[0].clientX - dx0, dy = e.touches[0].clientY - dy0;
    if (drawerAxis === null) {
      if (Math.abs(dx) < 6 && Math.abs(dy) < 6) return;
      drawerAxis = Math.abs(dx) > Math.abs(dy) * 1.3 ? "x" : "y";
      if (drawerAxis === "y") { drawerDrag = false; return; }
      chipsNav.style.transition = "none";
    }
    chipsNav.style.transform = "translateX(" + Math.max(0, dx) + "px)";
  }, { passive: true });
  function endDrawerDrag(e) {
    if (!drawerDrag) return;
    drawerDrag = false;
    var dx = e.changedTouches ? e.changedTouches[0].clientX - dx0 : 0;
    chipsNav.style.transition = "";
    chipsNav.style.transform = "";
    if (drawerAxis === "x" && dx > 70) closePicker();
  }
  chipsNav.addEventListener("touchend", endDrawerDrag, { passive: true });
  chipsNav.addEventListener("touchcancel", endDrawerDrag, { passive: true });
  scrim.addEventListener("click", closePicker);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && chipsNav.classList.contains("open")) { closePicker(); catBtn.focus(); }
  });

  // deep link: #whisky or #limited-edition opens that shelf on load
  if (location.hash) {
    var want = location.hash.slice(1).toLowerCase();
    var hit = chips.filter(function (c) {
      var v = c.dataset.shelf || c.dataset.fam;
      return v && slug(v) === want;
    })[0];
    if (hit) hit.click();
  }

  // ---- detail sheet ----
  var openCard = null, shots = [], photoIdx = 0, body = dlg.querySelector(".dlg-body"),
      prevBtn = document.getElementById("prev"),
      nextBtn = document.getElementById("next"),
      closeBtn = document.getElementById("closebtn"),
      posEl   = document.getElementById("pos");

  [prevBtn, nextBtn, closeBtn].forEach(dropletOn);

  function visible() { return cards.filter(function (c) { return !c.hidden; }); }

  // Chevrons and an "n of m" counter, so the swipe is discoverable rather than hidden.
  function syncNav() {
    var vis = visible(), i = vis.indexOf(openCard);
    posEl.textContent = i < 0 ? "" : (i + 1) + " / " + vis.length;
    prevBtn.disabled = i <= 0;
    nextBtn.disabled = i < 0 || i >= vis.length - 1;
  }

  function render(card, from) {
    var img = card.querySelector(".shot img"), rows = "";
    var meta = card.querySelector(".meta").textContent.trim();
    if (meta) {
      meta.split("\u00b7").forEach(function (part) {
        part = part.trim(); if (!part) return;
        var label = /ABV/i.test(part) ? "Strength" : /^\d{4}$/.test(part) ? "Vintage" : "Size";
        rows += "<div><dt>" + label + "</dt><dd>" + part + "</dd></div>";
      });
    }
    rows += "<div><dt>Category</dt><dd>" + card.dataset.fam + "</dd></div>";
    if (card.dataset.shelf) rows += "<div><dt>Shelf</dt><dd>" + card.dataset.shelf + "</dd></div>";
    body.className = "dlg-body";
    if (from) { void body.offsetWidth; body.classList.add(from); }
    shots = (card.dataset.imgs || "").split(",").filter(Boolean);
    photoIdx = 0;
    var dots = shots.length > 1
      ? '<div class="dots">' + shots.map(function (_, i) {
          return "<i" + (i === 0 ? ' class="on"' : "") + "></i>";
        }).join("") + "</div>"
      : "";
    var first = shots.length ? "img/" + shots[0] + ".jpg" : img.getAttribute("src");
    body.innerHTML =
      '<div class="dlg-shot"><img src="' + first + '" alt="' + img.getAttribute("alt") + '">' + dots + "</div>" +
      '<div class="dlg-txt">' + card.querySelector(".brand").outerHTML +
        "<h2>" + card.querySelector(".nm").textContent + "</h2>" +
        card.querySelector(".price").outerHTML +
        '<dl class="rows">' + rows + "</dl></div>";
    openCard = card;
    dlg.scrollTop = 0;
    syncNav();
  }

  function open(card) {
    render(card);
    if (typeof dlg.showModal === "function") dlg.showModal();
  }

  // Move to the neighbouring bottle within whatever is currently filtered in.
  function nextCard(dir) {
    if (!openCard) return null;
    var vis = visible(), i = vis.indexOf(openCard);
    return i < 0 ? null : (vis[i + dir] || null);
  }

  // `quiet` swaps the content with no entry animation of its own — the swipe is
  // already mid-flight and drives the motion itself.
  function step(dir, quiet) {
    var next = nextCard(dir);
    if (!next) return;                       // ends of the list are hard stops, as on iOS
    render(next, quiet ? null : (dir > 0 ? "from-r" : "from-l"));
  }

  // Swap the photo in place. Only ever called from inside the image area.
  function stepPhoto(dir, quiet) {
    if (shots.length < 2) return false;
    var next = photoIdx + dir;
    if (next < 0 || next >= shots.length) return false;
    photoIdx = next;
    var el = body.querySelector(".dlg-shot img");
    if (!el) return false;
    el.classList.remove("from-l", "from-r");
    void el.offsetWidth;
    el.src = "img/" + shots[photoIdx] + ".jpg";
    if (!quiet) el.classList.add(dir > 0 ? "from-r" : "from-l");
    var ds = body.querySelectorAll(".dots i");
    for (var i = 0; i < ds.length; i++) ds[i].classList.toggle("on", i === photoIdx);
    return true;
  }

  function closeSheet() {
    dlg.classList.remove("dragging");
    dlg.style.transform = ""; dlg.style.opacity = "";
    clearScrub(body);
    gen++;
    dlg.close();
  }

  // ---- pointer sheen ----
  // Light moving across glass: the card's ::after highlight is positioned from
  // --mx/--my. One delegated listener for the whole grid rather than 170, and
  // the write is deferred to the next frame so a fast sweep across the
  // catalogue cannot schedule a layout read per mousemove.
  if (!calm && window.matchMedia("(hover: hover)").matches) {
    var sheenCard = null, sheenX = 0, sheenY = 0, sheenQueued = false;
    function paintSheen() {
      sheenQueued = false;
      if (!sheenCard) return;
      var r = sheenCard.getBoundingClientRect();
      sheenCard.style.setProperty("--mx", (sheenX - r.left) + "px");
      sheenCard.style.setProperty("--my", (sheenY - r.top) + "px");
    }
    grid.addEventListener("pointermove", function (e) {
      if (e.pointerType !== "mouse") return;
      var c = e.target.closest(".card");
      if (!c) { sheenCard = null; return; }
      sheenCard = c; sheenX = e.clientX; sheenY = e.clientY;
      if (!sheenQueued) { sheenQueued = true; requestAnimationFrame(paintSheen); }
    }, { passive: true });
    grid.addEventListener("pointerleave", function () { sheenCard = null; }, { passive: true });
  }

  // ---- press feedback ----
  // :active alone is unreliable on touch (iOS needs a touch listener present, and
  // browsers delay it to tell a tap from a scroll). Driving it explicitly makes the
  // highlight land on touchdown, and we drop it the moment the finger travels,
  // so scrolling past a card never lights it up.
  var pressedCard = null, pressX = 0, pressY = 0;
  function clearPress() {
    if (pressedCard) { pressedCard.classList.remove("pressed"); pressedCard = null; }
  }
  grid.addEventListener("touchstart", function (e) {
    var c = e.target.closest(".card"); if (!c) return;
    pressedCard = c; pressX = e.touches[0].clientX; pressY = e.touches[0].clientY;
    c.classList.add("pressed");
  }, { passive: true });
  grid.addEventListener("touchmove", function (e) {
    if (!pressedCard) return;
    var t = e.touches[0];
    if (Math.abs(t.clientX - pressX) > 8 || Math.abs(t.clientY - pressY) > 8) clearPress();
  }, { passive: true });
  grid.addEventListener("touchend", clearPress, { passive: true });
  grid.addEventListener("touchcancel", clearPress, { passive: true });

  grid.addEventListener("click", function (e) {
    var c = e.target.closest(".card"); if (c) { clearPress(); open(c); }
  });
  grid.addEventListener("keydown", function (e) {
    if (e.key !== "Enter" && e.key !== " ") return;
    var c = e.target.closest(".card"); if (c) { e.preventDefault(); open(c); }
  });
  prevBtn.addEventListener("click", function () { step(-1); });
  nextBtn.addEventListener("click", function () { step(1); });
  document.getElementById("x").addEventListener("click", closeSheet);
  if (closeBtn) closeBtn.addEventListener("click", closeSheet);
  dlg.addEventListener("click", function (e) { if (e.target === dlg) closeSheet(); });
  dlg.addEventListener("close", function () {
    dlg.classList.remove("dragging");
    dlg.style.transform = ""; dlg.style.opacity = "";
    clearScrub(body);            // Escape can close it mid-swipe
    gen++;
  });
  // arrow keys mirror the swipe on desktop
  document.addEventListener("keydown", function (e) {
    if (!dlg.open) return;
    if (e.key === "ArrowRight") { e.preventDefault(); step(1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); step(-1); }
  });

  // ---- iOS-style sheet gestures (touch, phone layout only) ----
  // The swipe is scrubbed, not triggered: the content tracks the finger one to
  // one, so a slow drag moves it slowly and you can see the half-way state and
  // change your mind. On release it finishes the journey at the speed you let
  // go at, which is what keeps a flick snappy and a slow drag from snapping.
  var phone = window.matchMedia("(max-width: 640px)");
  var y0 = 0, x0 = 0, t0 = 0, dy = 0, dx = 0, axis = null, tracking = false, inImage = false;
  var scrubEl = null, scrubPhoto = false;
  var frame = null, pendY = 0, pendX = 0;
  // Every touch starts a new generation. A glide that finishes after the finger
  // is already down again belongs to the last one and must not touch anything,
  // or it would wipe the transform the new drag is busy setting.
  var gen = 0;

  function lim(v, a, b) { return v < a ? a : v > b ? b : v; }
  function sheetW() { return dlg.clientWidth || window.innerWidth || 360; }
  function canGo(dir) {
    return scrubPhoto
      ? (photoIdx + dir >= 0 && photoIdx + dir < shots.length)
      : !!nextCard(dir);
  }

  function paintDrag() {
    frame = null;
    if (axis === "y") {
      dlg.style.transform = "translateY(" + pendY + "px)";
      dlg.style.opacity = String(Math.max(0.45, 1 - pendY / 520));
    } else if (axis === "x" && scrubEl) {
      scrubEl.style.transform = "translateX(" + pendX + "px)";
      // it thins out as it travels, so the swap at the far end is never a cut
      scrubEl.style.opacity = String(lim(1 - Math.abs(pendX) / (sheetW() * 0.9), 0.18, 1));
    }
  }
  function schedule() { if (frame === null) frame = requestAnimationFrame(paintDrag); }

  function clearScrub(el) {
    if (!el) return;
    el.style.transition = ""; el.style.transform = ""; el.style.opacity = "";
  }
  function stopDrag() {
    if (frame !== null) { cancelAnimationFrame(frame); frame = null; }
    tracking = false;
    dlg.classList.remove("dragging");
    dlg.style.transform = ""; dlg.style.opacity = "";
    clearScrub(scrubEl); scrubEl = null;
  }

  // One transition, its duration taken from the speed of the finger rather than
  // a constant — that is the whole difference between smooth and clunky here.
  function glide(el, x, op, ms, done) {
    el.style.transition = "transform " + ms + "ms cubic-bezier(.22,.68,.32,1)," +
                          "opacity " + ms + "ms ease";
    el.style.transform = "translateX(" + x + "px)";
    el.style.opacity = String(op);
    var fired = false, g = gen;
    function end() {
      if (fired) return;
      fired = true;
      el.removeEventListener("transitionend", end);
      if (g !== gen) return;           // superseded by a newer gesture
      if (done) done();
    }
    el.addEventListener("transitionend", end);
    setTimeout(end, ms + 90);     // transitionend never arrives if nothing moved
  }

  function finishSwipe(commit, dir, speed) {
    if (frame !== null) { cancelAnimationFrame(frame); frame = null; }
    dlg.classList.remove("dragging");
    var el = scrubEl, wasPhoto = scrubPhoto;
    scrubEl = null;
    if (!el) return;

    if (calm) {                                   // reduced motion: just arrive
      clearScrub(el);
      if (commit) { if (wasPhoto) stepPhoto(dir, true); else step(dir, true); }
      return;
    }
    if (!commit) {
      // travel back over the distance actually covered, at the speed of release
      var back = lim(Math.abs(pendX) / Math.max(speed, 0.5), 140, 280);
      glide(el, 0, 1, back, function () { clearScrub(el); });
      return;
    }
    var w = sheetW(), out = dir > 0 ? -w * 0.45 : w * 0.45;
    var ms = lim(Math.abs(out - pendX) / Math.max(speed, 0.45), 120, 300);
    glide(el, out, 0, ms, function () {
      if (wasPhoto) stepPhoto(dir, true); else step(dir, true);
      // render() rebuilds .dlg-body in place, so the element to bring back in is
      // the same one for bottles, and the same <img> for photos
      var target = wasPhoto ? body.querySelector(".dlg-shot img") : body;
      clearScrub(el);
      if (!target) return;
      target.style.transition = "none";
      target.style.transform = "translateX(" + (dir > 0 ? w * 0.45 : -w * 0.45) + "px)";
      target.style.opacity = "0";
      void target.offsetWidth;                    // commit the start position
      glide(target, 0, 1, ms, function () { clearScrub(target); });
    });
  }

  dlg.addEventListener("touchstart", function (e) {
    if (!phone.matches || e.touches.length !== 1) { tracking = false; return; }
    var t = e.touches[0];
    y0 = t.clientY; x0 = t.clientX; t0 = e.timeStamp;
    dy = 0; dx = 0; pendX = 0; axis = null; tracking = true; gen++;
    // Where the gesture began decides what a sideways swipe means — photos under
    // the picture, bottles everywhere else. It no longer decides whether the
    // sheet responds at all.
    inImage = !!(e.target.closest && e.target.closest(".dlg-shot"));
  }, { passive: true });

  dlg.addEventListener("touchmove", function (e) {
    if (!tracking || e.touches.length !== 1) return;
    var t = e.touches[0];
    dy = t.clientY - y0; dx = t.clientX - x0;

    if (axis === null) {
      if (Math.abs(dx) < 6 && Math.abs(dy) < 6) return;
      // bias towards vertical, so a slightly-diagonal pull still scrolls or dismisses
      axis = Math.abs(dx) > Math.abs(dy) * 1.3 ? "x" : "y";
      if (axis === "y" && (dlg.scrollTop > 0 || dy < 0)) { tracking = false; return; }
      if (axis === "x") {
        // drag exactly the thing that is going to change
        scrubPhoto = inImage && shots.length > 1;
        scrubEl = scrubPhoto ? body.querySelector(".dlg-shot img") : body;
        if (!scrubEl) { tracking = false; return; }
        scrubEl.style.transition = "none";
        scrubEl.classList.remove("from-l", "from-r");
      }
      dlg.classList.add("dragging");
    }

    e.preventDefault();
    if (axis === "y") {
      pendY = dy;
    } else {
      // one to one where there is somewhere to go; the ends of the list pull back
      pendX = canGo(dx < 0 ? 1 : -1) ? dx : dx * 0.14;
    }
    schedule();
  }, { passive: false });


  dlg.addEventListener("touchend", function (e) {
    if (!tracking) return;
    tracking = false;
    var dt = Math.max(1, e.timeStamp - t0), vy = dy / dt, vx = dx / dt;

    if (axis === "x") {
      var dir = dx < 0 ? 1 : -1;
      // a short flick counts as much as a long slow drag
      var commit = canGo(dir) &&
        (Math.abs(dx) > sheetW() * 0.28 || Math.abs(vx) > 0.5);
      finishSwipe(commit, dir, Math.abs(vx));
      return;
    }
    var dismiss = axis === "y" && (dy > 110 || vy > 0.55);
    stopDrag();
    if (dismiss) closeSheet();
  });

  dlg.addEventListener("touchcancel", stopDrag);
})();
