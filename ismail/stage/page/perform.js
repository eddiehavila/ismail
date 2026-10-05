// A Follow is a performance (the user, 2026-10-04: "performance mode is activated by a follow button, it's obvs
// deactivated by the same button"). While someone follows the user:
//   - no gesture acts (hands.performing): no travel, menus, phone, thumbs or grabs; a poke still presses a panel
//   - the mic records from the first moment, in clips on the Follow's clock (seconds since the Follow began). An agent
//     stops a clip to read it while the user goes on, starts the next, or turns the mic off ("as soon as you stop so
//     you can transcribe you can start another"); each clip is uploaded a second at a time as it records
//   - an agent drops markers at the moment (stage_perform), and its speech waits (it would be in the recording)
//     unless it is said aloud on purpose
// A played take whose meta names a performance plays its voice with it, on the take's own clock (update below).
// Events: perform_start, perform_clip_start, perform_clip_stop, perform_mark, perform_mic, perform_stop; the server
// adds perform_clip_in and perform_clip (the words, snapped onto the voice).

const MIME = () => ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg', 'audio/mp4'].find((m) => window.MediaRecorder && MediaRecorder.isTypeSupported(m)) || '';
const pad = (x) => String(x).padStart(2, '0');
const stamp = (d) => `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
const r2 = (x) => Math.round(x * 100) / 100;
// the level a recorded voice plays back at: RMS about -30 dBFS, a person talking a step or two away, under the agents'
// speech (the user, 2026-10-05: his voice came out of Sam "super loud", the raw mic level with its auto gain)
const VOICE_RMS = 0.03;
const levelOf = (buf) => {
  const d = buf.getChannelData(0);
  let s = 0, n = 0;
  for (let i = 0; i < d.length; i += 4) { s += d[i] * d[i]; n++; }
  const rms = Math.sqrt(s / Math.max(1, n));
  return rms > 1e-5 ? Math.min(1, VOICE_RMS / rms) : 1;
};

export function initPerform(ed, hands, voice, live, getActors) {
  let perf = null;            // { id, scene, person, t0, started, clips, cur, markers, mic, take, take_shift }
  const scn = () => ed.sceneName;
  const clock = () => (perf ? (performance.now() - perf.t0) / 1000 : 0);
  const url = (path, p, extra = '') => `${path}?scene=${encodeURIComponent(p.scene)}&perf=${encodeURIComponent(p.id)}${extra}`;
  const meta = (p, body) => fetch(url('perf/meta', p), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    .catch(() => {});

  function start(person) {
    if (perf) return perf;
    const d = new Date();
    perf = { id: stamp(d) + '_' + String(person).replace(/[^A-Za-z0-9_-]+/g, '_').slice(0, 40), scene: scn(), person,
      t0: performance.now(), started: d, clips: [], cur: null, markers: [], mic: true, take: null, take_shift: null, local: [] };
    hands.performing = true;
    meta(perf, { id: perf.id, person, scene: perf.scene, started: d.toISOString(), markers: [],
      clock: 'seconds since the Follow began (frames of a take kept from it: take time = Follow time - take_shift)' });
    live.emit('perform_start', { perf: perf.id, person });
    clipStart('follow start');
    return perf;
  }

  async function clipStart(by = 'agent') {
    if (!perf) throw new Error('no performance: nobody is following the user');
    if (perf.cur) return { clip: perf.cur.n, already: true };
    const p = perf;
    p.mic = true; p.starting = true;
    let stream;
    try {
      if (voice.micState.s !== 'on') throw new Error('not allowed');   // never prompt inside VR (the page's button allows it)
      stream = await voice.mic();
    } catch (e) {
      p.starting = false;
      live.emit('voice_error', { where: 'performance', error: 'mic ' + voice.micState.s + ': the performance has no voice' });
      return { error: 'mic ' + voice.micState.s };
    }
    p.starting = false;
    if (p !== perf || p.cur) return { error: 'the performance changed meanwhile' };
    const mime = MIME(), r = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    const c = { n: p.clips.length + 1, r, at: r2(clock()), t0: performance.now(), seq: 0, chain: Promise.resolve(), by, parts: [] };
    const type = (mime || 'audio/webm').split(';')[0];
    c.type = type;
    r.ondataavailable = (e) => {
      if (!e.data || !e.data.size) return;
      const k = c.seq++, blob = e.data;
      c.parts.push(blob);
      c.chain = c.chain.then(() => fetch(url('voice/perf', p, `&clip=${c.n}&seq=${k}`), { method: 'POST', headers: { 'Content-Type': type }, body: blob }))
        .catch((err) => live.emit('voice_error', { where: 'performance upload', error: String(err.message || err) }));
    };
    c.done = new Promise((res) => { r.onstop = res; });
    r.start(1000);
    p.cur = c;
    p.clips.push({ n: c.n, at: c.at, by });
    live.emit('perform_clip_start', { perf: p.id, clip: c.n, at: c.at, by });
    return { clip: c.n, at: c.at };
  }

  async function clipStop(by = 'agent') {
    if (!perf) throw new Error('no performance: nobody is following the user');
    const p = perf, c = p.cur;
    if (!c) return { recording: false };
    p.cur = null;
    c.r.stop();
    await c.done;
    const seconds = r2((performance.now() - c.t0) / 1000);
    Object.assign(p.clips.find((x) => x.n === c.n), { seconds });
    // kept here too: the playback right after the Follow has its voice before the server has it all
    p.local.push(new Blob(c.parts, { type: c.type }).arrayBuffer().then((ab) => voice.ctx().decodeAudioData(ab))
      .then((buf) => ({ n: c.n, start: c.at, buf, gain: levelOf(buf) })).catch(() => null));
    await c.chain;
    fetch(url('voice/perf', p, `&clip=${c.n}&end=1&at=${c.at}&seconds=${seconds}&by=${encodeURIComponent(by)}`), { method: 'POST' })
      .catch(() => {});
    live.emit('perform_clip_stop', { perf: p.id, clip: c.n, at: c.at, seconds, by });
    return { clip: c.n, at: c.at, seconds };
  }

  function mark(label, by = 'agent') {
    if (!perf) throw new Error('no performance: nobody is following the user');
    const m = { t: r2(clock()), label: String(label || 'mark').slice(0, 200), by };
    perf.markers.push(m);
    meta(perf, { markers: perf.markers });
    live.emit('perform_mark', { perf: perf.id, ...m });
    return m;
  }

  async function micOff(by = 'agent') {
    if (!perf) throw new Error('no performance: nobody is following the user');
    const r = await clipStop(by);
    perf.mic = false;
    live.emit('perform_mic', { perf: perf.id, on: false, by });
    return r;
  }

  async function stop() {
    if (!perf) return null;
    const p = perf;
    let fin;
    const finished = new Promise((res) => { fin = res; });
    perfs.set(p.scene + '/' + p.id, finished.then(() => Promise.all(p.local)).then((l) => l.filter(Boolean)));
    if (p.cur) await clipStop('follow end');
    perf = null;
    hands.performing = false;
    const seconds = r2((performance.now() - p.t0) / 1000);
    meta(p, { ended: new Date().toISOString(), seconds, take: p.take, take_shift: p.take_shift });
    live.emit('perform_stop', { perf: p.id, person: p.person, seconds, clips: p.clips.length });
    fin();
    return { perf: p.id, person: p.person, seconds, clips: p.clips };
  }

  // a take recording while the Follow performs: its frames start later than the Follow (take time = Follow time - shift)
  function attachTake(id, takeT0) {
    if (!perf) return null;
    perf.take = id; perf.take_shift = r2((takeT0 - perf.t0) / 1000);
    meta(perf, { take: id, take_shift: perf.take_shift });
    return { performance: perf.id, perf_shift: perf.take_shift, perf_scene: perf.scene };
  }

  function state() {
    if (!perf) return { performing: false };
    return { performing: true, perf: perf.id, person: perf.person, seconds: r2(clock()), mic: perf.mic && !!(perf.cur || perf.starting),
      clip: perf.cur ? { n: perf.cur.n, at: perf.cur.at, seconds: r2((performance.now() - perf.cur.t0) / 1000) }
        : perf.starting ? { n: perf.clips.length + 1, starting: true } : null,
      clips: perf.clips.length, markers: perf.markers.length, take: perf.take };
  }

  // the agent's hand on it (stage_perform): one action per command
  live.handlers.perform = async (c) => {
    const by = c.by || 'agent';
    switch (c.action || 'state') {
      case 'state': return state();
      case 'stop_clip': return { ...(await clipStop(by)), state: state() };
      case 'start_clip': { const r = await clipStart(by); if (r.error) throw new Error(r.error); return { ...r, state: state() }; }
      case 'next_clip': { const a = await clipStop(by), b = await clipStart(by); if (b.error) throw new Error(b.error); return { stopped: a, started: b }; }
      case 'mic_off': return { ...(await micOff(by)), state: state() };
      case 'mark': return mark(c.label, by);
      default: throw new Error("action is state, stop_clip, start_clip, next_clip, mic_off or mark");
    }
  };

  // what the user sees: one line over their view while they perform
  voice.perfHud = () => {
    if (!perf) return null;
    const t = clock(), mm = Math.floor(t / 60), ss = pad(Math.floor(t % 60));
    return perf.cur ? `● PERFORMING  ${mm}:${ss}  voice clip ${perf.cur.n}` : `PERFORMING  ${mm}:${ss}  mic off`;
  };

  // ---- the voice of a played take: clips of its performance, started where the take's clock reaches them
  const perfs = new Map();    // "scene/id" -> Promise<[{n, start (Follow clock), buf}]>
  function clipsOf(scene, id) {
    const key = scene + '/' + id;
    if (!perfs.has(key)) {
      const base = `scenes/${encodeURIComponent(scene)}/performances/${encodeURIComponent(id)}/`;
      const one = (c) => fetch(base + c.file).then((r) => r.arrayBuffer()).then((ab) => voice.ctx().decodeAudioData(ab))
        .then((buf) => ({ n: c.n, start: c.at, buf, gain: levelOf(buf) })).catch(() => null);
      perfs.set(key, fetch(base + 'perf.json', { cache: 'no-store' }).then((r) => r.json())
        .then((m) => Promise.all((m.clips || []).filter((c) => c.file).map(one)))
        .then((l) => l.filter(Boolean))
        .catch(() => { perfs.delete(key); return []; }));
    }
    return perfs.get(key);
  }
  const voices = new Map();   // person -> { key, clips, lastT, played: Set, src: Map }
  function hush(person) {
    const v = voices.get(person);
    if (v) for (const s of v.src.values()) try { s.stop(); } catch (_) { /* ended */ }
    voices.delete(person);
  }
  ed.preRender.push(function performVoice() {
    const actors = getActors();
    if (!actors) return;
    for (const person of [...voices.keys()]) if (!actors.playing.has(person)) hush(person);
    for (const [person, st] of actors.playing) {
      const m = st.meta;
      if (st.live || !m || !m.performance || !st.frames) continue;
      const key = (m.perf_scene || scn()) + '/' + m.performance + '/' + (st.take || '');
      let v = voices.get(person);
      if (!v || v.key !== key) {
        hush(person);
        v = { key, clips: null, lastT: -1, played: new Set(), src: new Map() };
        voices.set(person, v);
        clipsOf(m.perf_scene || scn(), m.performance).then((l) => { v.clips = l; });
      }
      if (!v.clips) continue;
      const t = st.frames[st.i].t, shift = m.perf_shift || 0;
      if (t < v.lastT - 0.2) { for (const s of v.src.values()) try { s.stop(); } catch (_) { /* ended */ } v.src.clear(); v.played.clear(); }   // looped
      v.lastT = t;
      for (const c of v.clips) {
        const s0 = c.start - shift;
        if (v.played.has(c.n) || t < s0 || t >= s0 + c.buf.duration - 0.05) continue;
        v.played.add(c.n);
        const a = voice.ctx(), src = a.createBufferSource();
        src.buffer = c.buf; src.playbackRate.value = st.rate || 1;
        const g = a.createGain();
        g.gain.value = c.gain || 1;
        src.connect(g).connect(a.destination);
        src.start(0, t - s0);
        src.onended = () => v.src.delete(c.n);
        v.src.set(c.n, src);
      }
    }
  });

  return { start, stop, clipStart, clipStop, micOff, mark, attachTake, state, get active() { return !!perf; }, hush };
}
