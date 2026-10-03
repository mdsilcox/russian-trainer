/* Speak: a reusable "read this Russian aloud" control. It uses natural cloud voices (Azure, through
 * the app's /tts route) when a key is configured, and the browser's Web Speech API otherwise.
 *
 * Include static/speak.css and this file (with `defer`) on any page.
 *
 * MARKUP (all declarative, picked up on load and for nodes added later)
 *   <button class="speak" data-speak="Где вокза́л?"></button>
 *       A speak button. The script adds the icon and aria-label if the button is empty.
 *       With an empty data-speak it reads the text of the previous element sibling.
 *   <p lang="ru" data-speak="привет">привет</p>   (or data-speak with no value: speaks its own text)
 *       Any other element: the script inserts a speak button right after it, in a
 *       <span class="speak-row">. Add data-speak-hotkey="s" to give that button a
 *       data-hotkey (see app.js). Use this form for chat messages.
 *   data-speak-speed
 *       Placeholder element that becomes a compact 0.6x to 1.2x speed picker.
 *   data-listen-first
 *       Element whose text stays blurred behind a "Reveal" button until it has been played
 *       (or Speak.reveal() is called). It only applies while listen-first mode is on.
 *       Put it on the text element itself, usually together with data-speak, so that playing
 *       the audio reveals the text. (The element is aria-hidden while concealed.)
 *   data-listen-first-toggle
 *       A checkbox (or any element, used as a toggle button) that turns the mode on or off.
 *       Toggling applies at once: on blurs every not-yet-revealed element, off shows them all.
 *       The mode is stored per device and mirrored as class "speak-lf" on <html>, so a
 *       tiny inline script can set it before first paint if you want no flash.
 *   data-speak-voice="ru-RU-DmitryNeural"
 *       On a data-speak element (or any ancestor): the cloud voice to use for it. Ignored by
 *       the browser provider. Without it the voice chosen in Settings is used.
 *   data-speak-note
 *       Optional container for the "no Russian voice" note; default is the top of <main>.
 *
 * JAVASCRIPT
 *   Speak.say(text, opts) -> Promise<boolean>  speak text (stress marks stripped, any current
 *                              speech stopped first). opts: { rate, voice, el }. `el` receives the
 *                              speak:start and speak:end events (bubbling CustomEvents with
 *                              detail { text, completed }) and gets the is-playing state.
 *                              Resolves true if it played to the end.
 *   Speak.stop()               stop speaking now
 *   Speak.provider()           "cloud" or "browser": which provider is active
 *   Speak.available()          false once we know there is no Russian voice (true while loading)
 *   Speak.rate                 current speed (getter); Speak.setRate(r) snaps to the nearest step
 *                              (0.6, 0.75, 0.9, 1, 1.2), saves it, and updates every speed picker
 *   Speak.onvoices(cb)         cb(available) now (if settled) and whenever it changes; returns
 *                              an unsubscribe function
 *   Speak.reveal(root)         reveal listen-first elements inside root (default: document)
 *   Speak.scan(root)           enhance markup inside root (automatic; only needed for odd cases)
 *   Speak.RATES                the speed steps
 *
 * PROVIDERS
 *   Speak.say() talks to one provider object: { available(), speak(text, {rate, voice}) -> Promise<bool>,
 *   stop(), onchange(cb) }. Two exist. The browser provider is the default. On load we ask
 *   GET /tts/status; when it says available, the cloud provider (an Audio element playing
 *   GET /tts?text=&voice=&rate=) takes over via Speak.useProvider. If a cloud request fails, that one
 *   utterance is spoken by the browser voice instead (logged once to the console). The "no Russian
 *   voice" note never shows while the cloud provider is active.
 */
(function () {
  "use strict";
  if (window.Speak) return;

  const RATES = [0.6, 0.75, 0.9, 1, 1.2];
  const KEY_RATE = "speak-rate", KEY_LF = "speak-listen-first", KEY_NOTE = "speak-note-dismissed";
  const LABEL = "Play Russian audio";
  const NO_VOICE = "No Russian voice found on this device";
  const ICON = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' +
    '<path d="M4 9.5v5h3.5L12 18.5v-13L7.5 9.5z" fill="currentColor" fill-opacity=".25"/>' +
    '<path d="M15.5 9a4 4 0 0 1 0 6"/><path d="M18 6.5a8 8 0 0 1 0 11"/></svg>';

  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode: ignore */ } },
  };

  // ---- Browser provider ------------------------------------------------------------------
  function browserProvider() {
    const synth = window.speechSynthesis;
    const supported = !!(synth && window.SpeechSynthesisUtterance);
    const listeners = [];
    let voice = null;
    let status = supported ? "pending" : "missing"; // pending | ready | missing
    let utterance = null; // keep a reference: some browsers drop it mid-speech otherwise

    // Natural / online voices sound far better than the old offline ones.
    function score(v) {
      let s = 0;
      if (/natural|online/i.test(v.name)) s += 4;
      if (/google/i.test(v.name)) s += 2;
      if (!v.localService) s += 1;
      if (/^ru[-_]RU$/i.test(v.lang)) s += 1;
      return s;
    }
    function notify() { listeners.forEach((cb) => cb(status !== "missing")); }
    function refresh() {
      const before = status;
      const ru = synth.getVoices().filter((v) => /^ru([-_]|$)/i.test(v.lang)).sort((a, b) => score(b) - score(a));
      voice = ru[0] || null;
      if (voice) status = "ready";
      else if (status === "ready") status = "missing";
      if (status !== before) notify();
    }

    if (supported) {
      refresh();
      if (status === "pending") {
        synth.addEventListener("voiceschanged", refresh);
        // voiceschanged can fire late or never: give up waiting after a few seconds.
        setTimeout(() => { if (status === "pending") { status = "missing"; notify(); } }, 3000);
      }
    }

    return {
      name: "browser",
      available: () => status !== "missing",
      settled: () => status !== "pending",
      onchange(cb) { listeners.push(cb); return () => { const i = listeners.indexOf(cb); if (i >= 0) listeners.splice(i, 1); }; },
      stop() { if (supported) synth.cancel(); },
      speak(text, o) {
        return new Promise((resolve) => {
          if (!supported) { resolve(false); return; }
          synth.cancel();
          const u = utterance = new SpeechSynthesisUtterance(text);
          u.lang = voice ? voice.lang : "ru-RU";
          if (voice) u.voice = voice;
          u.rate = o.rate;
          u.onend = () => resolve(true);
          u.onerror = () => resolve(false); // includes "canceled" when interrupted
          synth.speak(u);
        });
      },
    };
  }

  // ---- Cloud provider --------------------------------------------------------------------
  function cloudProvider(fallback, defaultVoice) {
    const audio = new Audio();
    let finish = null; // settles the utterance in progress
    let warned = false;

    function end(ok) { const f = finish; finish = null; if (f) f(ok); }
    return {
      name: "cloud",
      available: () => true,
      settled: () => true,
      onchange: () => () => {},
      stop() {
        audio.pause();
        end(false);
        fallback.stop();
      },
      speak(text, o) {
        this.stop();
        return new Promise((resolve) => {
          let done = false;
          let cancelled = false;
          const settle = (ok) => { if (!done) { done = true; resolve(ok); } };
          finish = (ok) => { cancelled = true; settle(ok); };
          const failed = () => {
            if (done || cancelled) return;
            if (!warned) { warned = true; console.warn("Natural voice unavailable, using the browser voice instead."); }
            finish = (ok) => { cancelled = true; settle(ok); };
            if (fallback.available()) fallback.speak(text, o).then(settle); else settle(false);
          };
          const q = new URLSearchParams({ text, voice: o.voice || defaultVoice || "", rate: String(o.rate) });
          audio.onended = () => { finish = null; settle(true); };
          audio.onerror = failed;
          audio.src = "/tts?" + q.toString();
          const p = audio.play();
          if (p && p.catch) p.catch(() => { if (!cancelled) failed(); });
        });
      },
    };
  }

  let provider = browserProvider();
  let unsubscribe = provider.onchange(onAvailability);

  // ---- Core API --------------------------------------------------------------------------
  let rate = nearestRate(parseFloat(store.get(KEY_RATE)));
  let active = null; // { el } of the speech in progress

  function nearestRate(r) {
    if (!isFinite(r)) return 1;
    return RATES.reduce((best, x) => (Math.abs(x - r) < Math.abs(best - r) ? x : best), RATES[0]);
  }
  /* Stress marks confuse some voices; ё carries no combining mark, so it is kept. */
  function clean(text) {
    return String(text || "").replace(/́/g, "").normalize("NFC").replace(/\s+/g, " ").trim();
  }
  function fire(el, type, detail) {
    if (el) el.dispatchEvent(new CustomEvent(type, { bubbles: true, detail }));
  }
  function setPlaying(el, on) {
    if (!el) return;
    el.classList.toggle("is-playing", on);
    if (el.matches("button")) el.setAttribute("aria-pressed", on ? "true" : "false");
  }

  function voiceFor(el) {
    const holder = el && (el._speakSource || el);
    const v = holder && holder.closest ? holder.closest("[data-speak-voice]") : null;
    return v ? v.getAttribute("data-speak-voice") : "";
  }

  function say(text, opts) {
    opts = opts || {};
    const t = clean(text);
    if (!t || !provider.available()) return Promise.resolve(false);
    stop();
    const el = opts.el || null;
    const mine = active = { el };
    setPlaying(el, true);
    fire(el, "speak:start", { text: t });
    const voice = opts.voice || voiceFor(el);
    return provider.speak(t, { rate: opts.rate || rate, voice }).then((ok) => {
      if (active === mine) {
        active = null;
        setPlaying(el, false);
        fire(el, "speak:end", { text: t, completed: ok });
      }
      return ok;
    });
  }
  function stop() {
    if (active) {
      const { el } = active;
      active = null;
      setPlaying(el, false);
      fire(el, "speak:end", { text: "", completed: false });
    }
    provider.stop();
  }
  function setRate(r) {
    rate = nearestRate(r);
    store.set(KEY_RATE, String(rate));
    renderSpeedPickers();
  }
  function onvoices(cb) {
    if (provider.settled && provider.settled()) cb(provider.available());
    return provider.onchange(cb);
  }
  function useProvider(p) {
    unsubscribe();
    stop();
    provider = p;
    unsubscribe = provider.onchange(onAvailability);
    onAvailability(provider.available());
  }

  // ---- Buttons ---------------------------------------------------------------------------
  function textFor(btn) {
    const src = btn._speakSource;
    if (src) return src.getAttribute("data-speak") || src.textContent;
    const own = btn.getAttribute("data-speak");
    if (own) return own;
    const prev = btn.previousElementSibling;
    return prev ? prev.textContent : "";
  }

  function enhanceButton(btn) {
    btn.classList.add("speak");
    if (!btn.hasChildNodes()) btn.innerHTML = ICON;
    if (!btn.hasAttribute("aria-label")) btn.setAttribute("aria-label", LABEL);
    btn.setAttribute("aria-pressed", "false");
    btn.type = "button";
    applyAvailability(btn);
  }
  function applyAvailability(btn) {
    const ok = provider.available();
    btn.disabled = !ok;
    btn.title = ok ? "" : NO_VOICE;
  }
  function onAvailability(ok) {
    document.querySelectorAll("button.speak").forEach(applyAvailability);
    if (!ok) showNote();
    else document.querySelector(".speak-note")?.remove();
  }

  document.addEventListener("click", (e) => {
    const btn = e.target.closest("button.speak");
    if (!btn || btn.disabled) return;
    if (btn.classList.contains("is-playing")) { stop(); return; }
    const holder = btn._speakSource || btn;
    const hidden = holder.closest("[data-listen-first]");
    if (hidden) revealEl(hidden);
    say(textFor(btn), { el: btn });
  });

  // ---- Listen first ----------------------------------------------------------------------
  const lfOn = () => document.documentElement.classList.contains("speak-lf");

  function revealEl(el) {
    el.classList.add("speak-revealed");
    el.removeAttribute("aria-hidden");
    if (el._speakRow) el._speakRow.querySelectorAll(".speak-reveal").forEach((b) => { b.hidden = true; });
  }
  function reveal(root) {
    (root || document).querySelectorAll("[data-listen-first]").forEach(revealEl);
  }
  function applyListenFirst() {
    const on = lfOn();
    document.querySelectorAll("[data-listen-first]").forEach((el) => {
      if (on && !el.classList.contains("speak-revealed")) el.setAttribute("aria-hidden", "true");
      else el.removeAttribute("aria-hidden");
    });
    document.querySelectorAll("[data-listen-first-toggle]").forEach((t) => {
      if (t.matches("input")) t.checked = on;
      else t.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }
  function setListenFirst(on) {
    document.documentElement.classList.toggle("speak-lf", on);
    store.set(KEY_LF, on ? "1" : "0");
    applyListenFirst();
  }
  document.addEventListener("change", (e) => {
    if (e.target.matches("input[data-listen-first-toggle]")) setListenFirst(e.target.checked);
  });
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-listen-first-toggle]");
    if (t && !t.matches("input")) setListenFirst(!lfOn());
  });

  // ---- Speed picker ----------------------------------------------------------------------
  function buildSpeedPicker(host) {
    host.classList.add("speak-speed");
    host.setAttribute("role", "group");
    host.setAttribute("aria-label", "Speech speed");
    host.innerHTML = "";
    RATES.forEach((r) => {
      const b = document.createElement("button");
      b.type = "button";
      b.dataset.rate = String(r);
      b.textContent = r + "×";
      b.addEventListener("click", () => setRate(r));
      host.appendChild(b);
    });
  }
  function renderSpeedPickers() {
    document.querySelectorAll("[data-speak-speed] button").forEach((b) => {
      b.setAttribute("aria-pressed", String(Number(b.dataset.rate) === rate));
    });
  }

  // ---- No-voice note ---------------------------------------------------------------------
  function showNote() {
    if (document.querySelector(".speak-note") || store.get(KEY_NOTE) === "1") return;
    if (!document.querySelector("button.speak")) return;
    const note = document.createElement("div");
    note.className = "speak-note";
    note.setAttribute("role", "note");
    note.innerHTML = "<p><b>No Russian voice found.</b> On Windows: Settings &gt; Time &amp; language &gt; Speech &gt; Add voices " +
      "(or Language &amp; region &gt; add Russian with speech), then restart the browser. " +
      "On macOS: System Settings &gt; Accessibility &gt; Spoken Content &gt; System voice &gt; Manage voices.</p>";
    const close = document.createElement("button");
    close.type = "button";
    close.className = "speak-note-close";
    close.setAttribute("aria-label", "Dismiss note");
    close.textContent = "×";
    close.addEventListener("click", () => { store.set(KEY_NOTE, "1"); note.remove(); });
    note.appendChild(close);
    const host = document.querySelector("[data-speak-note]") || document.querySelector("main") || document.body;
    host.insertBefore(note, host.firstChild);
  }

  // ---- Scanning --------------------------------------------------------------------------
  function rowFor(el) {
    if (!el._speakRow) {
      const row = document.createElement("span");
      row.className = "speak-row";
      el.insertAdjacentElement("afterend", row);
      el._speakRow = row;
    }
    return el._speakRow;
  }
  function scan(root) {
    root = root || document;
    const all = (sel) => {
      const list = [...root.querySelectorAll(sel)];
      if (root.matches && root.matches(sel)) list.unshift(root);
      return list.filter((n) => !n._speakReady);
    };

    all("[data-speak]").forEach((el) => {
      el._speakReady = true;
      if (el.matches("button")) { enhanceButton(el); return; }
      const btn = document.createElement("button");
      btn._speakSource = el;
      const hotkey = el.getAttribute("data-speak-hotkey");
      if (hotkey) btn.setAttribute("data-hotkey", hotkey);
      btn._speakReady = true;
      enhanceButton(btn);
      rowFor(el).appendChild(btn);
    });

    all("[data-listen-first]").forEach((el) => {
      el._speakReady = true;
      const reveal = document.createElement("button");
      reveal.type = "button";
      reveal.className = "speak-reveal";
      reveal.textContent = "Reveal";
      reveal.addEventListener("click", () => revealEl(el));
      rowFor(el).appendChild(reveal);
    });

    all("[data-speak-speed]").forEach((el) => { el._speakReady = true; buildSpeedPicker(el); });
    all("[data-listen-first-toggle]").forEach((el) => { el._speakReady = true; });

    renderSpeedPickers();
    applyListenFirst();
    if (!provider.available()) showNote();
  }

  // ---- Boot ------------------------------------------------------------------------------
  if (store.get(KEY_LF) === "1") document.documentElement.classList.add("speak-lf");

  /* Switch to the cloud voices when the server has an Azure key; otherwise stay on the browser's. */
  function detectCloud() {
    if (!window.fetch || !window.Audio) return;
    fetch("/tts/status").then((r) => (r.ok ? r.json() : null)).then((st) => {
      if (st && st.available) useProvider(cloudProvider(provider, st.default_voice));
    }).catch(() => { /* offline or old server: keep the browser voice */ });
  }

  function boot() {
    detectCloud();
    scan(document);
    new MutationObserver((records) => {
      records.forEach((r) => r.addedNodes.forEach((n) => { if (n.nodeType === 1) scan(n); }));
    }).observe(document.body, { childList: true, subtree: true });
    window.addEventListener("pagehide", () => provider.stop());
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();

  window.Speak = {
    RATES, say, stop, onvoices, reveal, scan, useProvider, setRate,
    provider: () => provider.name,
    available: () => provider.available(),
    get rate() { return rate; },
  };
})();
