// Count-up for big numbers: any element with data-count="N" counts from 0 to N
// when the page arrives (see the inline script in base.html), easing out over
// ~900ms. With Reduce motion, or on a reload of the same page, it just shows N.
(function () {
  const root = document.documentElement;
  if (!root.classList.contains("arrive")) return;

  const easeOut = (t) => 1 - Math.pow(1 - t, 3);
  const duration = 900;

  function countUp(el) {
    const target = Number(el.dataset.count);
    if (!Number.isFinite(target) || target <= 0) return;
    const decimals = (el.dataset.count.split(".")[1] || "").length;
    const start = performance.now() + Number(el.dataset.countDelay || 250);
    el.textContent = (0).toFixed(decimals);
    function frame(now) {
      const t = Math.min(1, Math.max(0, (now - start) / duration));
      el.textContent = (target * easeOut(t)).toFixed(decimals);
      if (t < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  document.querySelectorAll("[data-count]:not(input)").forEach(countUp);

  // The title sweep paints text through its background, which stops at the box edge;
  // display line-heights leave tails (y, р, у) and stress marks outside it. Grow the
  // box past the ink and take the space back from this title's own margins.
  document.querySelectorAll("main h1").forEach((h1) => {
    const cs = getComputedStyle(h1);
    const size = parseFloat(cs.fontSize);
    const extra = { top: 0.15 * size, bottom: 0.3 * size, side: 0.05 * size };
    h1.style.paddingTop = `${parseFloat(cs.paddingTop) + extra.top}px`;
    h1.style.paddingBottom = `${parseFloat(cs.paddingBottom) + extra.bottom}px`;
    h1.style.paddingLeft = `${parseFloat(cs.paddingLeft) + extra.side}px`;
    h1.style.paddingRight = `${parseFloat(cs.paddingRight) + extra.side}px`;
    h1.style.marginTop = `${parseFloat(cs.marginTop) - extra.top}px`;
    h1.style.marginBottom = `${parseFloat(cs.marginBottom) - extra.bottom}px`;
    h1.style.marginLeft = `${parseFloat(cs.marginLeft) - extra.side}px`;
    h1.style.marginRight = `${parseFloat(cs.marginRight) - extra.side}px`;
  });
})();

// A page restored from the back/forward cache shouldn't replay its arrival.
window.addEventListener("pageshow", (event) => {
  if (event.persisted) document.documentElement.classList.remove("arrive");
});
