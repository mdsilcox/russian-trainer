// Today: live Moscow clock and sky. Moscow is UTC+3 with no DST; the server
// renders the same initial state, this keeps it current.
(function () {
  var root = document.querySelector("[data-moscow-clock]");
  if (!root) return;
  var timeEl = root.querySelector("[data-clock-time]");
  var phaseEl = root.querySelector("[data-clock-phase]");
  var PHASES = ["dawn", "day", "dusk", "night"];
  var LABELS = { dawn: "рассве́т", day: "день", dusk: "зака́т", night: "ночь" };
  var fmt;
  try {
    fmt = new Intl.DateTimeFormat("ru-RU", { timeZone: "Europe/Moscow", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  } catch (e) { return; }

  function phase(h) {
    if (h >= 5 && h < 8) return "dawn";
    if (h >= 8 && h < 18) return "day";
    if (h >= 18 && h < 21) return "dusk";
    return "night";
  }
  function tick() {
    var parts = fmt.formatToParts(new Date()), h = 0, m = "00";
    parts.forEach(function (p) {
      if (p.type === "hour") h = parseInt(p.value, 10) % 24;
      if (p.type === "minute") m = p.value;
    });
    var text = String(h).padStart(2, "0") + ":" + m;
    if (timeEl.textContent !== text) timeEl.textContent = text;
    var ph = phase(h);
    if (!root.classList.contains("sky-" + ph)) {
      PHASES.forEach(function (p) { root.classList.remove("sky-" + p); });
      root.classList.add("sky-" + ph);
    }
    if (phaseEl) phaseEl.textContent = LABELS[ph];
  }
  tick();
  var delay = 60000 - (Date.now() % 60000) + 50;
  setTimeout(function () { tick(); setInterval(tick, 60000); }, delay);
})();
