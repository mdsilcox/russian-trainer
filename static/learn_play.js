// Exercise player: focus after each swap, sentence-building tiles and matching pairs.
(function () {
  function stage() { return document.getElementById("lp"); }

  function focusStage() {
    var root = stage();
    if (!root) return;
    var target = root.querySelector("input[data-select]:not([disabled])") || root.querySelector("[autofocus]");
    if (!target) return;
    target.focus();
    if (target.select && target.value) target.select();
  }

  // ---- Sentence building: tap a tile to place it, tap it in the sentence to take it back ----
  function syncBuild(box) {
    var slot = box.querySelector("[data-slot]");
    var placed = Array.prototype.slice.call(slot.querySelectorAll(".lp-tile"));
    var empty = slot.querySelector(".lp-slot-empty");
    if (empty) empty.hidden = placed.length > 0;
    box.querySelector("[data-response]").value = placed.map(function (t) { return t.textContent; }).join(" ");
  }

  function moveTile(tile) {
    var box = tile.closest("[data-lp-build]");
    var slot = box.querySelector("[data-slot]");
    var bank = box.querySelector("[data-bank]");
    if (tile.parentNode === slot) {
      // back to the bank, in its original place among the tiles still there
      var index = Number(tile.dataset.i);
      var before = Array.prototype.find.call(bank.children, function (t) { return Number(t.dataset.i) > index; });
      bank.insertBefore(tile, before || null);
    } else {
      slot.appendChild(tile);
    }
    syncBuild(box);
    tile.focus();
  }

  // ---- Matching: pick one on the left, then its partner on the right ----
  function matchState(box) {
    return box._lp || (box._lp = { picked: null, done: [], misses: 0 });
  }

  function syncMatch(box) {
    var state = matchState(box);
    var total = Number(box.dataset.total);
    var pairs = state.done.map(function (k) {
      return [box.querySelector('[data-side="left"][data-k="' + k + '"]').textContent,
              box.querySelector('[data-side="right"][data-k="' + k + '"]').textContent];
    });
    var all = state.done.length === total;
    box.querySelector("[data-response]").value = all ? JSON.stringify(pairs) : "";
    box.querySelector("[data-misses]").value = state.misses;
    var form = box.closest("form");
    var submit = form && form.querySelector("[data-lp-submit]");
    if (submit) submit.disabled = !all;
    box.querySelector("[data-status]").textContent = all
      ? "All matched. Check your answer."
      : state.done.length + " of " + total + " matched.";
  }

  function pickMatch(button) {
    var box = button.closest("[data-lp-match]");
    var state = matchState(box);
    if (button.disabled || button.classList.contains("done")) return;
    if (button.dataset.side === "left") {
      Array.prototype.forEach.call(box.querySelectorAll('[data-side="left"]'), function (b) {
        b.classList.remove("picked");
        b.setAttribute("aria-pressed", "false");
      });
      state.picked = button.dataset.k;
      button.classList.add("picked");
      button.setAttribute("aria-pressed", "true");
      return;
    }
    if (state.picked === null) {
      box.querySelector("[data-status]").textContent = "Pick an item on the left first.";
      return;
    }
    var left = box.querySelector('[data-side="left"][data-k="' + state.picked + '"]');
    if (state.picked === button.dataset.k) {
      [left, button].forEach(function (b) {
        b.classList.remove("picked");
        b.classList.add("done");
        b.disabled = true;
        b.setAttribute("aria-pressed", "false");
      });
      state.done.push(state.picked);
      state.picked = null;
    } else {
      state.misses += 1;
      button.classList.add("nope");
      setTimeout(function () { button.classList.remove("nope"); }, 500);
      box.querySelector("[data-status]").textContent = "Not a pair. Try another.";
      box.querySelector("[data-misses]").value = state.misses;
      return;
    }
    syncMatch(box);
  }

  function initMatch(root) {
    Array.prototype.forEach.call(root.querySelectorAll("[data-lp-match]"), syncMatch);
  }

  document.addEventListener("click", function (e) {
    var tile = e.target.closest && e.target.closest(".lp-tile");
    if (tile) { moveTile(tile); return; }
    var m = e.target.closest && e.target.closest(".lp-m");
    if (m) pickMatch(m);
  });

  document.addEventListener("htmx:afterSettle", function (e) {
    var root = stage();
    if (!root || !(e.target === root || root.contains(e.target))) return;
    initMatch(root);
    focusStage();
  });
  document.addEventListener("DOMContentLoaded", function () {
    var root = stage();
    if (root) initMatch(root);
    focusStage();
  });
})();
