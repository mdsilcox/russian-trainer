// Keyboard shortcuts: any visible element with data-hotkey="<key>" is clicked
// when that key is pressed, unless you are typing in a field.
document.addEventListener("keydown", (event) => {
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  const target = event.target;
  if (target.closest("input, textarea, select, [contenteditable]")) return;

  const key = event.key === " " ? "Space" : event.key;
  const match = [...document.querySelectorAll(`[data-hotkey="${CSS.escape(key)}"]`)]
    .find((el) => el.offsetParent !== null && !el.disabled);
  if (match) {
    event.preventDefault();
    match.click();
  }
});

// Grouped main menu: click or tap a group to open it; Escape or a click outside closes it; one open at a time.
(function () {
  const groups = [...document.querySelectorAll("[data-nav-group]")];
  const close = (except) => groups.forEach((g) => {
    if (g === except) return;
    const b = g.querySelector("button"), m = g.querySelector(".nav-menu");
    b.setAttribute("aria-expanded", "false"); m.hidden = true;
  });
  groups.forEach((g) => {
    const b = g.querySelector("button"), m = g.querySelector(".nav-menu");
    b.addEventListener("click", () => {
      const open = b.getAttribute("aria-expanded") === "true";
      close(g);
      b.setAttribute("aria-expanded", String(!open)); m.hidden = open;
      if (!open) m.querySelector("a")?.focus({ preventScroll: true });
    });
  });
  document.addEventListener("click", (e) => { if (!e.target.closest("[data-nav-group]")) close(); });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    const open = groups.find((g) => g.querySelector("button").getAttribute("aria-expanded") === "true");
    if (open) { close(); open.querySelector("button").focus(); }
  });
})();
