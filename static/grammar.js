/* Grammar page enhancements: the living case table and the word-change morph.
   Both work without this script (server-rendered table and a plain list of forms). */
(function () {
  "use strict";

  function reduced() {
    try { return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches); }
    catch (e) { return false; }
  }

  /* ---------------- Living table ---------------- */
  function initLiving(root) {
    var brief = {};
    try { brief = JSON.parse(root.querySelector("[data-brief]").textContent); } catch (e) { return; }
    var rows = root.querySelectorAll("tbody tr[data-case]");
    var chipRow = root.querySelector("[data-chiprow]");
    var desc = root.querySelector("[data-desc]");
    var live = root.querySelector("[data-desc-live]");
    var controls = root.querySelectorAll("button[data-case]");
    var hover = null, pinned = null;

    chipRow.hidden = false;
    desc.classList.add("is-live");
    live.hidden = false;

    function paint() {
      var act = hover || pinned;
      if (act) root.setAttribute("data-active", act); else root.removeAttribute("data-active");
      rows.forEach(function (r) { r.classList.toggle("is-on", r.getAttribute("data-case") === act); });
      controls.forEach(function (b) {
        var c = b.getAttribute("data-case");
        b.classList.toggle("is-cur", c === act);
        b.setAttribute("aria-pressed", c === pinned ? "true" : "false");
      });
      live.textContent = "";
      var b = document.createElement("b");
      if (act) {
        b.textContent = act.charAt(0).toUpperCase() + act.slice(1) + " · " + brief[act].q;
        live.appendChild(b);
        live.appendChild(document.createTextNode(brief[act].use));
      } else {
        b.textContent = "Pick a case";
        live.appendChild(b);
        live.appendChild(document.createTextNode("Hover or focus a case name to light up its endings."));
      }
    }

    function caseOf(t) {
      var el = t.closest && t.closest("button[data-case]");
      return el && root.contains(el) ? el.getAttribute("data-case") : null;
    }
    root.addEventListener("mouseover", function (e) { var c = caseOf(e.target); if (c && hover !== c) { hover = c; paint(); } });
    root.addEventListener("mouseout", function (e) {
      if (caseOf(e.target) && !caseOf(e.relatedTarget || document.body)) { hover = null; paint(); }
    });
    root.addEventListener("focusin", function (e) { var c = caseOf(e.target); if (c) { hover = c; paint(); } });
    root.addEventListener("focusout", function (e) { if (caseOf(e.target)) { hover = null; paint(); } });
    root.addEventListener("click", function (e) {
      var c = caseOf(e.target);
      if (!c) return;
      pinned = pinned === c ? null : c;
      hover = null;
      paint();
    });
    paint();
  }

  /* ---------------- Word-change morph ---------------- */
  var W = 0.64;
  var SVG_MARK = '<svg viewBox="0 0 10 10" aria-hidden="true"><path d="M2 9 L8 1" stroke="#E2C46A" stroke-width="2.4" stroke-linecap="round" fill="none"/></svg>';
  var SVG_ARC = '<svg viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden="true"><path d="M0 40 Q50 -30 100 40" fill="none" stroke="#E2C46A" stroke-width="1.6" stroke-dasharray="3 4" vector-effect="non-scaling-stroke"/></svg>';

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function initMorph(root) {
    var SEQ;
    try { SEQ = JSON.parse(root.querySelector("[data-morph-data]").textContent); } catch (e) { return; }
    var host = root.querySelector("[data-morph-live]");
    root.classList.add("is-live");
    host.hidden = false;

    var seq = 0, step = 0, playing = false, timers = [], queue = [];

    /* build the static frame */
    var seqRow = el("div", "g-seqs");
    seqRow.setAttribute("role", "group");
    seqRow.setAttribute("aria-label", "Choose a sequence");
    var seqBtns = SEQ.map(function (q, i) {
      var b = el("button", "g-seqb");
      b.type = "button";
      b.appendChild(el("span", "sn", q.name));
      var p = el("span", "sp", q.path);
      p.lang = "ru";
      b.appendChild(p);
      b.addEventListener("click", function () { stopPlay(); seq = i; step = 0; draw(null, true); });
      seqRow.appendChild(b);
      return b;
    });

    var stage = el("div", "g-stage");
    var top = el("div", "g-stage-top");
    var stageLabel = el("span", "g-stage-label");
    var pills = el("div", "g-pills");
    top.appendChild(stageLabel);
    top.appendChild(pills);
    var scroll = el("div", "g-wdscroll");
    var box = el("div", "g-wdbox");
    var wd = el("div", "g-wd");
    wd.setAttribute("role", "img");
    var mk = el("span", "g-mk");
    mk.innerHTML = '<span class="g-mk-i">' + SVG_MARK + "</span>";
    var arc = document.createElement("span");
    arc.className = "g-arc";
    arc.innerHTML = SVG_ARC;
    arc = arc.firstChild;
    arc.setAttribute("class", "g-arc");
    var stemRow = el("span", "g-stemrow");
    var slot = el("span", "g-slot");
    var oldG = el("span", "g-eg lv");
    var newG = el("span", "g-eg");
    slot.appendChild(oldG);
    slot.appendChild(newG);
    [mk, arc, stemRow, slot].forEach(function (n) { wd.appendChild(n); });
    box.appendChild(wd);
    scroll.appendChild(box);
    var chg = el("div", "g-chg");
    var rule = el("p", "g-rule");
    rule.setAttribute("aria-live", "polite");
    var legend = el("div", "g-legend");
    legend.setAttribute("aria-hidden", "true");
    [["#F3E9D2", "stem (never moves)"], ["#E36B5F", "old ending"], ["#E2C46A", "new ending and stress"]].forEach(function (l) {
      var s = el("span");
      var i = el("i");
      i.style.background = l[0];
      s.appendChild(i);
      s.appendChild(document.createTextNode(l[1]));
      legend.appendChild(s);
    });
    var rl = el("div", "");
    rl.style.cssText = "height:1px;background:linear-gradient(90deg,rgba(201,162,39,0),#C9A227,rgba(201,162,39,0))";
    [top, scroll, rl, chg, rule, legend].forEach(function (n) { stage.appendChild(n); });

    var controls = el("div", "g-controls");
    var stepBtn = el("button", "g-btn primary");
    stepBtn.type = "button";
    var playBtn = el("button", "g-btn ghost");
    playBtn.type = "button";
    var note = el("span", "g-note-i");
    [stepBtn, playBtn, note].forEach(function (n) { controls.appendChild(n); });

    [seqRow, stage, controls].forEach(function (n) { host.appendChild(n); });

    /* helpers */
    function lettersFor(f, withGrow, hideHid) {
      stemRow.textContent = "";
      f.stem.split("").forEach(function (ch, i) {
        var s = el("span", "g-ltr" + (f.hid === i ? " hid" : "") + (withGrow && f.grow === i ? " grow" : ""), ch);
        stemRow.appendChild(s);
      });
    }
    function endLetters(group, f) {
      group.textContent = "";
      if (!f.end) { var z = el("span", "g-ltr zr", "∅"); group.appendChild(z); return; }
      f.end.split("").forEach(function (ch) { group.appendChild(el("span", "g-ltr", ch)); });
    }
    function pos(f) {
      var n = f.stem.length, x = 0;
      for (var i = 0; i < Math.min(f.st < 0 ? 0 : f.st, n); i++) x += (f.hid === i ? 0 : W);
      if (f.st > n) x += (f.st - n) * W;
      return x;
    }
    function endTxt(f) { return f.end ? "-" + f.end : "∅"; }

    function setMark(f, instant) {
      mk.classList.toggle("nomv", !!instant);
      if (f.st < 0) { mk.classList.add("off"); return; }
      mk.classList.remove("off");
      mk.style.left = pos(f).toFixed(3) + "em";
    }
    function clearTimers() { timers.forEach(clearTimeout); timers = []; }
    function later(fn, ms) { var t = setTimeout(fn, ms); timers.push(t); }

    /* static parts that depend on (seq, step) */
    function chrome() {
      var forms = SEQ[seq].forms, cur = forms[step];
      seqBtns.forEach(function (b, i) { b.setAttribute("aria-pressed", i === seq ? "true" : "false"); });
      stageLabel.textContent = cur.label;
      pills.textContent = "";
      forms.forEach(function (f, i) {
        var p = el("span", "g-pill" + (i === step ? " is-cur" : ""), f.text);
        p.lang = "ru";
        pills.appendChild(p);
      });
      var maxCells = 1;
      forms.forEach(function (f) { maxCells = Math.max(maxCells, f.stem.length + Math.max(1, f.end.length)); });
      box.style.width = (maxCells * W).toFixed(2) + "em";
      wd.setAttribute("aria-label", cur.text + " (" + cur.label + ")");
      wd.lang = "ru";

      var prev = step > 0 ? forms[step - 1] : null;
      chg.textContent = "";
      var a = el("span"), b1 = el("b", "", "ending");
      a.appendChild(b1);
      a.appendChild(document.createTextNode(" "));
      a.appendChild(el("span", "g-old", prev ? endTxt(prev) : "start"));
      a.appendChild(document.createTextNode(" → "));
      a.appendChild(el("span", "g-new", endTxt(cur)));
      var s = el("span"), b2 = el("b", "", "stress");
      s.appendChild(b2);
      s.appendChild(document.createTextNode(" "));
      s.appendChild(el("span", "g-old", prev ? prev.sn : "start"));
      s.appendChild(document.createTextNode(" → "));
      s.appendChild(el("span", "g-new", cur.sn));
      chg.appendChild(a);
      chg.appendChild(s);
      rule.textContent = cur.rule;
      var last = step >= forms.length - 1;
      stepBtn.textContent = last ? "Start over" : "Next: " + forms[step + 1].label;
      playBtn.textContent = playing ? "Stop" : "Play all";
      playBtn.setAttribute("aria-pressed", playing ? "true" : "false");
      note.textContent = reduced() ? "Reduce motion is on: forms swap instantly." : "Play all runs every sequence in turn.";
    }

    /* draw the current frame; if fromStep is given and motion allowed, animate from it */
    function draw(fromStep, instant) {
      clearTimers();
      var forms = SEQ[seq].forms, cur = forms[step];
      chrome();
      arc.setAttribute("class", "g-arc");
      oldG.className = "g-eg lv";
      newG.className = "g-eg";
      if (fromStep === null || fromStep === undefined || reduced()) {
        lettersFor(cur, false);
        oldG.textContent = "";
        endLetters(newG, cur);
        setMark(cur, true);
        mk.classList.remove("hop");
        return;
      }
      var prev = forms[fromStep];
      var a = pos(prev), b = pos(cur);
      var moved = prev.st >= 0 && cur.st >= 0 && Math.abs(a - b) > 0.001;
      /* phase 1: old ending sinks away */
      lettersFor(prev, false);
      endLetters(oldG, prev);
      oldG.className = "g-eg lv run";
      endLetters(newG, cur);
      newG.className = "g-eg wait";
      mk.classList.remove("hop");
      setMark(prev, true);
      later(function () {
        /* phase 2: new ending rises, letter grows, mark travels */
        lettersFor(cur, true);
        oldG.className = "g-eg lv gone";
        newG.className = "g-eg ent";
        void mk.offsetWidth;
        setMark(cur, prev.st < 0);
        if (moved) {
          mk.classList.add("hop");
          arc.style.left = (Math.min(a, b) + W / 2).toFixed(3) + "em";
          arc.style.width = Math.abs(b - a).toFixed(3) + "em";
          void arc.getBoundingClientRect();
          arc.setAttribute("class", "g-arc " + (b > a ? "onr" : "onl"));
        }
        later(function () { oldG.textContent = ""; mk.classList.remove("hop"); }, 1120);
      }, 380);
    }

    function stopPlay() {
      playing = false;
      queue = [];
      clearTimers();
      playBtn.textContent = "Play all";
      playBtn.setAttribute("aria-pressed", "false");
    }

    function runQueue() {
      var a = queue.shift();
      if (!a) { playing = false; chrome(); return; }
      seq = a.seq;
      var from = a.step - 1;
      step = a.step;
      if (a.step === 0) {
        draw(null, true);
        playing = true;
        later(runQueue, 1500);
      } else {
        var wasPlaying = playing;
        draw(from);
        playing = wasPlaying;
        chrome();
        later(runQueue, reduced() ? 1700 : 3100);
      }
    }

    stepBtn.addEventListener("click", function () {
      stopPlay();
      var n = SEQ[seq].forms.length;
      if (step >= n - 1) { step = 0; draw(null, true); }
      else { var f = step; step += 1; draw(f); }
    });
    playBtn.addEventListener("click", function () {
      if (playing) { stopPlay(); chrome(); return; }
      stopPlay();
      SEQ.forEach(function (q, si) { q.forms.forEach(function (f, k) { queue.push({ seq: si, step: k }); }); });
      playing = true;
      runQueue();
    });

    draw(null, true);
  }

  function boot() {
    document.querySelectorAll("[data-living]").forEach(initLiving);
    document.querySelectorAll("[data-morph]").forEach(initMorph);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
