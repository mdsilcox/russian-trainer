// Lessons: loading state for the word-list lookup, copy button, question box.
(function () {
  // Word list: one Claude call per word, so say how long it may take.
  document.addEventListener("submit", function (e) {
    var form = e.target.closest ? e.target.closest("[data-wait-form]") : null;
    if (!form) return;
    var area = form.querySelector("textarea");
    var lines = area ? area.value.split("\n").filter(function (l) { return l.trim(); }).length : 1;
    var wait = form.querySelector("[data-wait]");
    if (wait) {
      wait.hidden = false;
      var text = wait.querySelector("[data-wait-text]");
      if (text) text.textContent = "Looking up " + lines + (lines === 1 ? " word" : " words") + "… about " + Math.max(5, lines * 4) + " seconds";
    }
    var btn = form.querySelector("button[type=submit]");
    if (btn) setTimeout(function () { btn.disabled = true; }, 0);
  });

  // Copy the Russian summary.
  document.addEventListener("click", function (e) {
    var btn = e.target.closest ? e.target.closest("[data-copy-summary]") : null;
    if (!btn) return;
    var src = document.querySelector("[data-copy-source]");
    if (!src || !navigator.clipboard) return;
    navigator.clipboard.writeText(src.textContent.trim()).then(function () {
      var label = btn.textContent;
      btn.textContent = "Copied";
      setTimeout(function () { btn.textContent = label; }, 1500);
    });
  });

  // Question box: let a 400 (blank text) show its message, and clear the box after a save.
  document.addEventListener("htmx:beforeSwap", function (e) {
    var target = e.detail.target;
    if (target && target.classList && target.classList.contains("tq-status") && e.detail.xhr.status === 400) {
      e.detail.shouldSwap = true;
      e.detail.isError = false;
    }
  });
  document.addEventListener("htmx:afterRequest", function (e) {
    var form = e.target;
    if (form && form.closest && form.closest("[data-tutor-question]") && e.detail.successful) {
      var area = form.querySelector("textarea");
      if (area) area.value = "";
    }
  });
})();
