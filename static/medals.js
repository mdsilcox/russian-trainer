// Medallions: the ceremony toast (every page), the detail panel and hover tilt (dashboard).
(function () {
  "use strict";

  var script = document.currentScript;
  var CSS_HREF = script && script.src ? script.src.replace(/medals\.js(\?.*)?$/, "medals.css") : "/static/medals.css";
  var SEEN_KEY = "medals:lastCheck";
  var DEBOUNCE_MS = 30000;
  var TOAST_MS = 7000;
  var HUES = ["#E2C46A", "#C9A227", "#F3E9D2"];

  function reduced() {
    try { return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches); }
    catch (e) { return false; }
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function ensureCss() {
    var links = document.querySelectorAll('link[rel="stylesheet"]');
    for (var i = 0; i < links.length; i++) {
      if (links[i].href.indexOf("medals.css") !== -1) return Promise.resolve();
    }
    return new Promise(function (resolve) {
      var link = el("link");
      link.rel = "stylesheet";
      link.href = CSS_HREF;
      link.onload = link.onerror = function () { resolve(); };
      document.head.appendChild(link);
    });
  }

  // ---- the stage: one at a time ----------------------------------------------------------

  var current = null; // {root, close}

  function closeCurrent() {
    if (current) current.close();
  }

  function flecks(wrap) {
    for (var i = 0; i < 12; i++) {
      var a = (i / 12) * Math.PI * 2 + 0.2;
      var r = i % 2 === 0 ? 150 : 124;
      var sz = i % 3 === 0 ? 7 : 5;
      var f = el("span", "fleck");
      f.style.cssText = "--dx:" + Math.round(Math.cos(a) * r) + "px;--dy:" + Math.round(Math.sin(a) * r) +
        "px;width:" + sz + "px;height:" + sz + "px;margin:-" + sz / 2 + "px 0 0 -" + sz / 2 +
        "px;background:" + HUES[i % 3] + ";animation-delay:" + (330 + (i % 4) * 45) + "ms";
      wrap.appendChild(f);
    }
  }

  /** opts: {mode: "toast"|"panel", ru, en, story, art (trusted SVG markup), onClose} */
  function show(opts) {
    closeCurrent();
    var panel = opts.mode === "panel";
    var restore = document.activeElement;
    var root = el("div", panel ? "mback" : "mback toastpos");
    var stage = el("div", "mstage " + (panel ? "panel" : "toast"));
    stage.setAttribute("role", panel ? "dialog" : "status");
    if (panel) stage.setAttribute("aria-modal", "true");
    stage.setAttribute("aria-label", (panel ? "Medallion: " : "New medallion: ") + opts.ru.replace(/́/g, "") + ", " + opts.en);
    stage.tabIndex = -1;

    var x = el("button", "xbtn", "×");
    x.type = "button";
    x.setAttribute("aria-label", "Close");
    stage.appendChild(x);

    stage.appendChild(el("span", "kick new-kick", "New medallion"));
    var kick = el("span", "kick panel-kick");
    kick.appendChild(document.createTextNode("Medallion · "));
    var kr = el("span", null, "Награ́да");
    kr.lang = "ru";
    kick.appendChild(kr);
    stage.appendChild(kick);

    var cer = el("div", reduced() ? "" : "cer");
    cer.style.cssText = "display:flex;flex-direction:column;align-items:center;gap:10px";
    var medal = el("div", "stagemedal");
    var drop = el("span", "drop");
    drop.innerHTML = opts.art; // markup is rendered server-side from fixed templates
    medal.appendChild(drop);
    if (!reduced()) flecks(medal);
    cer.appendChild(medal);
    var ribbon = el("div", "ribbon");
    var rs = el("span", null, opts.ru);
    rs.lang = "ru";
    ribbon.appendChild(rs);
    cer.appendChild(ribbon);
    stage.appendChild(cer);

    stage.appendChild(el("span", "cen", opts.en));
    stage.appendChild(el("p", "story", opts.story || ""));

    var links = el("div", "toast-links");
    var a = el("a", null, "View all");
    a.href = "/dashboard#medals";
    links.appendChild(a);
    stage.appendChild(links);

    var btns = el("div", "stbtns");
    var replay = el("button", "tbtn gold", "Replay ceremony");
    replay.type = "button";
    var close2 = el("button", "tbtn ghost", "Close");
    close2.type = "button";
    btns.appendChild(replay);
    btns.appendChild(close2);
    stage.appendChild(btns);

    root.appendChild(stage);
    document.body.appendChild(root);

    var timer = null;
    var done = false;
    function close() {
      if (done) return;
      done = true;
      clearTimeout(timer);
      document.removeEventListener("keydown", onKey, true);
      if (root.parentNode) root.parentNode.removeChild(root);
      if (current && current.root === root) current = null;
      // Put focus back only if it was lost with the stage (never steal it from the page).
      if (panel && restore && restore.focus && document.body.contains(restore)) restore.focus();
      if (opts.onClose) opts.onClose();
    }
    function onKey(e) {
      if (e.key === "Escape") { e.stopPropagation(); close(); return; }
      if (panel && e.key === "Tab") { // keep focus inside the dialog
        var f = stage.querySelectorAll("button, a[href]");
        var visible = Array.prototype.filter.call(f, function (n) { return n.offsetParent !== null; });
        if (!visible.length) return;
        var first = visible[0], last = visible[visible.length - 1];
        if (e.shiftKey && (document.activeElement === first || document.activeElement === stage)) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    }
    document.addEventListener("keydown", onKey, true);
    x.addEventListener("click", close);
    close2.addEventListener("click", close);
    replay.addEventListener("click", function () {
      var again = Object.assign({}, opts, { onClose: null });
      var oc = opts.onClose;
      close();
      setTimeout(function () { show(Object.assign(again, { onClose: oc })); }, 70);
    });
    if (panel) {
      root.addEventListener("click", function (e) { if (e.target === root) close(); });
      x.focus();
    } else {
      var arm = function () { clearTimeout(timer); timer = setTimeout(close, TOAST_MS); };
      stage.addEventListener("mouseenter", function () { clearTimeout(timer); });
      stage.addEventListener("mouseleave", arm);
      stage.addEventListener("focusin", function () { clearTimeout(timer); });
      stage.addEventListener("focusout", arm);
      arm();
    }
    current = { root: root, close: close };
    return current;
  }

  // ---- toast on every page ---------------------------------------------------------------

  function showQueue(list) {
    if (!list.length) return;
    var m = list.shift();
    ensureCss().then(function () {
      show({
        mode: "toast", ru: m.ru, en: m.en, story: m.story, art: m.art,
        onClose: function () { if (list.length) setTimeout(function () { showQueue(list); }, 400); },
      });
      fetch("/medals/" + encodeURIComponent(m.key) + "/seen", { method: "POST" }).catch(function () {});
    });
  }

  function checkPending() {
    try {
      var last = Number(sessionStorage.getItem(SEEN_KEY) || 0);
      if (last && Date.now() - last < DEBOUNCE_MS) return;
      sessionStorage.setItem(SEEN_KEY, String(Date.now()));
    } catch (e) { /* storage unavailable: just check */ }
    fetch("/medals/pending", { headers: { Accept: "application/json" } })
      .then(function (r) { return r.ok ? r.json() : { medals: [] }; })
      .then(function (data) { showQueue((data.medals || []).slice()); })
      .catch(function () {});
  }

  // ---- dashboard: detail panel and tilt -------------------------------------------------

  function artOf(btn) {
    var mdl = btn.querySelector(".mdl");
    return mdl ? mdl.outerHTML : "";
  }

  function bindGrid() {
    var grid = document.querySelector(".mgrid");
    if (!grid) return;
    grid.addEventListener("click", function (e) {
      var btn = e.target.closest ? e.target.closest(".medal.earned[data-medal]") : null;
      if (!btn) return;
      ensureCss().then(function () {
        show({
          mode: "panel", ru: btn.dataset.ru, en: btn.dataset.en,
          story: btn.dataset.story, art: artOf(btn),
        });
      });
    });
    grid.addEventListener("pointermove", function (e) {
      if (reduced()) return;
      var btn = e.target.closest ? e.target.closest(".medal.earned") : null;
      if (!btn) return;
      var tilt = btn.querySelector(".tilt");
      var r = btn.getBoundingClientRect();
      var px = (e.clientX - r.left) / r.width - 0.5;
      var py = (e.clientY - r.top) / r.height - 0.5;
      var cl = function (v) { return Math.max(-8, Math.min(8, v)); };
      tilt.classList.add("moving");
      tilt.style.transform = "perspective(520px) rotateX(" + cl(-py * 16).toFixed(2) + "deg) rotateY(" + cl(px * 16).toFixed(2) + "deg)";
    });
    grid.addEventListener("pointerout", function (e) {
      var btn = e.target.closest ? e.target.closest(".medal.earned") : null;
      if (!btn || (e.relatedTarget && btn.contains(e.relatedTarget))) return;
      var tilt = btn.querySelector(".tilt");
      tilt.classList.remove("moving");
      tilt.style.transform = "";
    });
  }

  function init() {
    bindGrid();
    checkPending();
  }

  window.RuMedals = { show: show };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
