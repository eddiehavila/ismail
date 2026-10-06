// Music in the room: a song playing from a place in the scene (the stage, Lucy, a radio), positional, so it is louder
// as the user walks up to it. Claude starts and stops it (live command `music`); the user asked for it in the
// headset ("could we get some music in here?"). Only ever on a command: no sound without one.
import * as THREE from 'three';
import { listenerOf } from './stream.js';

// The music clock: the song's own time as the person hears it (the audio context's sample clock, less the output
// latency), so takes can play on it (actors.js play(at_music)): the film's dancers were time-warped onto the beat, but
// a take started on a command lands 0.3 to 6 s late (load time), and a wall clock drifts from the audio
export function initMusic(ed, live) {
  let listener = null, src = null, holder = null, clock = null;   // clock: { url, ctx0, from, duration, loop }
  function stop() {
    if (src) { try { src.stop(); } catch (_) { /* not started */ } src.disconnect(); }
    if (holder) holder.removeFromParent();
    if (clock) live.emit('music_stop', { url: clock.url, at_s: now().t });
    src = holder = clock = null;
  }
  // { playing, url, t (song seconds now, as heard), duration, loop } or { playing: false }
  function now() {
    if (!clock || !src || !src.isPlaying) return { playing: false };
    const a = src.context, lat = a.outputLatency || a.baseLatency || 0;
    let t = clock.from + (a.currentTime - clock.ctx0) - lat;
    if (clock.loop && clock.duration > 0) t = ((t % clock.duration) + clock.duration) % clock.duration;
    else t = Math.min(Math.max(0, t), clock.duration);
    return { playing: true, url: clock.url, t: +t.toFixed(4), duration: +clock.duration.toFixed(3), loop: clock.loop };
  }
  async function play(c) {
    stop();
    if (!listener) listener = listenerOf(ed);
    if (listener.context.state !== 'running') await listener.context.resume().catch(() => {});
    const it = c.at ? ed.byName.get(c.at) : null;
    holder = new THREE.Object3D();
    if (it) { it.obj.updateMatrixWorld(true); holder.position.copy(it.obj.getWorldPosition(new THREE.Vector3())); holder.position.y += c.lift ?? 1.0; }
    ed.scene.add(holder);
    const buf = await new THREE.AudioLoader().loadAsync(c.url);
    src = new THREE.PositionalAudio(listener);
    src.setBuffer(buf);
    src.setRefDistance(c.ref ?? 3);
    src.setRolloffFactor(c.rolloff ?? 1);
    src.setLoop(c.loop !== false);
    src.setVolume(c.volume ?? 0.6);
    holder.add(src);
    const from = Math.max(0, Math.min(+(c.from || 0), buf.duration - 0.01));   // start this far into the song
    src.offset = from;
    src.play();
    clock = { url: c.url, ctx0: src.context.currentTime, from, duration: buf.duration, loop: c.loop !== false };
    live.emit('music_start', { url: c.url, from, seconds: +buf.duration.toFixed(3), at: it ? it.name : null });
    return { playing: c.url, at: it ? it.name : null, seconds: +buf.duration.toFixed(1), from };
  }
  live.handlers.music = async (c) => (c.action === 'stop' ? (stop(), { stopped: true })
    : c.action === 'volume' && src ? (src.setVolume(c.volume), { volume: c.volume }) : play(c));
  live.handlers.music_time = () => now();
  return { play, stop, now };
}
