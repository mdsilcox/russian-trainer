/* Cloze picker: clicking (or pressing Enter/Space on) a word in a sentence fills that sentence's word field. */
(function () {
  document.addEventListener("click", function (event) {
    const button = event.target.closest(".cz-word");
    if (!button) return;
    const form = button.closest("[data-cloze-form]");
    const field = form && form.querySelector('input[name="word"]');
    if (!field) return;
    field.value = button.dataset.word || "";
    form.querySelectorAll(".cz-word.is-picked").forEach(function (el) { el.classList.remove("is-picked"); });
    button.classList.add("is-picked");
    const meaning = form.querySelector('input[name="en"]');
    if (meaning) meaning.focus();
  });
})();
