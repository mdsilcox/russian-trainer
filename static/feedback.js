/* Self-correct-first feedback: try a fix before the correction is shown.
   Delegated on document, so it survives HTMX swapping the panel. */
(function () {
  if (window.__feedbackSelfCorrect) return;
  window.__feedbackSelfCorrect = true;

  var MAX_TRIES = 2;

  // Mirrors normalize_answer() in app/services/feedback.py
  function normalize(text) {
    text = (text || "").normalize("NFD").replace(/\u0301/g, "").normalize("NFC");
    text = text.toLowerCase().replace(/\u0451/g, "\u0435").replace(/\s+/g, " ").trim();
    return text.replace(/[\s.,!?;:\u2026\u00bb"')\]]+$/, "").trim();
  }
  window.normalizeAnswer = normalize;

  function say(panel, text) {
    var live = panel.querySelector("#fix-status");
    if (live) live.textContent = text;
  }

  function record(item, correct) {
    var id = item.dataset.mistake;
    if (!id) return;
    var body = new URLSearchParams({ correct: correct ? "true" : "false" });
    fetch("/workshop/mistakes/" + id + "/attempt", { method: "POST", body: body }).catch(function () {});
  }

  function reveal(panel, item, solved) {
    item.classList.add("resolved");
    item.classList.toggle("solved", !!solved);
    item.classList.toggle("gave-up", !solved);
    var tip = panel.querySelector('.tip[data-issue="' + item.dataset.issue + '"]');
    if (tip) tip.classList.add("revealed");
    var input = item.querySelector(".fix-input");
    if (input) input.disabled = true;
    checkAllDone(panel);
  }

  function checkAllDone(panel) {
    var open = panel.querySelectorAll(".issue-item:not(.resolved)");
    if (!open.length) panel.classList.remove("try-mode");
  }

  function check(panel, item) {
    var input = item.querySelector(".fix-input");
    var msg = item.querySelector(".fix-msg");
    if (!input || !input.value.trim()) { if (input) input.focus(); return; }
    var tries = (parseInt(item.dataset.tries || "0", 10)) + 1;
    item.dataset.tries = tries;
    if (normalize(input.value) === item.dataset.right) {
      record(item, true);
      msg.textContent = "";
      reveal(panel, item, true);
      say(panel, "Correct.");
    } else {
      record(item, false);
      if (tries >= MAX_TRIES) {
        msg.textContent = "";
        reveal(panel, item, false);
        say(panel, "Not quite. The answer is now shown.");
      } else {
        msg.textContent = "Not quite \u2014 try again. Hint: " + (item.dataset.category || "check the rule") + ".";
        input.select();
        say(panel, msg.textContent);
      }
    }
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("[data-act]");
    if (!btn) return;
    var panel = btn.closest(".feedback");
    if (!panel) return;
    var act = btn.dataset.act;
    if (act === "reveal-all") {
      panel.classList.remove("try-mode");
      panel.querySelectorAll(".issue-item:not(.resolved)").forEach(function (item) { reveal(panel, item, false); });
      panel.querySelectorAll(".tip").forEach(function (t) { t.classList.add("revealed"); });
      return;
    }
    var item = btn.closest(".issue-item");
    if (!item) return;
    if (act === "check") check(panel, item);
    if (act === "show") {
      if (!item.dataset.tries) record(item, false);
      reveal(panel, item, false);
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Enter" || !e.target.classList || !e.target.classList.contains("fix-input")) return;
    e.preventDefault();
    var item = e.target.closest(".issue-item");
    var panel = e.target.closest(".feedback");
    if (item && panel) check(panel, item);
  });
})();
