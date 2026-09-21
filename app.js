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
  sortEl.addEventListener("change", function () { sortBy(sortEl.value); });

  chips.forEach(function (ch) {
    ch.addEventListener("click", function () {
      chips.forEach(function (o) { o.classList.remove("on"); o.setAttribute("aria-selected", "false"); });
      ch.classList.add("on"); ch.setAttribute("aria-selected", "true");
      shelf = ch.dataset.shelf || "";
      fam   = ch.dataset.fam   || "";
      apply();
    });
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

  function open(card) {
    var img = card.querySelector(".shot img"), rows = "";
    var meta = card.querySelector(".meta").textContent.trim();
    if (meta) {
      meta.split("·").forEach(function (part) {
        part = part.trim(); if (!part) return;
        var label = /ABV/i.test(part) ? "Strength" : /^\d{4}$/.test(part) ? "Vintage" : "Size";
        rows += "<div><dt>" + label + "</dt><dd>" + part + "</dd></div>";
      });
    }
    rows += "<div><dt>Category</dt><dd>" + card.dataset.fam + "</dd></div>";
    if (card.dataset.shelf) rows += "<div><dt>Shelf</dt><dd>" + card.dataset.shelf + "</dd></div>";
    dlg.querySelector(".dlg-body").innerHTML =
      '<div class="dlg-shot"><img src="' + img.getAttribute("src") + '" alt="' + img.getAttribute("alt") + '"></div>' +
      '<div class="dlg-txt">' + card.querySelector(".brand").outerHTML +
        "<h2>" + card.querySelector(".nm").textContent + "</h2>" +
        card.querySelector(".price").outerHTML +
        '<dl class="rows">' + rows + "</dl></div>";
    if (typeof dlg.showModal === "function") dlg.showModal();
  }
  grid.addEventListener("click", function (e) {
    var c = e.target.closest(".card"); if (c) open(c);
  });
  grid.addEventListener("keydown", function (e) {
    if (e.key !== "Enter" && e.key !== " ") return;
    var c = e.target.closest(".card"); if (c) { e.preventDefault(); open(c); }
  });
  document.getElementById("x").addEventListener("click", function () { dlg.close(); });
  dlg.addEventListener("click", function (e) { if (e.target === dlg) dlg.close(); });
})();
