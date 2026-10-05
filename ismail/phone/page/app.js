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
  audio.play().then(() => { retry = 0; }).catch((e) => { if (want) setTimeout(() => want && connect(), backoff()); });
}
function backoff() { retry = Math.min(retry + 1, 6); return 1000 * 2 ** (retry - 1); }
function setPlaying(on) {
  want = on;
  if (on) connect(); else { audio.pause(); audio.removeAttribute('src'); audio.load(); sid = null; }
  $('play').innerHTML = on ? '&#10073;&#10073; Pause' : '&#9654; Listen';
  if ('mediaSession' in navigator) navigator.mediaSession.playbackState = on ? 'playing' : 'paused';
}
$('play').onclick = () => setPlaying(!want);
$('golive').onclick = () => { if (!want) return setPlaying(true); connect(0); toast('back to live'); };
$('back').onclick = () => { want = true; connect(30); send('/api/tap', { what: 'rewind' }, true); toast('30 s back'); };
['error', 'ended'].forEach((ev) => audio.addEventListener(ev, () => { if (want) setTimeout(() => want && connect(), backoff()); }));
audio.addEventListener('timeupdate', () => { if (audio.currentTime > lastT + 0.2) { lastT = audio.currentTime; lastAdvance = Date.now(); } });
setInterval(() => {                     // a stream that stops moving reconnects (wifi dropped, server restarted)
  if (want && !clip.el && Date.now() - lastAdvance > 12000) { lastAdvance = Date.now(); $('livetext').textContent = 'reconnecting'; connect(); }
}, 3000);
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
  h('play', () => setPlaying(true));
  h('pause', () => setPlaying(false));
  h('nexttrack', () => tap('change'));
  h('previoustrack', () => tap('love'));
  h('seekbackward', () => $('back').onclick());
}

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
const SAID = { love: '♥ love', change: 'change it up', energy_up: 'more energy', energy_down: 'calmer', louder: 'louder',
  quieter: 'quieter', pause: 'pause the set', resume: 'resume the set', start_set: 'start a set' };
async function tap(what, extra) {
  buzz([40]);
  const j = await send('/api/tap', Object.assign({ what }, extra || {}));
  if (j) toast((SAID[what] || extra && extra.mood || what) + (j.heard && j.heard.of ? ' · ' + j.heard.of : '') + ' · sent');
}
$('love').onclick = () => tap('love');
$('startset').onclick = () => tap('start_set');
$('change').onclick = () => tap('change');
document.querySelectorAll('[data-tap]').forEach((b) => { b.onclick = () => tap(b.dataset.tap); });
document.querySelectorAll('[data-mood]').forEach((b) => { b.onclick = () => tap('mood', { mood: b.dataset.mood }); });
$('quality').onclick = () => { kbps = kbps === 64 ? 128 : 64; store.set('kbps', kbps); $('quality').textContent = kbps + ' kbps'; if (want) connect(); };
$('buzzset').onclick = () => { buzzOn = !buzzOn; store.set('buzz', buzzOn); $('buzzset').textContent = buzzOn ? 'buzz on' : 'buzz off'; };
$('quality').textContent = kbps + ' kbps'; $('buzzset').textContent = buzzOn ? 'buzz on' : 'buzz off';

// ---- talk: hold to talk, or tap once to talk hands-free and tap again to send
const talk = { rec: null, stream: null, chunks: [], down: 0, toggle: false, t: null, sid: null };
async function micStart() {
  if (talk.rec) return;
  try {
    talk.stream = talk.stream || await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  } catch (e) { toast('the microphone is blocked: allow it for this page'); return; }
  const mime = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4'].find((m) => window.MediaRecorder && MediaRecorder.isTypeSupported(m)) || '';
  talk.chunks = []; talk.t = heardNow(); talk.sid = sid;
  talk.rec = new MediaRecorder(talk.stream, mime ? { mimeType: mime } : undefined);
  talk.rec.ondataavailable = (e) => { if (e.data.size) talk.chunks.push(e.data); };
  talk.rec.start(250);
  audio.volume = 0.25;
  $('talk').classList.add('on'); $('talk').textContent = 'Listening…'; buzz([30]);
}
function micStop(sendIt) {
  const r = talk.rec; if (!r) return;
  talk.rec = null; talk.toggle = false;
  $('talk').classList.remove('on'); $('talk').textContent = 'Hold to talk'; audio.volume = 1;
  $('talkhint').textContent = 'tap once to talk hands-free, tap again to send';
  r.onstop = () => {
    const blob = new Blob(talk.chunks, { type: r.mimeType || 'audio/webm' });
    if (sendIt && blob.size > 1500) upload(blob, talk.sid, talk.t);
    else if (sendIt) toast('too short: hold a little longer');
  };
  r.stop();
}
const pending = [];
async function upload(blob, s, t) {
  const u = `api/voice?sid=${encodeURIComponent(s || '')}&t=${t == null ? '' : t}`;
  try {
    const r = await fetch(u, { method: 'POST', headers: { 'Content-Type': blob.type }, body: blob });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error);
    addFeed({ me: true, id: j.id, text: 'voice note' + (j.heard && j.heard.of ? ' at ' + j.heard.of : '') + ': transcribing…' });
    toast('sent'); buzz([30, 60, 30]);
  } catch (e) {
    pending.push([blob, s, t]); toast('offline: the note waits and sends when you are back');
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
  if (held < 400) { talk.toggle = true; $('talkhint').textContent = 'talking hands-free: tap to send'; return; }
  if (!talk.toggle) micStop(true);
});
T.addEventListener('pointercancel', () => { if (!talk.toggle) micStop(false); });
T.addEventListener('contextmenu', (e) => e.preventDefault());

// ---- what the agents put here
const feedItems = [];
function addFeed(it) { feedItems.unshift(it); feedItems.splice(12); renderFeed(); }
function renderFeed() {
  const caps = (state.captions || []).slice().reverse().map((c) => ({ text: c.text, who: c.who, ts: c.ts }));
  const mine = feedItems.filter((x) => x.me);
  const all = mine.concat(caps).slice(0, 10);
  $('feed').innerHTML = all.length ? all.map((c) => c.me ? `<div><small>you:</small> ${esc(c.text)}</div>`
    : `<div>${esc(c.text)} <small>${esc(c.who || '')} ${esc((c.ts || '').slice(11, 16))}</small></div>`).join('') : '<div><small>nothing yet</small></div>';
}
const clip = { el: null, resume: false };
function stopClip() {
  if (clip.el) { clip.el.pause(); clip.el = null; document.querySelectorAll('.clip').forEach((c) => c.classList.remove('playing')); }
  if (clip.resume) { clip.resume = false; setPlaying(true); }
}
function playClip(url, box) {
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
  shown = p.id; buzz([80, 60, 80]);
  const box = $('panel');
  let h = `<h2>${esc(p.title)}</h2>` + (p.text ? `<p>${esc(p.text)}</p>` : '') + (p.image ? `<img src="${esc(p.image)}">` : '');
  if (p.kind === 'exam') {
    h += (p.clips || []).map((c, i) => `<div class="clip" data-i="${i}"><button class="playclip" data-url="${esc(c.url)}">&#9654; ${esc(c.label)}</button>`
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
}
function render() {
  const e = state.engine || {}, h = state.heard || {}, r = state.rec || {};
  $('top').classList.toggle('live', !!e.playing);
  let lt = e.playing ? 'LIVE' : 'no set playing';
  if (e.playing && h.of) lt += ' · ' + h.of;
  if (want && h.behind_s != null) lt += ' · ' + h.behind_s + ' s behind';
  if (!navigator.onLine) lt = 'offline';
  $('livetext').textContent = lt;
  $('rec').className = 'chip' + (r.on ? ' rec' : '');
  $('rec').textContent = (r.on ? '● rec on' : 'rec off') + (r.why ? ': ' + r.why : '');
  $('now').textContent = e.now || (e.playing ? 'playing' : 'nothing playing right now');
  $('next').textContent = e.next ? 'next: ' + e.next : '';
  $('pinned').hidden = !state.pinned; if (state.pinned) $('pinned').textContent = state.pinned.text;
  const caps = state.captions || [], lastc = caps[caps.length - 1];
  const fresh = lastc && (!state.pinned || lastc.text !== state.pinned.text);
  $('last').hidden = !fresh; if (fresh) $('last').innerHTML = esc(lastc.text) + ` <small>${esc(lastc.who || '')} ${esc((lastc.ts || '').slice(11, 16))}</small>`;
  $('startset').hidden = !!e.playing;
  document.querySelectorAll('[data-mood]').forEach((b) => b.classList.toggle('sel', b.dataset.mood === state.mood));
  $('agentbtns').innerHTML = (state.buttons || []).map((b) => `<button data-btn="${esc(b.id)}">${esc(b.label)}</button>`).join('');
  $('agentbtns').querySelectorAll('[data-btn]').forEach((b) => { b.onclick = () => tap('button:' + b.dataset.btn); });
  const ls = state.listening || [];
  $('listening').innerHTML = ls.length ? 'listening: ' + esc(ls.join(', ')) : '<span class="warn">no agent listening: your notes wait in the inbox</span>';
  (state.voice || []).forEach((v) => { const it = feedItems.find((x) => x.id === v.id); if (it && v.state.startsWith('waiting')) it.text = 'voice note: ' + v.state; });
  renderFeed(); renderPanel(); renderOffers(); mediaSession();
}
function onCmd(c) {
  if (c.type === 'caption') { toast(c.text); if (c.buzz) buzz([150, 80, 150]); }
  else if (c.type === 'buzz') buzz(c.pattern);
  else if (c.type === 'heard') { const it = feedItems.find((x) => x.id === c.ref); if (it) it.text = '“' + c.text + '”'; else addFeed({ me: true, id: c.ref, text: '“' + c.text + '”' }); }
  else if (c.type === 'offer' && c.offer && c.offer.auto && document.visibilityState === 'visible') {
    const a = document.createElement('a'); a.href = c.offer.url + '?dl=1'; a.download = c.offer.name; document.body.appendChild(a); a.click(); a.remove(); toast('downloading ' + c.offer.name);
  }
}
async function poll() {
  for (;;) {
    try {
      const t = heardNow();
      const r = await fetch(`api/state?since=${since}&wait=${first ? 0 : 20}&sid=${sid || ''}&t=${t == null ? '' : t}`, { cache: 'no-store' });
      const j = await r.json();
      state = j;
      if (!first) (j.cmds || []).forEach(onCmd);
      since = j.cmd; first = false;
      render();
    } catch (e) {
      $('livetext').textContent = navigator.onLine ? 'the server does not answer, retrying' : 'offline';
      await new Promise((ok) => setTimeout(ok, 4000));
    }
  }
}
$('sheet').addEventListener('click', (e) => { if (e.target.id === 'sheet') { $('sheet').classList.remove('show'); } });
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') { if (shown) $('sheet').classList.add('show'); } });
if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});
poll();
