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
  function watchImage(img) {
    if (img.complete && img.naturalWidth) { img.classList.add("ready"); return; }
    img.addEventListener("load", function () { img.classList.add("ready"); }, { once: true });
    img.addEventListener("error", function () { img.classList.add("ready"); }, { once: true });
  }
  Array.prototype.forEach.call(grid.querySelectorAll(".shot img"), watchImage);

  // Re-run the rise-in on the cards that survived a filter change. The stagger is
  // capped so the 170th card doesn't wait two seconds for its turn.
  var RISE_MAX = 24;              // roughly a screenful; beyond that nobody sees it
  function settle() {
    cards.forEach(function (c) { c.classList.remove("rise"); });
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
    countEl.textContent = shown + (shown === 1 ? " bottle" : " bottles")
      + (shelf ? " · " + shelf : "") + (fam ? " · " + fam : "")
      + (t ? ' · "' + term.trim() + '"' : "");
    emptyEl.hidden = shown > 0;
    var pick = shelf || fam;
    history.replaceState(null, "", pick ? "#" + slug(pick) : " ");
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

  // Sort belongs inside the picker on phones — the island has room for two controls, not three.
  var sortWrap = sortEl.parentNode;
  function placeSort() {
    var target = phoneMQ.matches ? chipsNav : document.querySelector(".tools");
    if (sortWrap.parentNode !== target) {
      phoneMQ.matches ? target.insertBefore(sortWrap, target.firstChild) : target.appendChild(sortWrap);
    }
  }
  placeSort();
  phoneMQ.addEventListener("change", function () { placeSort(); closePicker(); });

  function openPicker() {
    chipsNav.classList.add("open");
    catBtn.setAttribute("aria-expanded", "true");
    document.body.classList.add("picker-open");
    scrim.hidden = false;
    void scrim.offsetWidth;                 // let the scrim paint before fading it in
    scrim.classList.add("open");
  }
  function closePicker() {
    chipsNav.classList.remove("open");
    catBtn.setAttribute("aria-expanded", "false");
    document.body.classList.remove("picker-open");
    scrim.classList.remove("open");
    setTimeout(function () { if (!chipsNav.classList.contains("open")) scrim.hidden = true; }, 240);
  }
  function togglePicker() {
    chipsNav.classList.contains("open") ? closePicker() : openPicker();
  }
  catBtn.addEventListener("click", togglePicker);
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
  var openCard = null, body = dlg.querySelector(".dlg-body"),
      prevBtn = document.getElementById("prev"),
      nextBtn = document.getElementById("next"),
      posEl   = document.getElementById("pos");

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
    body.innerHTML =
      '<div class="dlg-shot"><img src="' + img.getAttribute("src") + '" alt="' + img.getAttribute("alt") + '"></div>' +
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
  function step(dir) {
    if (!openCard) return;
    var vis = visible(), i = vis.indexOf(openCard);
    if (i < 0) return;
    var next = vis[i + dir];
    if (!next) return;                       // ends of the list are hard stops, as on iOS
    render(next, dir > 0 ? "from-r" : "from-l");
  }

  function closeSheet() {
    dlg.classList.remove("dragging");
    dlg.style.transform = ""; dlg.style.opacity = "";
    dlg.close();
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
  dlg.addEventListener("click", function (e) { if (e.target === dlg) closeSheet(); });
  dlg.addEventListener("close", function () {
    dlg.classList.remove("dragging");
    dlg.style.transform = ""; dlg.style.opacity = "";
  });
  // arrow keys mirror the swipe on desktop
  document.addEventListener("keydown", function (e) {
    if (!dlg.open) return;
    if (e.key === "ArrowRight") { e.preventDefault(); step(1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); step(-1); }
  });

  // ---- iOS-style sheet gestures (touch, phone layout only) ----
  var phone = window.matchMedia("(max-width: 640px)");
  var y0 = 0, x0 = 0, t0 = 0, dy = 0, dx = 0, axis = null, tracking = false;
  // Touch events can outpace the display. Coalescing the writes into one
  // requestAnimationFrame keeps the sheet on the frame clock instead of
  // thrashing style on every event.
  var frame = null, pendY = 0, pendX = 0;
  function paintDrag() {
    frame = null;
    if (axis === "y") {
      dlg.style.transform = "translateY(" + pendY + "px)";
      dlg.style.opacity = String(Math.max(0.45, 1 - pendY / 520));
    } else if (axis === "x") {
      dlg.style.transform = "translateX(" + pendX + "px)";
    }
  }
  function schedule() { if (frame === null) frame = requestAnimationFrame(paintDrag); }
  function stopDrag() {
    if (frame !== null) { cancelAnimationFrame(frame); frame = null; }
    tracking = false;
    dlg.classList.remove("dragging");
    dlg.style.transform = ""; dlg.style.opacity = "";
  }

  dlg.addEventListener("touchstart", function (e) {
    if (!phone.matches || e.touches.length !== 1) { tracking = false; return; }
    var t = e.touches[0];
    y0 = t.clientY; x0 = t.clientX; t0 = e.timeStamp;
    dy = 0; dx = 0; axis = null; tracking = true;
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
      dlg.classList.add("dragging");
    }

    e.preventDefault();
    if (axis === "y") {
      pendY = dy;
    } else {
      // resist horizontally — the sheet hints at the move rather than following it
      var edge = (dx < 0 && !nextExists(1)) || (dx > 0 && !nextExists(-1));
      pendX = dx * (edge ? 0.08 : 0.22);
    }
    schedule();
  }, { passive: false });

  function nextExists(dir) {
    if (!openCard) return false;
    var vis = visible(), i = vis.indexOf(openCard);
    return i >= 0 && !!vis[i + dir];
  }

  dlg.addEventListener("touchend", function (e) {
    if (!tracking) return;
    var dt = Math.max(1, e.timeStamp - t0), vy = dy / dt, vx = dx / dt;
    var dismiss = axis === "y" && (dy > 110 || vy > 0.55);
    var stepped = axis === "x" && (Math.abs(dx) > 70 || Math.abs(vx) > 0.5);
    stopDrag();                       // cancels any queued frame, springs back
    if (dismiss) { closeSheet(); return; }
    if (stepped) step(dx < 0 ? 1 : -1);
  });

  dlg.addEventListener("touchcancel", stopDrag);
})();
