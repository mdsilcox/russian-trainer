/* Role-play chat: send a line, stream the partner's reply, then review the line in the background.
   Flow per turn: POST /turn (save line) -> POST /reply (streamed text) -> POST /review/{id} (corrections).
   A failed reply can be retried; a failed review only leaves a small "Try again" button on that line. */
(function () {
  "use strict";
  const root = document.getElementById("chat");
  if (!root) return;
  const base = root.dataset.base;
  const log = document.getElementById("log");
  const errBox = document.getElementById("chat-error");
  const errText = errBox.querySelector("span");
  const retryBtn = document.getElementById("chat-retry");
  const MARK = "\x1e"; // the server ends a failed stream with this marker plus the message
  const composer = document.getElementById("composer");
  const input = document.getElementById("msg");
  const sendBtn = document.getElementById("send");
  const hintBtn = document.getElementById("hint-btn");
  const hintBox = document.getElementById("hint");
  const partnerName = root.querySelector(".sc-eyebrow").textContent.split(" · ")[0].trim();
  let busy = false;
  let retry = null;

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function post(path) { return fetch(base + path, { method: "POST", headers: { "Accept": "application/json" } }); }
  function scrollDown() { window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" }); }

  function showError(message, again) {
    errText.textContent = message;
    retry = again || null;
    retryBtn.hidden = !again;
    errBox.hidden = false;
  }
  function clearError() { errBox.hidden = true; retry = null; }
  retryBtn.addEventListener("click", () => { const r = retry; clearError(); if (r) r(); });

  function setBusy(on) {
    busy = on;
    if (!composer) return;
    input.readOnly = on;
    sendBtn.disabled = on;
    hintBtn.disabled = on;
    composer.classList.toggle("is-busy", on);
    if (!on) input.focus();
  }

  function learnerBubble(text) {
    const box = el("div", "ch-msg you");
    box.append(el("p", "ch-who", "You"));
    const p = el("p", "ch-text", text);
    p.lang = "ru";
    box.append(p);
    log.append(box);
    return box;
  }

  function typingBubble() {
    const box = el("div", "ch-msg partner ch-typing");
    box.setAttribute("aria-label", "The partner is typing");
    box.append(el("span", "ch-dot"), el("span", "ch-dot"), el("span", "ch-dot"));
    log.append(box);
    return box;
  }

  // --- the partner's streamed reply ---------------------------------------------------------
  async function streamReply() {
    const typing = typingBubble();
    scrollDown();
    let bubble = null, textEl = null, full = "";
    try {
      const res = await fetch(base + "/reply", { method: "POST" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || "The reply failed");
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let failed = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        let chunk = decoder.decode(value, { stream: true });
        const at = chunk.indexOf(MARK);
        if (at >= 0) { failed = chunk.slice(at + 1); chunk = chunk.slice(0, at); }
        if (chunk) {
          if (!bubble) {
            typing.remove();
            bubble = el("div", "ch-msg partner");
            bubble.append(el("p", "ch-who", partnerName));
            textEl = el("p", "ch-text");
            textEl.lang = "ru";
            textEl.setAttribute("data-speak", "");
            textEl.setAttribute("data-listen-first", ""); // blurred while "Listen first" is on
            bubble.append(textEl);
            log.append(bubble);
          }
          full += chunk;
          textEl.textContent = full;
          scrollDown();
        }
        if (failed) break;
      }
      if (failed) throw new Error(failed);
      if (!full.trim()) throw new Error("The partner said nothing. Try again.");
    } catch (e) {
      typing.remove();
      if (bubble) bubble.remove();
      throw e;
    }
    return { bubble, text: full };
  }

  // With "Listen first" on, speak the new reply and reveal its text once it has been played.
  function autoPlay(reply) {
    const S = window.Speak;
    if (!S || !document.documentElement.classList.contains("speak-lf")) return;
    const btn = reply.bubble.querySelector("button.speak");
    S.say(reply.text, { el: btn }).then(() => S.reveal(reply.bubble));
  }

  async function runReply(reviewId) {
    setBusy(true);
    let reply;
    try {
      reply = await streamReply();
    } catch (e) {
      showError(e.message || "The reply failed", () => runReply(reviewId));
      setBusy(false);
      return;
    }
    setBusy(false);
    autoPlay(reply);
    if (reviewId) review(reviewId);
  }

  // --- corrections, fetched after the reply so they never hold it up ------------------------
  function markGoals(done) {
    document.querySelectorAll("#goals li").forEach((li) => {
      const on = done.indexOf(Number(li.dataset.goal)) >= 0;
      li.classList.toggle("done", on);
      const sr = li.querySelector(".ch-sr");
      if (sr) sr.textContent = on ? " (done)" : " (not yet)";
    });
  }
  function bubbleFor(id) { return log.querySelector('.ch-msg.you[data-mid="' + id + '"]'); }

  async function review(id, button) {
    const box = bubbleFor(id);
    if (!box) return;
    box.querySelectorAll(".ch-review-fail").forEach((n) => n.remove());
    if (button) { button.disabled = true; button.textContent = "Checking..."; }
    try {
      const res = await post("/review/" + id);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not check this line");
      box.querySelectorAll(":scope > :not(.ch-who)").forEach((n) => n.remove());
      box.insertAdjacentHTML("beforeend", data.html);
      markGoals(data.goals_met);
    } catch (e) {
      if (button) button.remove();
      const fail = el("p", "ch-review-fail", "Corrections unavailable. ");
      const again = el("button", "ch-check", "Try again");
      again.type = "button";
      again.addEventListener("click", () => review(id, again));
      fail.append(again);
      box.append(fail);
    }
  }

  // --- sending ----------------------------------------------------------------------------------
  async function send() {
    const text = input.value.trim();
    if (busy || !text) return;
    hintBox.hidden = true;
    clearError();
    setBusy(true);
    input.value = "";
    const box = learnerBubble(text);
    scrollDown();
    let id;
    try {
      const res = await fetch(base + "/turn", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json" },
        body: new URLSearchParams({ text }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not send that");
      id = data.id;
    } catch (e) {
      box.remove();
      input.value = text;
      showError(e.message || "Could not send that");
      setBusy(false);
      return;
    }
    box.dataset.mid = id;
    runReply(id);
  }

  function lastLearnerId() {
    const all = log.querySelectorAll(".ch-msg.you[data-mid]");
    return all.length ? all[all.length - 1].dataset.mid : null;
  }

  if (composer) {
    composer.addEventListener("submit", (e) => { e.preventDefault(); send(); });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
    });
    document.getElementById("end-form").addEventListener("submit", (e) => {
      if (busy || !window.confirm("End this conversation?")) e.preventDefault();
    });

    // --- hint ---------------------------------------------------------------------------------
    hintBtn.addEventListener("click", async () => {
      if (busy) return;
      clearError();
      hintBtn.disabled = true;
      hintBtn.textContent = "Thinking...";
      try {
        const res = await post("/hint");
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "No hint right now");
        hintBox.querySelector(".ch-hint-ru").textContent = data.ru;
        hintBox.querySelector(".ch-hint-en").textContent = data.en;
        hintBox.querySelector(".ch-hint-tip").textContent = data.tip;
        hintBox.hidden = false;
      } catch (e) {
        showError(e.message || "No hint right now", () => hintBtn.click());
      }
      hintBtn.disabled = busy;
      hintBtn.textContent = "Hint";
    });
    document.getElementById("hint-use").addEventListener("click", () => {
      input.value = hintBox.querySelector(".ch-hint-ru").textContent;
      input.focus();
    });
    if (root.dataset.awaiting === "true") {
      showError("The partner has not replied yet.", () => runReply(lastLearnerId()));
    }
  }

  // --- corrections: tap an underlined span to show the rule; "Check this line" on old lines -----
  log.addEventListener("click", (e) => {
    const wrong = e.target.closest(".ch-wrong");
    if (wrong) {
      const note = document.getElementById(wrong.dataset.note);
      const open = wrong.getAttribute("aria-expanded") !== "true";
      wrong.setAttribute("aria-expanded", String(open));
      if (note) note.hidden = !open;
      return;
    }
    const check = e.target.closest(".ch-check[data-review]");
    if (check) review(check.closest(".ch-msg").dataset.mid, check);
  });
})();
