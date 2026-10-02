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
