"""A scene's world: the scene data the stage runtime must never hard-code (scenes/<name>/world.json).

    {
      "actors":   {"person_bartender": "bf_pete"},          who plays whom: person object -> actors/<name>.glb
      "facings":  {"person_bartender": [0, -1]},            which way a person faces (Blender x, y)
      "partners": {"person_couple_1_m": "person_couple_1_f"},  who faces whom (a couple)
      "floor":    0.09,                                     the floor people stand on (Blender z, metres)
      "keep_out": [[6.4, 19.6, 6.6, 14.4, -1, 3.05]],       boxes grown trees never draw inside (x0 x1 y0 y1 z0 z1)
      "spawn":    {"position": [x, y, z], "target": [x, y, z]},   where a first visit starts (optional)
      "credits":  ["SOURCES.md#lucy"],                      asset credits for what the scene shows
      "build":    {"script": "video/rooms/blue_front_block.py", "root": "../../../..", "env": {"VR_DETAIL": "1"}}
    }

`build.script` is relative to `build.root`, which is relative to the scene folder (default "../../../..": the song
folder, for scenes in <song>/video/vr/scenes/<name>); scene_export runs the script in Blender with VR_EXPORT set to
the scene folder.
scenes/stage.json may name the default scene: {"default": "bluefront"}.
"""
import json
from pathlib import Path

DEFAULTS = {'actors': {}, 'facings': {}, 'partners': {}, 'floor': 0.0, 'keep_out': [], 'spawn': None, 'credits': [],
            'build': None}


def world_path(scenes, name):
    return Path(scenes) / name / 'world.json'


def load_world(scenes, name):
    """The scene's world.json over the defaults; a missing file is an empty world (no actors, floor 0)."""
    w = json.loads(json.dumps(DEFAULTS))
    f = world_path(scenes, name)
    if f.is_file():
        try:
            got = json.loads(f.read_text(encoding='utf-8'))
        except ValueError as e:
            raise ValueError(f'{f}: not valid JSON ({e})')
        if not isinstance(got, dict):
            raise ValueError(f'{f}: world.json must be an object')
        w.update(got)
    return w


def check_world(w):
    """Problems in a world, as short lines (empty when it is fine)."""
    out = []
    for k in ('actors', 'facings', 'partners'):
        if not isinstance(w.get(k), dict):
            out.append(f'{k} must be an object')
    for p, v in (w.get('facings') or {}).items():
        if not (isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v)):
            out.append(f'facings.{p} must be [x, y]')
    for i, b in enumerate(w.get('keep_out') or []):
        if not (isinstance(b, list) and len(b) == 6 and b[0] < b[1] and b[2] < b[3] and b[4] < b[5]):
            out.append(f'keep_out[{i}] must be [x0, x1, y0, y1, z0, z1] with each min below its max')
    if not isinstance(w.get('floor'), (int, float)):
        out.append('floor must be a number')
    b = w.get('build')
    if b is not None and not (isinstance(b, dict) and isinstance(b.get('script'), str)):
        out.append('build must be {"script": "<path>", ...}')
    return out


def save_world(scenes, name, w):
    """Write world.json (the previous one kept in the scene's history/)."""
    probs = check_world({**DEFAULTS, **w})
    if probs:
        raise ValueError('world.json: ' + '; '.join(probs))
    f = world_path(scenes, name)
    if f.is_file():
        import time
        h = f.parent / 'history'
        h.mkdir(exist_ok=True)
        f.replace(h / time.strftime('world_%Y%m%d_%H%M%S.json'))
    f.write_text(json.dumps(w, indent=1), encoding='utf-8')
    return f


def default_scene(scenes):
    """scenes/stage.json "default", else the first scene (alphabetical), else ''."""
    scenes = Path(scenes)
    try:
        d = json.loads((scenes / 'stage.json').read_text(encoding='utf-8')).get('default')
        if d and (scenes / d / 'scene.glb').is_file():
            return d
    except (OSError, ValueError, AttributeError):
        pass
    names = sorted(p.name for p in scenes.iterdir() if (p / 'scene.glb').is_file()) if scenes.is_dir() else []
    return names[0] if names else ''


def build_of(scenes, name):
    """(script path, cwd, env) for scene_export, or None when the scene has no build."""
    w = load_world(scenes, name)
    b = w.get('build')
    if not b:
        return None
    root = (Path(scenes) / name / b.get('root', '../../../..')).resolve()
    script = (root / b['script']).resolve()
    return script, script.parent, {str(k): str(v) for k, v in (b.get('env') or {}).items()}
