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
})();
