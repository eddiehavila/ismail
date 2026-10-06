// ismail phone page: listen with the screen off, talk back, tap feedback, answer what the agents put here.
'use strict';
const $ = (id) => document.getElementById(id);
const audio = $('audio');
const store = {
  get(k, d) { try { const v = localStorage.getItem('ismail.' + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem('ismail.' + k, JSON.stringify(v)); } catch (e) {} },
};
let kbps = store.get('kbps', 64), buzzOn = store.get('buzz', true);
let sid = null, want = false, lastT = 0, lastAdvance = Date.now(), retry = 0, state = {}, since = 0, first = true;
let outbox = store.get('outbox', []);

function toast(text) {
  const t = $('toast'); t.textContent = text; t.classList.add('show');
  clearTimeout(toast.h); toast.h = setTimeout(() => t.classList.remove('show'), 2600);
}
function buzz(p) { if (buzzOn && navigator.vibrate) navigator.vibrate(p || [120]); }
function heardNow() { return audio.src && !audio.paused ? audio.currentTime : null; }
function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }

// ---- the stream
function connect(back) {
  sid = Math.random().toString(36).slice(2, 10);
  audio.src = `stream.mp3?sid=${sid}&kbps=${kbps}&back=${back || 0}`;
  lastT = 0; lastAdvance = Date.now();
  audio.play().then(() => { retry = 0; }).catch((e) => {
    if (e && e.name === 'NotAllowedError') return asleep();        // the phone wants a tap first: say so, no retry loop
    if (want) setTimeout(() => want && connect(), backoff());
  });
}
// A page that reloads (the phone dropped it while locked, or it was reopened) forgets it was listening and the set
// goes quiet with nobody told (2026-10-06, a walk). It remembers, picks the stream back up when the phone allows, and
// otherwise asks for one tap.
function remember() { store.set('listening', want ? Date.now() : 0); }
function asleep() {
  ev('resume_asked');
  want = false; sid = null;
  $('play').textContent = 'Resume'; $('play').classList.remove('on');
  toast('the set is still playing: tap Resume to hear it'); buzz([80, 60, 80]);
}
function backoff() { retry = Math.min(retry + 1, 6); return 1000 * 2 ** (retry - 1); }
function setPlaying(on) {
  if (on !== want) ev(on ? 'listen' : 'stop');
  want = on;
  if (on) connect(); else { audio.pause(); audio.removeAttribute('src'); audio.load(); sid = null; }
  $('play').textContent = on ? 'Stop' : 'Listen'; $('play').classList.toggle('on', on);
  if ('mediaSession' in navigator) navigator.mediaSession.playbackState = on ? 'playing' : 'paused';
  remember();
}
$('play').onclick = () => { setPlaying(!want); if (want && keysOn) armMic(); };
$('golive').onclick = () => { if (!want) return setPlaying(true); connect(0); toast('back to live'); };
$('back').onclick = () => { want = true; connect(30); send('/api/tap', { what: 'rewind' }, true); toast('30 s back'); };
['error', 'ended'].forEach((ev) => audio.addEventListener(ev, () => { if (want) setTimeout(() => want && connect(), backoff()); }));
audio.addEventListener('timeupdate', () => { if (audio.currentTime > lastT + 0.2) { lastT = audio.currentTime; lastAdvance = Date.now(); } });
setInterval(() => {                     // a stream that stops moving reconnects (wifi dropped, server restarted)
  if (want && !clip.el && Date.now() - lastAdvance > 12000) { lastAdvance = Date.now(); $('livetext').textContent = 'reconnecting'; connect(); }
}, 3000);
setInterval(() => { if (want) remember(); }, 30000);
window.addEventListener('online', () => { if (want) connect(); flush(); });

// ---- lock screen and earbuds: next = change it up, previous = love this
function mediaSession() {
  if (!('mediaSession' in navigator)) return;
  const ms = navigator.mediaSession, e = state.engine || {};
  try {
    ms.metadata = new MediaMetadata({ title: e.now || 'ismail live', artist: (state.heard && state.heard.of) ? 'ismail live, ' + state.heard.of : 'ismail live',
      album: e.next ? 'next: ' + e.next : '', artwork: [{ src: 'icon.svg', sizes: '512x512', type: 'image/svg+xml' }] });
  } catch (err) {}
  if (mediaSession.done) return;
  mediaSession.done = true;
  const h = (a, f) => { try { ms.setActionHandler(a, f); } catch (err) {} };
  // earbuds: the Dime 3 sends only play/pause (double and triple presses change the volume in the bud), so while
  // the set plays a press is a voice note, and "stop listening" said in a note stops the stream
  h('play', () => { ev('earbud', { key: 'play' }); if (want && keysOn) return keyNote(); setPlaying(true); cue('start'); });
  h('pause', () => { ev('earbud', { key: 'pause' }); if (want && keysOn) return keyNote(); setPlaying(false); });
  h('nexttrack', () => { ev('earbud', { key: 'next' }); tap('change'); });
  h('previoustrack', () => tap('love'));
  h('seekbackward', () => $('back').onclick());
}

// ---- the phone's take: what happens on the page, timed, so an agent can lay it over the voice notes
// (Nate 10-06: "kind of like the same thing [as a VR take], but for the mobile interface")
const evq = [];
function ev(what, f) { evq.push(Object.assign({ what, at: Date.now(), t: heardNow() }, f || {})); if (evq.length > 40) flushEv(); }
function flushEv(beacon) {
  if (!evq.length) return;
  const events = evq.splice(0).map((e) => { const { at, ...rest } = e; return Object.assign(rest, { age_ms: Date.now() - at }); });
  const body = JSON.stringify({ sid, events });
  if (beacon && navigator.sendBeacon) { navigator.sendBeacon('api/events', new Blob([body], { type: 'application/json' })); return; }
  fetch('api/events', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body, keepalive: true })
    .catch(() => { evq.unshift(...events.map((e) => Object.assign(e, { at: Date.now() - e.age_ms }))); });
}
setInterval(() => flushEv(), 3000);
window.addEventListener('pagehide', () => { ev('close'); flushEv(true); });
document.addEventListener('visibilitychange', () => { ev(document.visibilityState === 'visible' ? 'visible' : 'hidden'); if (document.visibilityState !== 'visible') flushEv(true); });
window.addEventListener('offline', () => ev('offline'));
window.addEventListener('online', () => ev('online'));
(function opened() {
  const c = navigator.connection || {};
  const standaloneNow = matchMedia('(display-mode: standalone)').matches || navigator.standalone;
  ev('open', { mobile: /Mobi|Android/i.test(navigator.userAgent), app: !!standaloneNow, w: screen.width, h: screen.height,
    lang: navigator.language, net: c.effectiveType || '', platform: (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || '' });
})();
// where they are on the page: the section in view once scrolling settles (a timer, not scroll events: those come
// with drawn frames, and a backgrounded page draws none)
let secShown = null, lastY = -1, stillY = -1;
setInterval(() => {
  const y = Math.round(window.scrollY);
  if (y !== lastY) { lastY = y; return; }                 // still moving
  if (y === stillY) return;                               // settled where it was
  stillY = y;
  const mid = window.innerHeight * 0.4;
  const s = [...document.querySelectorAll('[data-sec]')].find((el) => { const r = el.getBoundingClientRect(); return r.top <= mid && r.bottom >= mid; });
  const name = s ? s.dataset.sec : null;
  if (name && name !== secShown) { if (secShown !== null) ev('scroll', { to: name, y }); secShown = name; }
}, 1500);

// ---- sending (queued while offline)
async function send(path, body, quiet) {
  body = Object.assign({ sid, t: heardNow() }, body);
  try {
    const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.status);
    return j;
  } catch (e) {
    if (!quiet) toast('offline: kept, sends when you are back');
    outbox.push([path, body]); store.set('outbox', outbox);
    return null;
  }
}
async function flush() {
  const todo = outbox; outbox = []; store.set('outbox', outbox);
  for (const [p, b] of todo) {
    try { const r = await fetch(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }); if (!r.ok && r.status >= 500) throw 0; }
    catch (e) { outbox.push([p, b]); }
  }
  store.set('outbox', outbox);
}
const SAID = { love: 'love this', change: 'change it up', energy_up: 'more energy', energy_down: 'calmer', louder: 'louder',
  quieter: 'quieter', pause: 'pause the set', resume: 'resume the set', start_set: 'start a set' };
async function tap(what, extra) {
  buzz([40]);
  const j = await send('/api/tap', Object.assign({ what }, extra || {}));
  if (j) toast((SAID[what] || extra && extra.mood || what) + (j.heard && j.heard.of ? ', at ' + j.heard.of : '') + ': sent');
}
function flash(el) {                        // momentary: the key lights, says SENT, and is a plain key again
  el.blur();                                // (nothing stays pressed: a second press sends again, never "un-presses")
  const l = el.querySelector('.lbl') || el;
  if (!el.dataset.lbl) el.dataset.lbl = l.textContent;
  el.classList.add('sent'); l.textContent = 'Sent';
  clearTimeout(el.flashT); el.flashT = setTimeout(() => { el.classList.remove('sent'); l.textContent = el.dataset.lbl; }, 800);
}
$('love').onclick = () => { flash($('love')); tap('love'); };
$('startset').onclick = () => tap('start_set');
$('change').onclick = () => { flash($('change')); tap('change'); };
document.querySelectorAll('[data-tap]').forEach((b) => { b.onclick = () => { flash(b); tap(b.dataset.tap); }; });
document.querySelectorAll('[data-mood]').forEach((b) => { b.onclick = () => { flash(b); tap('mood', { mood: b.dataset.mood }); }; });
$('quality').onclick = () => { kbps = kbps === 64 ? 128 : 64; store.set('kbps', kbps); $('quality').textContent = kbps + ' kbps'; if (want) connect(); };
$('buzzset').onclick = () => { buzzOn = !buzzOn; store.set('buzz', buzzOn); $('buzzset').textContent = buzzOn ? 'Buzz on' : 'Buzz off'; };
$('quality').textContent = kbps + ' kbps'; $('buzzset').textContent = buzzOn ? 'Buzz on' : 'Buzz off';

// ---- talk: hold to talk, or tap once to talk hands-free and tap again to send
const talk = { rec: null, stream: null, chunks: [], down: 0, toggle: false, t: null, sid: null };
// ---- earbud button and the tones you hear in your pocket
let keysOn = store.get('keys', true), noteTimer = 0;
function wav(parts) {                       // [[freq, ms], ...] -> a data: URI of a short 16-bit tone sequence
  const sr = 22050, n = parts.reduce((a, [, ms]) => a + Math.round(sr * ms / 1000), 0);
  const b = new DataView(new ArrayBuffer(44 + 2 * n)); let o = 44;
  const str = (i, t) => [...t].forEach((c, k) => b.setUint8(i + k, c.charCodeAt(0)));
  str(0, 'RIFF'); b.setUint32(4, 36 + 2 * n, true); str(8, 'WAVEfmt '); b.setUint32(16, 16, true); b.setUint16(20, 1, true);
  b.setUint16(22, 1, true); b.setUint32(24, sr, true); b.setUint32(28, sr * 2, true); b.setUint16(32, 2, true); b.setUint16(34, 16, true);
  str(36, 'data'); b.setUint32(40, 2 * n, true);
  for (const [f, ms] of parts) {
    const m = Math.round(sr * ms / 1000);
    for (let i = 0; i < m; i++) { const env = Math.min(1, i / 200, (m - i) / 400); b.setInt16(o, f ? Math.sin(2 * Math.PI * f * i / sr) * 9000 * env : 0, true); o += 2; }
  }
  let bin = ''; new Uint8Array(b.buffer).forEach((x) => { bin += String.fromCharCode(x); });
  return 'data:audio/wav;base64,' + btoa(bin);
}
const CUES = { start: wav([[660, 90], [0, 30], [990, 120]]), end: wav([[990, 90], [0, 30], [660, 120]]),
  sent: wav([[1320, 60], [0, 50], [1320, 60]]), error: wav([[220, 260]]) };
// the tones are made with ismail (its measured grand piano: songs/_phone_cues/make_cues.py); the synthesized ones
// above stand in until the files load, or if they cannot
const MADE = {};
['start', 'end', 'sent', 'error'].forEach((n) => { const a = new Audio('cues/' + n + '.mp3'); a.preload = 'auto';
  a.addEventListener('canplaythrough', () => { MADE[n] = a.src; }, { once: true }); });
function cue(name) { try { const a = new Audio(MADE[name] || CUES[name]); a.volume = 0.8; a.play().catch(() => {}); } catch (e) {} }
async function armMic() {
  if (talk.stream && talk.stream.active) return true;
  try {
    talk.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    $('talkhint').textContent = 'earbud ready: press to talk, press again to send';
    return true;
  } catch (e) { $('talkhint').textContent = 'the microphone is blocked: the earbud cannot take notes'; return false; }
}
async function keyNote() {
  if (audio.paused && want) audio.play().catch(() => {});
  if ('mediaSession' in navigator) navigator.mediaSession.playbackState = 'playing';
  if (talk.rec) { micStop(true); return; }
  if (!talk.stream || !talk.stream.active) { cue('error'); buzz([300]); toast('open the page once to let the earbud take notes'); return; }
  await micStart();
}
$('keysset').onclick = () => { keysOn = !keysOn; store.set('keys', keysOn); $('keysset').textContent = keysOn ? 'Earbud: talk' : 'Earbud: play'; if (keysOn && want) armMic(); };
$('keysset').textContent = keysOn ? 'Earbud: talk' : 'Earbud: play';
async function micStart() {
  if (talk.rec) return;
  try {
    talk.stream = talk.stream || await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  } catch (e) { toast('the microphone is blocked: allow it for this page'); return; }
  const mime = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4'].find((m) => window.MediaRecorder && MediaRecorder.isTypeSupported(m)) || '';
  talk.chunks = []; talk.t = heardNow(); talk.sid = sid; talk.started = Date.now(); talk.end = 'press';
  ev('note_start');
  talk.rec = new MediaRecorder(talk.stream, mime ? { mimeType: mime } : undefined);
  talk.rec.ondataavailable = (e) => { if (e.data.size) talk.chunks.push(e.data); };
  talk.rec.start(250);
  audio.volume = 0.25;
  $('talk').classList.add('on'); $('talk').firstChild.textContent = 'Talking'; buzz([30]);
  meterStart(talk.stream);
  cue('start');
  // Nate 10-06: "the voice recording should not cut me off" (it stopped at 60 s mid-sentence). A note now runs as long
  // as they talk: it ends on their press, after 30 s of quiet (a note left running in a pocket), or at 10 minutes
  // (a warning buzz 20 s before). The quiet check runs on a timer: animation frames stop with the screen off.
  clearTimeout(noteTimer); clearInterval(talk.quietT);
  talk.loudAt = Date.now(); const startedAt = Date.now(); let warned = false;
  talk.quietT = setInterval(() => {
    if (!talk.rec) return clearInterval(talk.quietT);
    if (meter.an) {
      const b = new Float32Array(meter.an.fftSize); meter.an.getFloatTimeDomainData(b);
      let p = 0; for (const v of b) p = Math.max(p, Math.abs(v));
      if (p > 0.02) talk.loudAt = Date.now();
    }
    const left = NOTE_MAX_MS - (Date.now() - startedAt);
    if (!warned && left < 20000) { warned = true; buzz([200, 100, 200]); cue('error'); toast('20 s left on this note'); }
    if (Date.now() - talk.loudAt > NOTE_QUIET_MS || left <= 0) { talk.end = left <= 0 ? 'max' : 'quiet'; micStop(true); }
  }, 500);
}
const NOTE_QUIET_MS = 30000, NOTE_MAX_MS = 10 * 60000;
function micStop(sendIt) {
  const r = talk.rec; if (!r) return;
  talk.rec = null; talk.toggle = false;
  $('talk').classList.remove('on'); $('talk').firstChild.textContent = 'Hold to talk'; audio.volume = 1;
  $('talkhint').textContent = 'tap once for hands-free, tap again to send';
  meterStop();
  clearTimeout(noteTimer); clearInterval(talk.quietT); cue('end');
  const dur = (Date.now() - (talk.started || Date.now())) / 1000, endBy = talk.end;
  ev('note_end', { dur: Math.round(dur * 10) / 10, by: endBy, sent: !!sendIt });
  r.onstop = () => {
    const blob = new Blob(talk.chunks, { type: r.mimeType || 'audio/webm' });
    if (sendIt && blob.size > 1500) upload(blob, talk.sid, talk.t, dur, endBy);
    else if (sendIt) toast('too short: hold a little longer');
  };
  r.stop();
}
const METER_N = 16;
$('meter').innerHTML = '<b></b>'.repeat(METER_N);
const meter = { ctx: null, an: null, src: null, raf: 0 };
function meterStart(stream) {
  try {
    meter.ctx = meter.ctx || new (window.AudioContext || window.webkitAudioContext)();
    meter.src = meter.ctx.createMediaStreamSource(stream);
    meter.an = meter.ctx.createAnalyser(); meter.an.fftSize = 1024;
    meter.src.connect(meter.an);
    const buf = new Float32Array(meter.an.fftSize), bars = $('meter').children;
    const tick = () => {
      meter.an.getFloatTimeDomainData(buf);
      let p = 0; for (const v of buf) p = Math.max(p, Math.abs(v));
      const lit = Math.round(Math.max(0, Math.min(1, (20 * Math.log10(p + 1e-6) + 50) / 50)) * METER_N);
      for (let i = 0; i < METER_N; i++) bars[i].classList.toggle('lit', i < lit);
      meter.raf = requestAnimationFrame(tick);
    };
    tick();
  } catch (e) {}
}
function meterStop() {
  cancelAnimationFrame(meter.raf);
  try { meter.src && meter.src.disconnect(); } catch (e) {}
  [...$('meter').children].forEach((b) => b.classList.remove('lit'));
}
const pending = [];
async function upload(blob, s, t, dur, endBy) {
  const u = `api/voice?sid=${encodeURIComponent(s || '')}&t=${t == null ? '' : t}` + (dur ? `&dur=${dur.toFixed(1)}&end=${endBy || 'press'}` : '');
  try {
    const r = await fetch(u, { method: 'POST', headers: { 'Content-Type': blob.type }, body: blob });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error);
    addFeed({ me: true, id: j.id, ts: new Date().toTimeString().slice(0, 5), text: 'voice note' + (j.heard && j.heard.of ? ' at ' + j.heard.of : '') + ', transcribing' });
    toast('sent'); buzz([30, 60, 30]); setTimeout(() => cue('sent'), 350);
  } catch (e) {
    pending.push([blob, s, t, dur, endBy]); toast('offline: the note waits and sends when you are back'); cue('error');
  }
}
setInterval(() => { if (navigator.onLine && pending.length) { const p = pending.splice(0); p.forEach((x) => upload(...x)); } if (outbox.length) flush(); }, 8000);
const T = $('talk');
T.addEventListener('pointerdown', (e) => {
  e.preventDefault();
  if (talk.toggle) { micStop(true); return; }
  talk.down = Date.now(); micStart();
});
T.addEventListener('pointerup', () => {
  if (!talk.rec && !talk.down) return;
  const held = Date.now() - talk.down; talk.down = 0;
  if (held < 400) { talk.toggle = true; $('talkhint').textContent = 'hands-free: tap to send'; return; }
  if (!talk.toggle) micStop(true);
});
T.addEventListener('pointercancel', () => { if (!talk.toggle) micStop(false); });
T.addEventListener('contextmenu', (e) => e.preventDefault());

// ---- what the agents put here
// what they loved and asked for: kept by the server (it survives a reload), newest first
const TAPWORD = { love: 'loved', change: 'change it up', energy_up: 'more energy', energy_down: 'calmer', louder: 'louder',
  quieter: 'quieter', pause: 'pause', resume: 'resume', start_set: 'start a set', rewind: '30 s back' };
const svg = (d) => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${d}"/></svg>`;
const MARK = { loved: svg('M12 20 4.6 12.6a4.4 4.4 0 0 1 7.4-5.1 4.4 4.4 0 0 1 7.4 5.1Z'),
  replay: svg('M4 12a8 8 0 0 1 14-5.3M20 12a8 8 0 0 1-14 5.3M18 3v4h-4M6 21v-4h4'), new: 'NEW' };
function renderTaps() {
  const ts = state.taps || [], tl = state.tally || {};
  $('mine').hidden = !ts.length;
  $('tally').textContent = Object.keys(tl).length ? 'today: ' + Object.entries(tl).map(([k, n]) => `${TAPWORD[k] || k} ${n}`).join(', ') : '';
  $('taps').innerHTML = ts.map((x) => `<div><time>${esc((x.ts || '').slice(11, 16))}</time><span>${x.what === 'mood' ? 'mood: ' + esc(x.mood) : esc(TAPWORD[x.what] || x.what)}`
    + `${x.now ? ' <span class="me">' + (clockMode && x.into_s != null ? mmss(x.into_s) + ' into ' : 'during ') + esc(x.now) + '</span>' : x.of ? ' <span class="me">at ' + esc(x.of) + '</span>' : ''}</span></div>`).join('');
}
let clockMode = store.get('clock', false), polledAt = Date.now();
const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
function showInto() {                      // how far into the piece they are hearing, ticking between polls
  const h = state.heard || {};
  if (state.into_s == null) { $('heardcap').textContent = 'Into the piece'; $('bar').innerHTML = '<span>-:--</span>'; return; }
  const s = Math.max(0, state.into_s + (Date.now() - polledAt) / 1000 - (want && h.behind_s ? h.behind_s : 0));
  $('heardcap').textContent = 'Into the piece, ' + (state.clock || '').slice(0, 5);
  $('bar').innerHTML = `${mmss(s)}<span> in</span>`;
}
setInterval(() => { if (clockMode) showInto(); }, 1000);
function clockLabel() { $('clockset').textContent = clockMode ? 'Time' : 'Bars'; }
clockLabel();
$('clockset').onclick = () => { clockMode = !clockMode; store.set('clock', clockMode); clockLabel(); ev('setting', { clock: clockMode ? 'time' : 'bars' }); render(); };

// ---- the vibe: an agent sets the page to fit the music (phone_vibe); the server checked it, the page applies it
let vibeKey = '';
const fontsLoaded = new Set();
function applyVibe(v) {
  if (!v || !v.css) return;
  const k = JSON.stringify(v); if (k === vibeKey) return; vibeKey = k;
  const root = document.documentElement.style;
  root.setProperty('--vt', (v.transition_ms || 0) + 'ms');
  Object.entries(v.css).forEach(([n, val]) => root.setProperty(n, val));
  if (v.font_css && !fontsLoaded.has(v.font_css)) {
    fontsLoaded.add(v.font_css); const l = document.createElement('link'); l.rel = 'stylesheet'; l.href = v.font_css; document.head.appendChild(l);
  }
  const meta = document.querySelector('meta[name=theme-color]'); if (meta) meta.content = v.css['--ground'];
  const bg = $('bg');
  if (v.image) { bg.style.backgroundImage = `url("${v.image}")`; bg.style.filter = `blur(${v.blur}px)`; bg.classList.add('on'); $('bgdim').style.opacity = v.dim; }
  else { bg.classList.remove('on'); $('bgdim').style.opacity = 0; }
  fx.set(v.effect, v.intensity, v.css['--accent'], v.css['--ink']);
}
// one ambient effect on a canvas behind the page; still while hidden, and for anyone who asked for less motion
const fx = (() => {
  const cv = $('fx'), cx = cv.getContext('2d');
  let kind = 'none', amt = 0.5, acc = '#ffffff', ink = '#ffffff', raf = 0, last = 0, parts = [], W = 0, H = 0, dpr = 1;
  const still = matchMedia('(prefers-reduced-motion: reduce)');
  function size() {
    dpr = Math.min(2, window.devicePixelRatio || 1); W = window.innerWidth; H = window.innerHeight;
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); cv.style.width = W + 'px'; cv.style.height = H + 'px';
  }
  function seed() {
    const n = Math.round((kind === 'rain' ? 140 : kind === 'particles' ? 70 : 3) * (0.3 + amt));
    parts = Array.from({ length: n }, () => ({ x: Math.random() * W, y: Math.random() * H, v: 0.4 + Math.random(), r: Math.random() }));
  }
  function frame(t) {
    raf = 0;
    if (document.visibilityState !== 'visible' || kind === 'none') return;
    raf = requestAnimationFrame(frame);
    if (t - last < 33) return;                                       // about 30 frames a second is plenty
    const dt = Math.min(0.1, (t - last) / 1000); last = t;
    cx.setTransform(dpr, 0, 0, dpr, 0, 0); cx.clearRect(0, 0, W, H);
    const a = 0.15 + amt * 0.5;
    if (kind === 'rain') {
      cx.strokeStyle = ink; cx.lineWidth = 1; cx.globalAlpha = a * 0.5; cx.beginPath();
      for (const p of parts) { p.y += (500 + p.v * 500) * dt; p.x += 60 * dt; if (p.y > H) { p.y = -20; p.x = Math.random() * W; } cx.moveTo(p.x, p.y); cx.lineTo(p.x - 3, p.y - 14 - p.v * 8); }
      cx.stroke();
    } else if (kind === 'particles') {
      cx.fillStyle = acc;
      for (const p of parts) { p.y -= p.v * 8 * dt; p.x += Math.sin(t / 3000 + p.r * 6) * 6 * dt; if (p.y < -4) { p.y = H + 4; p.x = Math.random() * W; }
        cx.globalAlpha = a * (0.4 + 0.6 * Math.abs(Math.sin(t / 900 + p.r * 9))); cx.beginPath(); cx.arc(p.x, p.y, 1 + p.r * 1.6, 0, 6.283); cx.fill(); }
    } else if (kind === 'pulse') {
      const bpm = (state.engine && state.engine.bpm) || 120, ph = ((t / 1000) * bpm / 60) % 1;
      const k = Math.exp(-ph * 5), g = cx.createRadialGradient(W / 2, H + 40, 10, W / 2, H + 40, H * (0.55 + 0.25 * k));
      g.addColorStop(0, acc); g.addColorStop(1, 'transparent'); cx.globalAlpha = a * (0.25 + 0.75 * k); cx.fillStyle = g; cx.fillRect(0, 0, W, H);
    } else if (kind === 'grain') {
      cx.fillStyle = ink; cx.globalAlpha = a * 0.35;
      for (let i = 0; i < 900 * (0.3 + amt); i++) cx.fillRect(Math.random() * W, Math.random() * H, 1, 1);
    } else if (kind === 'aurora') {
      parts.forEach((p, i) => {
        const x = W * (0.5 + 0.4 * Math.sin(t / (9000 + i * 2300) + p.r * 6)), y = H * (0.3 + 0.3 * Math.cos(t / (11000 + i * 1700) + p.r * 4));
        const g = cx.createRadialGradient(x, y, 0, x, y, Math.max(W, H) * 0.6); g.addColorStop(0, i === 1 ? ink : acc); g.addColorStop(1, 'transparent');
        cx.globalAlpha = a * (i === 1 ? 0.12 : 0.3); cx.fillStyle = g; cx.fillRect(0, 0, W, H);
      });
    }
    cx.globalAlpha = 1;
  }
  function go() { if (!raf && kind !== 'none' && !still.matches && document.visibilityState === 'visible') raf = requestAnimationFrame(frame); }
  window.addEventListener('resize', () => { size(); seed(); });
  document.addEventListener('visibilitychange', go);
  return {
    set(k, i, a, n) {
      kind = k || 'none'; amt = i == null ? 0.5 : i; acc = a || acc; ink = n || ink; size(); seed();
      if (kind === 'none' || still.matches) { if (raf) cancelAnimationFrame(raf); raf = 0; cx.clearRect(0, 0, cv.width, cv.height); return; }
      go();
    },
    get kind() { return kind; },
  };
})();

const feedItems = [];
function addFeed(it) { feedItems.unshift(it); feedItems.splice(12); renderFeed(); }
function renderFeed() {
  const caps = (state.captions || []).slice().reverse().map((c) => ({ text: c.text, who: c.who, ts: (c.ts || '').slice(11, 16) }));
  const mine = feedItems.filter((x) => x.me);
  const all = mine.concat(caps).slice(0, 10);
  $('feed').innerHTML = all.length ? all.map((c) => `<div><time>${esc(c.ts || '')}</time><span class="${c.me ? 'me' : ''}">${c.me ? 'you: ' : ''}${esc(c.text)}</span></div>`).join('')
    : '<div><time></time><span class="me">nothing yet</span></div>';
}
const clip = { el: null, resume: false };
function stopClip() {
  if (clip.el) { clip.el.pause(); clip.el = null; document.querySelectorAll('.clip').forEach((c) => c.classList.remove('playing')); }
  if (clip.resume) { clip.resume = false; setPlaying(true); }
}
function playClip(url, box) {
  ev('clip', { url: String(url).split('?')[0].slice(-60) });
  const again = clip.el && clip.el.dataset.url === url;
  if (clip.el) { clip.el.pause(); clip.el = null; document.querySelectorAll('.clip').forEach((c) => c.classList.remove('playing')); }
  if (again) return stopClip();
  if (want) { clip.resume = true; setPlaying(false); }
  const a = new Audio(url); a.dataset.url = url; clip.el = a; box.classList.add('playing');
  a.onended = () => { box.classList.remove('playing'); clip.el = null; };
  a.play().catch(() => toast('could not play that clip'));
}
let shown = null;
function renderPanel() {
  const ps = state.panels || [];
  const p = ps[ps.length - 1];
  if (!p) { if (shown) { $('sheet').classList.remove('show'); stopClip(); shown = null; } return; }
  if (shown === p.id) return;
  shown = p.id; buzz([80, 60, 80]); ev('panel_open', { id: p.id, title: p.title || '' });
  const box = $('panel');
  let h = `<h2>${esc(p.title)}</h2>` + (p.text ? `<p>${esc(p.text)}</p>` : '') + (p.image ? `<img src="${esc(p.image)}">` : '');
  if (p.kind === 'exam') {
    h += (p.clips || []).map((c, i) => `<div class="clip" data-i="${i}"><button class="playclip" data-url="${esc(c.url)}">Play ${esc(c.label)}</button>`
      + (c.note ? `<div class="hint">${esc(c.note)}</div>` : '')
      + (p.chips && p.chips.length ? `<div class="chips">${p.chips.map((w) => `<button data-chip="${esc(w)}">${esc(w)}</button>`).join('')}</div>` : '') + '</div>').join('');
    if (p.choices && p.choices.length) h += `<div class="btns">${p.choices.map((c) => `<button class="choice" data-choice="${esc(c)}">${esc(c)}</button>`).join('')}</div>`;
    h += `<textarea id="examnote" placeholder="a note (optional)"></textarea><div class="btns"><button id="submit" style="font-weight:700">Submit</button></div>`;
  } else {
    h += `<div class="btns">${(p.buttons || ['OK']).map((b) => `<button data-answer="${esc(b)}">${esc(b)}</button>`).join('')}</div>`;
  }
  box.innerHTML = h;
  $('sheet').classList.add('show');
  box.querySelectorAll('[data-answer]').forEach((b) => { b.onclick = async () => {
    const j = await send('/api/answer', { id: p.id, answer: b.dataset.answer });
    if (j) { toast('sent: ' + b.dataset.answer); } } });
  box.querySelectorAll('.playclip').forEach((b) => { b.onclick = () => playClip(b.dataset.url, b.closest('.clip')); });
  box.querySelectorAll('[data-chip]').forEach((b) => { b.onclick = () => b.classList.toggle('sel'); });
  box.querySelectorAll('[data-choice]').forEach((b) => { b.onclick = () => { box.querySelectorAll('[data-choice]').forEach((x) => x.classList.remove('sel')); b.classList.add('sel'); }; });
  const sub = box.querySelector('#submit');
  if (sub) sub.onclick = async () => {
    const answers = { clips: {}, choice: (box.querySelector('.choice.sel') || {}).dataset ? (box.querySelector('.choice.sel') || { dataset: {} }).dataset.choice || null : null,
      note: (box.querySelector('#examnote') || {}).value || '' };
    box.querySelectorAll('.clip').forEach((c) => { const lab = p.clips[+c.dataset.i].label; answers.clips[lab] = [...c.querySelectorAll('[data-chip].sel')].map((x) => x.dataset.chip); });
    if (p.choices && p.choices.length && !answers.choice) { toast('pick one answer first'); return; }
    const j = await send('/api/answer', { id: p.id, answers });
    if (j) { toast('submitted, thank you'); stopClip(); }
  };
}
function renderOffers() {
  const os = state.offers || [];
  $('offerbox').hidden = !os.length;
  $('offers').innerHTML = os.slice().reverse().map((o) => `<div class="offer"><span>${esc(o.label)}</span><a href="${esc(o.url)}?dl=1" download="${esc(o.name)}">Download</a></div>`).join('');
  $('offers').querySelectorAll('a[download]').forEach((a) => { a.onclick = () => ev('download', { file: a.getAttribute('download') }); });
}
function render() {
  const e = state.engine || {}, h = state.heard || {}, r = state.rec || {};
  $('top').classList.toggle('live', !!e.playing);
  $('livetext').textContent = !navigator.onLine ? 'offline' : e.playing ? (want ? 'live' : 'live, not listening') : 'no set playing';
  $('rec').classList.toggle('on', !!r.on);
  $('rectext').innerHTML = (r.on ? 'ON AIR' : 'REC OFF') + (r.why ? ` <small>${esc(r.why)}</small>` : '');
  const m = /bar (\d+)(?: beat ([\d.]+))?/.exec(h.of || '');
  polledAt = Date.now();
  if (clockMode) showInto();
  else { $('heardcap').textContent = 'Heard'; $('bar').innerHTML = m ? `BAR ${m[1]}<span>.${esc(Math.floor(+(m[2] || 1)))}</span>` : 'BAR <span>---</span>'; }
  applyVibe(state.vibe);
  $('behind').textContent = want && h.behind_s != null ? '+' + h.behind_s.toFixed(1) + ' s' : '--';
  $('now').textContent = e.now || (e.playing ? 'playing' : 'nothing playing');
  $('next').textContent = e.next || '--';
  $('pinned').hidden = !state.pinned;
  if (state.pinned) $('pinned').innerHTML = `<span class="cap">Since you left</span>${esc(state.pinned.text)}`;
  const caps = state.captions || [], lastc = caps[caps.length - 1];
  const fresh = lastc && (!state.pinned || lastc.text !== state.pinned.text);
  $('last').hidden = !fresh;
  if (fresh) $('last').innerHTML = `<span class="cap">${esc(lastc.who || 'DJ')} ${esc((lastc.ts || '').slice(11, 16))}</span>${esc(lastc.text)}`;
  $('startset').hidden = !!e.playing;
  const am = state.asked_mood;
  $('askedmood').textContent = am ? `: you asked ${am.mood}, ${(am.ts || '').slice(11, 16)}` : '';
  $('nowmark').className = 'mark ' + (e.now_mark || ''); $('nowmark').innerHTML = MARK[e.now_mark] || '';
  $('nextmark').className = 'mark ' + (e.next_mark || ''); $('nextmark').innerHTML = MARK[e.next_mark] || '';
  renderTaps();
  $('agentbtns').innerHTML = (state.buttons || []).map((b) => `<button data-btn="${esc(b.id)}">${esc(b.label)}</button>`).join('');
  $('agentbtns').querySelectorAll('[data-btn]').forEach((b) => { b.onclick = () => tap('button:' + b.dataset.btn); });
  $('agentwrap').hidden = !(state.buttons || []).length;
  const ls = state.listening || [];
  $('listening').innerHTML = ls.length ? 'listening: ' + esc(ls.join(', ')) : '<span class="warn">nobody listening: notes wait in the inbox</span>';
  (state.voice || []).forEach((v) => { const it = feedItems.find((x) => x.id === v.id); if (it && v.state.startsWith('waiting')) it.text = 'voice note: ' + v.state; });
  renderFeed(); renderPanel(); renderOffers(); mediaSession();
}
function onCmd(c) {
  if (c.type === 'caption') { toast(c.text); if (c.buzz) buzz([150, 80, 150]); notifyBg(c.who || 'ismail live', c.text); }
  else if (c.type === 'buzz') buzz(c.pattern);
  else if (c.type === 'say_clip') {                // spoken to the page itself: nobody was on the stream
    const a = new Audio(c.url); a.play().catch(() => { toast((c.who || 'DJ') + ': ' + c.text); buzz([150, 80, 150]); });
  }
  else if (c.type === 'stop_listening') { if (want) { setPlaying(false); cue('end'); toast('stopped listening: press the earbud or Listen to start again'); } }
  else if (c.type === 'heard') { const it = feedItems.find((x) => x.id === c.ref); if (it) it.text = '“' + c.text + '”'; else addFeed({ me: true, id: c.ref, ts: new Date().toTimeString().slice(0, 5), text: '“' + c.text + '”' }); }
  else if (c.type === 'offer' && c.offer && c.offer.auto && document.visibilityState === 'visible') {
    const a = document.createElement('a'); a.href = c.offer.url + '?dl=1'; a.download = c.offer.name; document.body.appendChild(a); a.click(); a.remove(); toast('downloading ' + c.offer.name);
  }
}
async function poll() {
  const was = store.get('listening', 0);            // listening when the page went away: pick it back up
  if (was && Date.now() - was < 30 * 60000 && !want) setPlaying(true);
  for (;;) {
    try {
      const t = heardNow();
      const r = await fetch(`api/state?since=${since}&wait=${first ? 0 : 20}&sid=${sid || ''}&t=${t == null ? '' : t}`, { cache: 'no-store' });
      const j = await r.json();
      state = j;
      if (!first) (j.cmds || []).forEach(onCmd);
      since = j.cmd; first = false; poll.wait = 0;
      render();
    } catch (e) {
      $('livetext').textContent = navigator.onLine ? 'the server does not answer, retrying' : 'offline';
      poll.wait = Math.min(30000, (poll.wait || 2000) * 2);          // back off: a phone in a pocket keeps its battery
      await new Promise((ok) => setTimeout(ok, poll.wait));
      continue;
    }
  }
}
$('sheet').addEventListener('click', (e) => { if (e.target.id === 'sheet') { $('sheet').classList.remove('show'); ev('panel_close', { id: shown }); } });
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') { if (shown) $('sheet').classList.add('show'); } });
if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});
// Install: Chrome offers it once the page qualifies (PNG icons, a service worker); the button appears only then
let installEvt = null;
const standalone = () => matchMedia('(display-mode: standalone)').matches || navigator.standalone;
window.addEventListener('beforeinstallprompt', (e) => { e.preventDefault(); installEvt = e; $('install').hidden = standalone(); });
window.addEventListener('appinstalled', () => { $('install').hidden = true; installEvt = null; toast('installed: open ismail from your home screen'); });
$('install').onclick = async () => { if (!installEvt) return; installEvt.prompt(); await installEvt.userChoice.catch(() => {}); installEvt = null; $('install').hidden = true; };
// Notify: when the page is in the background, what the DJ says or asks also arrives as a phone notification
let notifyOn = store.get('notify', false) && 'Notification' in window && Notification.permission === 'granted';
function notifyLabel() { $('notify').textContent = notifyOn ? 'Notify on' : 'Notify off'; }
if ('Notification' in window && 'serviceWorker' in navigator) { $('notify').hidden = false; notifyLabel(); }
$('notify').onclick = async () => {
  if (!notifyOn && Notification.permission !== 'granted') {
    const p = await Notification.requestPermission().catch(() => 'denied');
    if (p !== 'granted') { toast('notifications are blocked for this page: allow them in Chrome site settings'); return; }
  }
  notifyOn = !notifyOn; store.set('notify', notifyOn); notifyLabel();
};
async function notifyBg(title, body) {
  if (!notifyOn || document.visibilityState === 'visible') return;
  try { const r = await navigator.serviceWorker.ready; r.showNotification(title, { body, tag: 'ismail', renotify: true, icon: 'icon-192.png', badge: 'icon-192.png' }); } catch (e) {}
}
poll();
