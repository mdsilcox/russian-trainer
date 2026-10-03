// Review page motion: card turn, rating feedback, progress collapse.
// (The card slide between cards is CSS view transitions; see review.css.)
(function () {
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const card = document.getElementById("review");
  const root = document.querySelector(".rv");
  const arrived = document.documentElement.classList.contains("arrive");

  // ---- Remaining count, remembered across the reload after each rating ----
  let prev = null;
  try { prev = sessionStorage.getItem("rv-remaining"); } catch (e) {}
  prev = prev === null ? null : Number(prev);
  if (root) {
    const left = Number(root.dataset.remaining);
    try { sessionStorage.setItem("rv-remaining", String(left)); } catch (e) {}
    if (!still && !arrived && prev !== null && prev > left) progressDrop(prev, left);
  }

  function progressDrop(prevLeft, left) {
    const bar = root.querySelector(".rv-bar");
    const num = root.querySelector(".rv-count-num");
    const gone = Math.min(prevLeft, 30) - Math.min(left, 30);
    if (bar) {
      for (let i = 0; i < gone; i++) {
        const seg = document.createElement("span");
        seg.className = "rv-gone";
        seg.style.animationDelay = (120 + i * 40) + "ms";
        bar.appendChild(seg);
      }
    }
    if (num) num.classList.add("is-tick");
  }

  vine();

  if (!card || still) return;

  // ---- Show answer: the card turns over ----
  const instantReveal = window.reveal;
  let turning = false;
  window.reveal = function () {
    const btn = card.querySelector(".rv-reveal");
    if (turning || !btn || btn.hidden) return;
    if (!card.animate) { instantReveal(); return; }
    turning = true;
    const persp = "perspective(1600px) ";
    const out = card.animate(
      [{ transform: persp + "rotateY(0deg)" }, { transform: persp + "rotateY(90deg)" }],
      { duration: 260, easing: "cubic-bezier(.5,0,.9,.6)", fill: "forwards" });
    const finish = () => {
      instantReveal(); // state is correct from here on, whatever the animation does
      const back = card.animate(
        [{ transform: persp + "rotateY(-90deg)" }, { transform: persp + "rotateY(0deg)" }],
        { duration: 290, easing: "cubic-bezier(.1,.6,.3,1)" });
      out.cancel();
      const done = () => { turning = false; };
      back.onfinish = done; back.oncancel = done;
    };
    out.onfinish = finish;
    out.oncancel = () => { if (turning) { turning = false; instantReveal(); } };
  };

  // ---- Rating: a flash of feedback (~140ms), then submit ----
  const form = document.getElementById("rate-form");
  if (form) {
    const fx = { 1: "fx-again", 2: "fx-hard", 3: "fx-good", 4: "fx-good" };
    let pending = false, go = false;
    form.addEventListener("submit", (e) => {
      if (go) return;
      e.preventDefault();
      if (pending) return;
      pending = true;
      const submitter = e.submitter;
      card.classList.add(fx[submitter && submitter.value] || "fx-good");
      setTimeout(() => {
        go = true;
        try { form.requestSubmit(submitter || undefined); } catch (err) { form.submit(); }
      }, 140);
    });
    window.addEventListener("pageshow", (e) => {
      if (e.persisted) { pending = go = false; card.classList.remove("fx-again", "fx-hard", "fx-good"); }
    });
  }

  // ---- Review vine -------------------------------------------------------
  // The page reloads after every rating, so this session's ratings live in sessionStorage
  // ("rv-vine": {d: day, r: [ratings], seen: how many nodes were already drawn}).
  function vine() {
    const KEY = "rv-vine", CAP = 24, NS = "http://www.w3.org/2000/svg";
    const today = new Date().toLocaleDateString("sv"); // YYYY-MM-DD, local
    const load = () => {
      try {
        const s = JSON.parse(sessionStorage.getItem(KEY) || "null");
        if (s && s.d === today && Array.isArray(s.r)) return { d: today, r: s.r.filter((v) => v >= 1 && v <= 4), seen: Number(s.seen) || 0 };
      } catch (e) {}
      return { d: today, r: [], seen: 0 };
    };
    const save = (s) => { try { sessionStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {} };
    const state = load();

    // Record the rating when the form is submitted (this listener runs before the feedback one).
    const rateForm = document.getElementById("rate-form");
    if (rateForm) {
      let recorded = false;
      rateForm.addEventListener("submit", (e) => {
        const v = e.submitter && Number(e.submitter.value);
        if (recorded || !(v >= 1 && v <= 4)) return;
        recorded = true;
        state.r.push(v);
        save(state);
      });
      window.addEventListener("pageshow", (e) => { if (e.persisted) recorded = false; });
    }

    const el = (name, attrs, parent) => {
      const n = document.createElementNS(NS, name);
      for (const k in attrs) n.setAttribute(k, attrs[k]);
      if (parent) parent.appendChild(n);
      return n;
    };
    const berriesIn = (list) => list.filter((v) => v >= 3).length;
    const plural = (n) => n + (n === 1 ? " berry" : " berries");

    // Draws the nodes of `list` into <g>; only the last one is animated when `animateLast`.
    function draw(g, list, animateLast) {
      const shown = list.slice(-CAP);
      const step = Math.min(140, 820 / Math.max(shown.length, 1));
      const f = Math.max(0.4, Math.min(1, step / 90));
      const by = 50 + 26 * Math.max(f, 0.7), br = 9 * Math.max(f, 0.6);
      shown.forEach((v, k) => {
        const x = 24 + (k + 1) * step, x0 = 24 + k * step;
        const fresh = animateLast && k === shown.length - 1;
        const grp = el("g", { class: "v-node" + (fresh ? " is-new" : "") }, g);
        const segD = "M" + x0 + " 50 Q" + (x0 + x) / 2 + " " + (k % 2 ? 38 : 62) + " " + x + " 50";
        el("path", { d: segD, stroke: "rgba(201,162,39,0.3)", "stroke-width": 1.5, "stroke-linecap": "round", fill: "none" }, grp);
        if (v >= 2) {
          el("path", { class: "v-seg", pathLength: 1, d: segD, stroke: "#C9A227", "stroke-width": 2.5, "stroke-linecap": "round", fill: "none" }, grp);
          const w = 38 * f, h = 24 * f;
          const leaf = (sgn, cls) => el("path", {
            class: "v-leaf " + cls,
            d: "M" + x + " 50 C" + (x + sgn * 5 * f) + " " + (50 - 12 * f) + " " + (x + sgn * w * 0.53) + " " + (50 - h) + " " + (x + sgn * w) + " " + (50 - h + 2) +
               " C" + (x + sgn * (w - 2)) + " " + (50 - 8 * f) + " " + (x + sgn * w * 0.53) + " 52 " + x + " 50Z",
            fill: "rgba(201,162,39,0.28)", stroke: "#E2C46A", "stroke-width": 1.5, "stroke-linejoin": "round",
          }, grp);
          leaf(-1, "v-leafL");
          if (v >= 3) leaf(1, "v-leafR");
        }
        if (v >= 3) {
          el("path", { class: "v-stem", pathLength: 1, d: "M" + x + " 50 C" + (x + 4) + " 56 " + (x + 4) + " " + (50 + (by - 50) * 0.6) + " " + x + " " + (by - br), stroke: "#C9A227", "stroke-width": 2, "stroke-linecap": "round", fill: "none" }, grp);
          const b = el("g", { class: "v-berry", "data-b": "" }, grp);
          el("circle", { class: "bf", cx: x, cy: by, r: br, fill: "#B3261E", stroke: "#C9A227", "stroke-width": 1.5 }, b);
          el("circle", { cx: x, cy: by, r: 2.2 * Math.max(f, 0.6), fill: "#E2C46A" }, b);
        }
        el("circle", { cx: x, cy: 50, r: 3.5, fill: "#0B0B0C", stroke: "#C9A227", "stroke-width": 1.5 }, grp);
      });
    }

    const wrap = document.querySelector("[data-rv-vine]");
    const branch = document.querySelector("[data-rv-branch]");

    if (wrap) {
      const g = wrap.querySelector(".rv-vine-nodes");
      const list = state.r;
      if (state.seen > list.length) state.seen = list.length;
      const added = list.length > state.seen;
      draw(g, list, added && !still);
      wrap.setAttribute("aria-label", "Review vine: " + plural(berriesIn(list)) + " so far");
      if (added && !still && list[list.length - 1] === 1) {
        wrap.classList.add("shiver");
      }
      state.seen = list.length;
      save(state);
    } else if (branch) {
      const list = state.r;
      if (list.length) {
        const n = berriesIn(list);
        draw(branch.querySelector(".rv-vine-nodes"), list, false);
        branch.querySelector("[data-rv-berries]").textContent = plural(n) + " from " + list.length + (list.length === 1 ? " card" : " cards");
        branch.setAttribute("aria-label", "Your branch today with " + plural(n));
        branch.hidden = false;
        const box = document.querySelector("[data-rv-done]");
        if (!still && box && box.classList.contains("is-bloom")) {
          branch.querySelectorAll("[data-b]").forEach((b, i) => { b.style.setProperty("--i", i); });
          branch.classList.add("is-shimmer");
        }
      }
      // The session is over: the next one starts a fresh branch.
      save({ d: today, r: [], seen: 0 });
    }
  }
})();
