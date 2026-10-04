// Music in the room: a song playing from a place in the scene (the stage, Lucy, a radio), positional, so it is louder
// as the user walks up to it. Claude starts and stops it (live command `music`); the user asked for it in the
// headset ("could we get some music in here?"). Only ever on a command: no sound without one.
import * as THREE from 'three';
import { listenerOf } from './stream.js';

export function initMusic(ed, live) {
  let listener = null, src = null, holder = null;
  function stop() {
    if (src) { try { src.stop(); } catch (_) { /* not started */ } src.disconnect(); }
    if (holder) holder.removeFromParent();
    src = holder = null;
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
    src.play();
    return { playing: c.url, at: it ? it.name : null, seconds: +buf.duration.toFixed(1) };
  }
  live.handlers.music = async (c) => (c.action === 'stop' ? (stop(), { stopped: true })
    : c.action === 'volume' && src ? (src.setVolume(c.volume), { volume: c.volume }) : play(c));
  return { play, stop };
}
