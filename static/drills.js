// Drills: keep the cursor in the blank after each HTMX swap, and make Enter advance.
(function () {
  function focusStage() {
    var stage = document.getElementById("drill");
    if (!stage) return;
    var target = stage.querySelector("input[data-select]") || stage.querySelector("[autofocus]");
    if (!target) return;
    target.focus();
    if (target.select && target.value) target.select();
  }
  document.addEventListener("htmx:afterSettle", function (e) {
    if (e.target && (e.target.id === "drill" || e.target.closest("#drill"))) focusStage();
  });
  document.addEventListener("DOMContentLoaded", focusStage);
})();
