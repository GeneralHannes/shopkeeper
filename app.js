(function () {
  "use strict";
  var grid  = document.getElementById("grid"),
      cards = Array.prototype.slice.call(grid.querySelectorAll(".card")),
      qEl   = document.getElementById("q"),
      sortEl= document.getElementById("sort"),
      countEl=document.getElementById("count"),
      emptyEl=document.getElementById("empty"),
      chips = Array.prototype.slice.call(document.querySelectorAll(".chip")),
      dlg   = document.getElementById("dlg"),
      fam   = "", term = "", special = false;

  function apply() {
    var shown = 0, t = term.trim().toLowerCase();
    cards.forEach(function (c) {
      var ok = (!fam || c.dataset.fam === fam)
        && (!special || c.dataset.special === "1")
        && (!t || c.dataset.q.indexOf(t) > -1);
      c.hidden = !ok;
      if (ok) shown++;
    });
    countEl.textContent = shown + (shown === 1 ? " bottle" : " bottles")
      + (fam ? " · " + fam : "") + (special ? " · Special" : "") + (t ? ' · "' + term.trim() + '"' : "");
    emptyEl.hidden = shown > 0;
    // keep the URL shareable / linkable for a category
    var u = special ? "#special" : fam ? "#" + fam.toLowerCase().replace(/[^a-z0-9]+/g, "-") : " ";
    history.replaceState(null, "", u);
  }

  function sortBy(mode) {
    var s = cards.slice().sort(function (a, b) {
      var ap = parseFloat(a.dataset.price), bp = parseFloat(b.dataset.price),
          aa = parseFloat(a.dataset.abv),   ba = parseFloat(b.dataset.abv);
      if (mode === "price-asc")  return (ap < 0) - (bp < 0) || ap - bp;
      if (mode === "price-desc") return (ap < 0) - (bp < 0) || bp - ap;
      if (mode === "abv")        return (aa < 0) - (ba < 0) || ba - aa;
      return a.dataset.name.localeCompare(b.dataset.name);
    });
    s.forEach(function (c) { grid.appendChild(c); });
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
      special = ch.dataset.special === "1";
      fam = special ? "" : ch.dataset.fam;
      apply();
    });
  });

  // deep link: #whisky selects that category on load
  if (location.hash) {
    var want = location.hash.slice(1).toLowerCase();
    var hit = chips.filter(function (c) {
      if (want === "special") return c.dataset.special === "1";
      return c.dataset.fam && c.dataset.fam.toLowerCase().replace(/[^a-z0-9]+/g, "-") === want;
    })[0];
    if (hit) hit.click();
  }

  // ---- detail dialog ----
  function open(card) {
    var img = card.querySelector(".shot img");
    var rows = "";
    var meta = card.querySelector(".meta").textContent.trim();
    if (meta && meta !== " ") {
      meta.split("·").forEach(function (part) {
        part = part.trim(); if (!part) return;
        var label = /ABV/i.test(part) ? "Strength" : /^\d{4}$/.test(part) ? "Vintage" : "Size";
        rows += "<div><dt>" + label + "</dt><dd>" + part + "</dd></div>";
      });
    }
    rows += "<div><dt>Category</dt><dd>" + card.dataset.fam + "</dd></div>";
    dlg.querySelector(".dlg-body").innerHTML =
      '<div class="dlg-shot"><img src="' + img.getAttribute("src") + '" alt="' + img.getAttribute("alt") + '"></div>' +
      '<div class="dlg-txt">' +
        card.querySelector(".brand").outerHTML +
        "<h2>" + card.querySelector(".nm").textContent + "</h2>" +
        card.querySelector(".price").outerHTML +
        '<dl class="rows">' + rows + "</dl>" +
      "</div>";
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
