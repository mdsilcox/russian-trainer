// Open and scroll to a month when its station (or a #month-N link) is used
(function () {
  function openMonth(hash, smooth) {
    var el = hash && /^#month-\d+$/.test(hash) ? document.querySelector(hash) : null;
    if (!el) return false;
    el.open = true;
    var calm = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollIntoView({ behavior: smooth && !calm ? "smooth" : "auto", block: "start" });
    return true;
  }
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest(".pl-track a");
    if (a && openMonth(a.getAttribute("href"), true)) {
      e.preventDefault();
      history.replaceState(null, "", a.getAttribute("href"));
    }
  });
  window.addEventListener("hashchange", function () { openMonth(location.hash, true); });
  if (location.hash) openMonth(location.hash, false);
})();
