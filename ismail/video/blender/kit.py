"""Shot kit (runs inside Blender 5.x). One shot = one script in <song>/video/shots/:

    import os, sys; sys.path.insert(0, os.environ['ISMAIL_VIDEO_KIT'])   # set by `python -m ismail.video`
    import kit
    S = kit.Shot('s04_foyer', 384, start_bar=9)            # frame 1 = song frame of bar 9 (S.events() use it)
    room = S.room('Foyer'); Z = S.floor(0, 50)             # models extracted by `ismail.video rip` into build/x
    L = S.character('hero', loc=(0, 34, Z), yaw=180)       # rigs/hero.json: bones, poses, eyes, mounts
    L.pose(L.poses['scared'], frame=1); L.eyes('wide', 1)
    S.flashlight(L); S.fog(...); S.light(...); S.camera(1, cam, target, lens=18)
    S.go()   # full render -> renders/shots/<name>_vN.mp4;  -- --still N [--pct P] -> build/look/<name>_NNNN.png
             # debug: --dbg nofog|lights, --top cx,cy,span,z (ortho plan with camera marker), --gain k

Units: ripped rooms are often ~20x metres; light energies are written as if metres and multiplied by Shot.gain (40).
"""
import json
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dae_import  # noqa: E402


def _video_dir():
    if os.environ.get('ISMAIL_VIDEO_DIR'):
        return os.environ['ISMAIL_VIDEO_DIR']
    script = next((a for i, a in enumerate(sys.argv) if i > 0 and sys.argv[i - 1] in ('-P', '--python')), None)
    return os.path.dirname(os.path.dirname(os.path.abspath(script))) if script else os.getcwd()


VD = _video_dir()
X = os.path.join(VD, 'build', 'x')
ASSETS = os.path.join(VD, 'assets')
CFG = json.load(open(os.path.join(VD, 'config.json'))) if os.path.exists(os.path.join(VD, 'config.json')) else {}


def args():
    a = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    out, i = {}, 0
    while i < len(a):
        if a[i].startswith('--'):
            has_val = i + 1 < len(a) and not a[i + 1].startswith('--')
            out[a[i][2:]] = a[i + 1] if has_val else True
            i += 2 if has_val else 1
        else:
            i += 1
    return out


def fcurves(id_block):
    """all fcurves of an ID (Blender 5 layered actions)."""
    ad = id_block.animation_data
    if not ad or not ad.action:
        return []
    act = ad.action
    if hasattr(act, 'fcurves') and len(getattr(act, 'fcurves', [])):
        return list(act.fcurves)
    out = []
    for layer in getattr(act, 'layers', []):
        for strip in layer.strips:
            for bag in strip.channelbags:
                out.extend(bag.fcurves)
    return out


def interp(id_block, mode):
    for fc in fcurves(id_block):
        for k in fc.keyframe_points:
            k.interpolation = mode


# ------------------------------------------------------------------ characters
class Character:
    """a rigged model driven by rigs/<name>.json:
    {"model": "Hero", "scale": 0.09,
     "bones": {"hips": "Bone1", "chest": "Bone13", "head": "Bone51", "r_up": "Bone16", "r_fore": "Bone17", "r_hand": "Bone18",
               "r_fing": "Bone19", "l_up": ..., "r_thigh": ..., "r_shin": ..., "r_foot": ..., "l_thigh": ..., ...},
     "eyes": {"base": "Texture10.png", "dir": "assets/hero", "states": {"default": "Texture10.png", "wide": "Texture19.png"}},
     "poses": {"stand": [["p", "r_up", "r_fore", [-0.3, -1, 0.05]], ["r", "head", "x", 8], ...]},
     "mounts": {"hand": ["r_hand", "r_fing"], "back": "chest"}}
    Armature space is the model's own (for GameCube rips: +Y up, +Z front, -X = the character's right).
    Pose ops: ["p", bone, child, dir] points bone->child along dir; ["r", bone, axis, deg] rotates about a world axis."""

    def __init__(self, shot, rig, loc=(0, 0, 0), yaw=0.0, name=None, scale=None):
        self.cfg = json.load(open(os.path.join(VD, 'rigs', rig + '.json')))
        name = name or rig
        self.bones = self.cfg.get('bones', {})
        self.poses = self.cfg.get('poses', {})
        self.scale = scale or self.cfg.get('scale', 1.0)
        self.ctl = bpy.data.objects.new(name + '_ctl', None)
        shot.coll.objects.link(self.ctl)
        self.root = dae_import.load(os.path.join(X, self.cfg['model']), name, shot.coll)
        self.root.parent = self.ctl
        self.root.scale = (self.scale,) * 3
        self.ctl.location = loc
        self.ctl.rotation_euler = (0, 0, math.radians(yaw))
        self.rig = next(o for o in self.root.children_recursive if o.type == 'ARMATURE')
        for pb in self.rig.pose.bones:
            pb.rotation_mode = 'QUATERNION'
        self.eye_values, self.eye_order = [], []
        if 'eyes' in self.cfg:
            self._eye_materials(self.cfg['eyes'])

    def b(self, n):
        return self.bones.get(n, n)

    # eyes: one image node per state, switched by a keyframed index (constant interpolation)
    def _eye_materials(self, ecfg):
        states = ecfg['states']
        self.eye_order = list(states)
        d = os.path.join(VD, ecfg.get('dir', ''))
        seen = set()
        for o in self.root.children_recursive:
            if o.type != 'MESH':
                continue
            for m in o.data.materials:
                if m in seen:
                    continue
                nt = m.node_tree
                src = next((n for n in nt.nodes if n.type == 'TEX_IMAGE' and n.image and n.image.filepath.endswith(ecfg['base'])), None)
                if src is None:
                    continue
                seen.add(m)
                orig_c = [l.to_socket for l in src.outputs['Color'].links]
                orig_a = [l.to_socket for l in src.outputs['Alpha'].links]
                idx = nt.nodes.new('ShaderNodeValue')
                col, alp = src.outputs['Color'], src.outputs['Alpha']
                for k, st in enumerate(self.eye_order[1:], 1):
                    t = nt.nodes.new('ShaderNodeTexImage')
                    t.image = bpy.data.images.load(os.path.join(d, states[st]), check_existing=True)
                    t.extension = src.extension
                    if src.inputs['Vector'].is_linked:
                        nt.links.new(src.inputs['Vector'].links[0].from_socket, t.inputs['Vector'])
                    cmp = nt.nodes.new('ShaderNodeMath'); cmp.operation = 'COMPARE'
                    cmp.inputs[1].default_value = k; cmp.inputs[2].default_value = 0.5
                    nt.links.new(idx.outputs[0], cmp.inputs[0])
                    mx = nt.nodes.new('ShaderNodeMix'); mx.data_type = 'RGBA'
                    nt.links.new(cmp.outputs[0], mx.inputs['Factor'])
                    nt.links.new(col, mx.inputs['A']); nt.links.new(t.outputs['Color'], mx.inputs['B'])
                    ma = nt.nodes.new('ShaderNodeMix'); ma.data_type = 'FLOAT'
                    nt.links.new(cmp.outputs[0], ma.inputs['Factor'])
                    nt.links.new(alp, ma.inputs['A']); nt.links.new(t.outputs['Alpha'], ma.inputs['B'])
                    col, alp = mx.outputs['Result'], ma.outputs['Result']
                for s in orig_c:        # captured BEFORE adding nodes: a vertex-colour multiply is also a Mix node
                    nt.links.new(col, s)
                for s in orig_a:
                    nt.links.new(alp, s)
                self.eye_values.append(idx)

    def eyes(self, state, frame=None):
        k = self.eye_order.index(state)
        for v in self.eye_values:
            v.outputs[0].default_value = k
            if frame is not None:
                v.outputs[0].keyframe_insert('default_value', frame=frame)
                interp(v.id_data, 'CONSTANT')

    # posing in armature space
    def rest(self):
        for pb in self.rig.pose.bones:
            pb.rotation_quaternion = (1, 0, 0, 0)
            pb.location = (0, 0, 0)
        bpy.context.view_layer.update()

    def rot(self, bone, axis, deg):
        pb = self.rig.pose.bones[self.b(bone)]
        M = pb.matrix.copy()
        h = M.translation.copy()
        ax = Vector({'x': (1, 0, 0), 'y': (0, 1, 0), 'z': (0, 0, 1)}[axis] if isinstance(axis, str) else axis)
        pb.matrix = Matrix.Translation(h) @ Matrix.Rotation(math.radians(deg), 4, ax) @ Matrix.Translation(-h) @ M
        bpy.context.view_layer.update()

    def point(self, bone, child, d):
        pb, c = self.rig.pose.bones[self.b(bone)], self.rig.pose.bones[self.b(child)]
        q = (c.head - pb.head).normalized().rotation_difference(Vector(d).normalized())
        h = pb.head.copy()
        pb.matrix = Matrix.Translation(h) @ q.to_matrix().to_4x4() @ Matrix.Translation(-h) @ pb.matrix.copy()
        bpy.context.view_layer.update()

    def pose(self, spec, frame=None, extra=()):
        """spec/extra: ops applied from rest, parents first. Keyframes every bone when frame is given."""
        self.rest()
        for op in list(spec) + list(extra):
            (self.point if op[0] == 'p' else self.rot)(*op[1:])
        if frame is not None:
            for pb in self.rig.pose.bones:
                pb.keyframe_insert('rotation_quaternion', frame=frame)
                pb.keyframe_insert('location', frame=frame)

    def walk(self, ph, stride=0.35, lift=0.35):
        """leg ops for a creeping walk at phase ph (0..1); add to a pose: C.pose(C.poses['stand'] + C.walk(ph))."""
        s, c, c2 = math.sin(ph * 2 * math.pi), max(0.0, math.cos(ph * 2 * math.pi)), max(0.0, -math.cos(ph * 2 * math.pi))
        return [['p', 'r_thigh', 'r_shin', (-0.05, -1, stride * s + 0.15)], ['p', 'r_shin', 'r_foot', (0, -1, -lift * c)],
                ['p', 'l_thigh', 'l_shin', (0.05, -1, -stride * s + 0.15)], ['p', 'l_shin', 'l_foot', (0, -1, -lift * c2)]]

    def bone_world(self, bone):
        return self.rig.matrix_world @ self.rig.pose.bones[self.b(bone)].matrix


# ------------------------------------------------------------------ the shot
class Shot:
    def __init__(self, name, frames, res=(1920, 1080), samples=None, pct=None, start_bar=1, gain=40.0):
        self.name, self.frames, self.start_bar, self.gain = name, frames, start_bar, gain
        self.a = args()
        self.pct = int(self.a.get('pct', pct or CFG.get('pct', 50)))
        bpy.ops.wm.read_factory_settings(use_empty=True)
        s = self.scene = bpy.context.scene
        self.coll = s.collection
        s.render.engine = 'BLENDER_EEVEE'
        s.render.resolution_x, s.render.resolution_y = res
        s.render.fps = int(CFG.get('fps', 30))
        s.frame_start, s.frame_end = 1, frames
        e = s.eevee
        e.taa_render_samples = int(self.a.get('samples', samples or CFG.get('samples', 16)))
        e.use_shadows = True
        e.volumetric_tile_size = str(self.a.get('vtile', 8))     # 16 makes fog blocky
        e.volumetric_samples = 64
        e.use_volumetric_shadows = True
        e.volumetric_end = 3000
        e.use_raytracing = False
        e.light_threshold = 0.0005                                # default culls weak lights: beams stop short
        try:
            s.view_settings.view_transform = 'AgX'
            s.view_settings.look = 'AgX - Punchy'
        except TypeError:
            pass
        w = self.world = bpy.data.worlds.new('world')
        s.world = w
        w.use_nodes = True
        self.bg = next(n for n in w.node_tree.nodes if n.type == 'BACKGROUND')
        self.bg.inputs['Color'].default_value = (0.004, 0.005, 0.01, 1)
        cam = self.cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
        self.coll.objects.link(cam)
        s.camera = cam
        cam.data.clip_start, cam.data.clip_end = 0.3, 20000
        self.target = bpy.data.objects.new('cam_target', None)
        self.coll.objects.link(self.target)
        c = cam.constraints.new('TRACK_TO')
        c.target = self.target
        c.track_axis, c.up_axis = 'TRACK_NEGATIVE_Z', 'UP_Y'

    # ---- content
    def room(self, stem, scale=1.0, tag=None):
        """a model extracted into build/x (rooms: some rips are 10x the others, use scale=0.1)."""
        r = dae_import.load(os.path.join(X, stem), tag or stem.lower(), self.coll)
        r.scale = (scale,) * 3
        bpy.context.view_layer.update()
        return r

    def dae(self, stem, name, loc=(0, 0, 0), rot=(0, 0, 0), scale=1.0):
        r = dae_import.load(os.path.join(X, stem), name, self.coll)
        e = bpy.data.objects.new(name + '_ctl', None)
        self.coll.objects.link(e)
        r.parent = e
        e.location, e.rotation_euler, e.scale = loc, [math.radians(v) for v in rot], (scale,) * 3
        return e

    def obj(self, path, name, loc=(0, 0, 0), rot=(0, 0, 0), scale=1.0):
        """an .obj under video/assets (rips often ship alpha 0 in the MTL: forced opaque)."""
        before = set(bpy.data.objects)
        bpy.ops.wm.obj_import(filepath=os.path.join(ASSETS, path), forward_axis='NEGATIVE_Z', up_axis='Y')
        e = bpy.data.objects.new(name, None)
        self.coll.objects.link(e)
        for o in [o for o in bpy.data.objects if o not in before and o is not e]:
            if o.parent is None:
                o.parent = e
            if o.type == 'MESH':
                for m in o.data.materials:
                    b = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None) if m and m.node_tree else None
                    if b and not b.inputs['Alpha'].is_linked:
                        b.inputs['Alpha'].default_value = 1.0
        e.location, e.rotation_euler, e.scale = loc, [math.radians(v) for v in rot], (scale,) * 3
        return e

    def character(self, rig, **kw):
        return Character(self, rig, **kw)

    def meshes(self, root):
        return [o for o in root.children_recursive if o.type == 'MESH']

    def bounds(self, root):
        bpy.context.view_layer.update()
        pts = [o.matrix_world @ Vector(c) for o in self.meshes(root) for c in o.bound_box]
        return (Vector([min(p[i] for p in pts) for i in range(3)]), Vector([max(p[i] for p in pts) for i in range(3)]))

    def fit(self, ctl, center, height=None, width=None):
        """scale to a bbox height (or width) and centre it. Skinned rips: bounds can miss the visible mesh; check a still."""
        lo, hi = self.bounds(ctl)
        k = (height / (hi.z - lo.z)) if height else (width / max(hi.x - lo.x, hi.y - lo.y)) if width else 1.0
        ctl.scale = ctl.scale * k
        lo, hi = self.bounds(ctl)
        ctl.location = ctl.location + (Vector(center) - (lo + hi) / 2)
        bpy.context.view_layer.update()
        return ctl

    def floor(self, x, y, z_from=-1e4):
        """z of the first surface above (x, y) from below: the floor. Room floors are NOT the bbox bottom."""
        bpy.context.view_layer.update()
        hit, loc, *_ = self.scene.ray_cast(bpy.context.evaluated_depsgraph_get(), Vector((x, y, z_from)), Vector((0, 0, 1)))
        return loc.z if hit else None

    def top(self, x, y, z_from=1e4):
        """z of the first surface below (x, y) from above (tables, counters, roofs)."""
        bpy.context.view_layer.update()
        hit, loc, *_ = self.scene.ray_cast(bpy.context.evaluated_depsgraph_get(), Vector((x, y, z_from)), Vector((0, 0, -1)))
        return loc.z if hit else None

    def cut_faces(self, root, pred):
        """delete faces whose world centre/normal satisfy pred(c, n): a wall that becomes a mirror.
        Rip normals can face either way: test abs(n.y), not its sign."""
        import bmesh
        n_del = 0
        for o in self.meshes(root):
            M = o.matrix_world
            N = M.to_3x3().inverted().transposed()
            bm = bmesh.new(); bm.from_mesh(o.data)
            dead = [f for f in bm.faces if pred(M @ f.calc_center_median(), (N @ f.normal).normalized())]
            n_del += len(dead)
            bmesh.ops.delete(bm, geom=dead, context='FACES')
            bm.to_mesh(o.data); bm.free()
        return n_del

    def glow(self, root, strength=0.5, alpha=None):
        """emission from the base texture (ghosts, haunted paintings, lit windows)."""
        seen = set()
        for o in self.meshes(root):
            for m in o.data.materials:
                if not m or m in seen:
                    continue
                seen.add(m)
                nt = m.node_tree
                b = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
                if b.inputs['Base Color'].is_linked:
                    nt.links.new(b.inputs['Base Color'].links[0].from_socket, b.inputs['Emission Color'])
                else:
                    b.inputs['Emission Color'].default_value = b.inputs['Base Color'].default_value
                b.inputs['Emission Strength'].default_value = strength
                if alpha is not None and not b.inputs['Alpha'].is_linked:
                    b.inputs['Alpha'].default_value = alpha
                    m.surface_render_method = 'BLENDED'

    # ---- song time inside a shot
    def events(self, track, fam=None):
        """song events as LOCAL frames of this shot (frame 1 = song frame of start_bar), from build/events.json."""
        ev = json.load(open(os.path.join(VD, 'build', 'events.json')))
        f0 = int(round((self.start_bar - 1) * ev['beats_per_bar'] * ev['frames_per_beat'] + ev.get('offset_frames', 0)))
        out = []
        for e in ev['tracks'].get(track, []):
            if fam and e.get('fam') != fam:
                continue
            lf = e['f'] - f0 + 1
            if 1 <= lf <= self.frames:
                out.append(dict(e, lf=lf))
        return out

    # ---- motion
    def bob(self, obj, n, amp=1.0, period=40, phase=0.0, step=4):
        base = obj.location.copy()
        for f in range(1, n + 1, step):
            obj.location = base + Vector((0, 0, amp * math.sin(2 * math.pi * f / period + phase)))
            obj.keyframe_insert('location', frame=f)

    def orbit(self, obj, n, center, radius, z, deg0, deg1, step=3, face_center=True, zwob=0.0, period=60, phase=0.0):
        for f in list(range(1, n + 1, step)) + [n]:
            t = (f - 1) / max(1, n - 1)
            a = math.radians(deg0 + (deg1 - deg0) * t)
            obj.location = (center[0] + radius * math.cos(a), center[1] + radius * math.sin(a), z + zwob * math.sin(2 * math.pi * f / period + phase))
            obj.keyframe_insert('location', frame=f)
            if face_center:
                obj.rotation_euler.z = a - math.pi / 2
                obj.keyframe_insert('rotation_euler', frame=f, index=2)

    # ---- light
    def light(self, kind, loc, energy, color=(1, 1, 1), target=None, size=None, spot_deg=None, blend=0.3, name=None, shadow=True):
        ld = bpy.data.lights.new(name or kind, kind)
        ld.energy = energy * (self.gain if kind != 'SUN' else 1.0)
        ld.color = color
        ld.use_shadow = shadow
        if spot_deg:
            ld.spot_size, ld.spot_blend = math.radians(spot_deg), blend
        if size is not None:
            if kind == 'AREA':
                ld.size = size
            else:
                ld.shadow_soft_size = size
        o = bpy.data.objects.new(name or kind, ld)
        self.coll.objects.link(o)
        o.location = loc
        if target is not None:
            self.aim(o, target)
        return o

    def aim(self, o, target):
        o.rotation_euler = (Vector(target) - Vector(o.location)).to_track_quat('-Z', 'Y').to_euler()

    def fog(self, center, size, density=0.01, color=(0.55, 0.65, 0.85), aniso=0.3):
        """a volume box (beams show only where there is fog). 540p + vtile 8 keeps it smooth."""
        bpy.ops.mesh.primitive_cube_add(size=1, location=center)
        box = bpy.context.object
        box.name, box.scale = 'fog', size
        m = bpy.data.materials.new('fog')
        nt = m.node_tree
        for n in list(nt.nodes):
            if n.type == 'BSDF_PRINCIPLED':
                nt.nodes.remove(n)
        v = nt.nodes.new('ShaderNodeVolumePrincipled')
        v.inputs['Density'].default_value = density
        v.inputs['Color'].default_value = (*color, 1)
        v.inputs['Anisotropy'].default_value = aniso
        nt.links.new(v.outputs[0], next(n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL').inputs['Volume'])
        box.data.materials.append(m)
        box.visible_shadow = False
        return box

    def mount(self, C, obj, bone, child, tilt=0.0, fwd=0.0):
        """parent obj to a bone, oriented in WORLD space along bone->child (the pose at call time); fwd moves it
        out past the child joint (a light inside a glove is shadowed by the glove)."""
        bpy.context.view_layer.update()
        h, f = C.bone_world(bone).translation, C.bone_world(child).translation
        d = ((f - h).normalized() + Vector((0, 0, tilt))).normalized()
        M = d.to_track_quat('-Z', 'Y').to_matrix().to_4x4()
        M.translation = f + d * fwd
        obj.parent, obj.parent_type, obj.parent_bone = C.rig, 'BONE', C.b(bone)
        bpy.context.view_layer.update()
        obj.matrix_world = M
        return obj

    def flashlight(self, C, energy=6000, deg=34, color=(1.0, 0.93, 0.75), tilt=-0.12, fwd=1.6):
        lt = self.light('SPOT', (0, 0, 0), energy, color, spot_deg=deg, blend=0.45, name='flashlight', size=0.3)
        bone, child = C.cfg.get('mounts', {}).get('hand', ['r_hand', 'r_fing'])
        self.mount(C, lt, bone, child, tilt, fwd)
        lt.data.use_soft_falloff = False
        return lt

    def back_mount(self, C, obj, back=3.2, down=1.2, yaw=180.0, scale=None):
        """a backpack (world placement at the current pose, then bone-parented to the mount's back bone)."""
        bone = C.cfg.get('mounts', {}).get('back', 'chest')
        bpy.context.view_layer.update()
        chest = C.bone_world(bone)
        fwd = (C.ctl.matrix_world.to_3x3() @ Vector((0, -1, 0))).normalized()
        s = scale or obj.scale[0]
        M = (Matrix.Translation(chest.translation - fwd * back - Vector((0, 0, down)))
             @ Matrix.Rotation(C.ctl.rotation_euler.z + math.radians(yaw), 4, 'Z') @ Matrix.Scale(s, 4))
        obj.parent, obj.parent_type, obj.parent_bone = C.rig, 'BONE', C.b(bone)
        bpy.context.view_layer.update()
        obj.matrix_world = M
        return obj

    def flicker(self, light, frames_off, length=6):
        """light off at each local frame for `length` frames (e.g. on the song's hits: S.events('growl'))."""
        d = light.data
        base = d.energy
        d.keyframe_insert('energy', frame=1)
        for f in frames_off:
            d.energy = base * 0.02; d.keyframe_insert('energy', frame=f)
            d.energy = base; d.keyframe_insert('energy', frame=f + length)
        interp(d, 'CONSTANT')

    def lightning(self, frames, loc, energy=25, color=(0.75, 0.82, 1.0), decay=5):
        """sun strikes with a double flicker at each local frame. A closed sky dome shadows the sun: split it off
        and set visible_shadow = False."""
        lt = self.light('SUN', loc, 0, color, name='lightning')
        self.aim(lt, (0, 0, 0))
        lt.data.keyframe_insert('energy', frame=1)
        for f in frames:
            for df, v in ((-1, 0), (0, 1), (1, 0.25), (2, 0.9), (3 + decay // 2, 0.2), (3 + decay, 0)):
                lt.data.energy = energy * v
                lt.data.keyframe_insert('energy', frame=max(1, f + df))
        interp(lt.data, 'LINEAR')
        return lt

    # ---- camera
    def camera(self, frame, loc, target, lens=None):
        self.cam.location = loc
        self.cam.keyframe_insert('location', frame=frame)
        self.target.location = target
        self.target.keyframe_insert('location', frame=frame)
        if lens:
            self.cam.data.lens = lens
            self.cam.data.keyframe_insert('lens', frame=frame)

    def ease(self, mode='BEZIER'):
        for idb in (self.cam, self.target, self.cam.data):
            interp(idb, mode)

    def handheld(self, amount=0.3, speed=1.0):
        for idb in (self.target, self.cam):
            fcs = [fc for fc in fcurves(idb) if fc.data_path == 'location']
            if not fcs:
                idb.keyframe_insert('location', frame=1)
                fcs = [fc for fc in fcurves(idb) if fc.data_path == 'location']
            for fc in fcs:
                n = fc.modifiers.new('NOISE')
                n.scale, n.strength = 40 / speed, amount * (1.0 if idb is self.target else 0.4)
                n.phase = hash((idb.name, fc.array_index)) % 100

    def dof(self, dist, fstop=2.0):
        d = self.cam.data.dof
        d.use_dof, d.aperture_fstop, d.focus_distance = True, fstop, dist

    # ---- output
    def _debug(self):
        a = self.a
        if a.get('dbg'):
            if a['dbg'] != 'lights':
                self.bg.inputs['Color'].default_value = (0.5, 0.5, 0.5, 1)
            if a['dbg'] in ('nofog', 'lights'):
                for o in [o for o in bpy.data.objects if o.name.startswith('fog')]:
                    bpy.data.objects.remove(o)
        if a.get('top'):
            cx, cy, span, zc = map(float, a['top'].split(','))
            self.scene.frame_set(int(a.get('still', 1)))
            for loc, r, col in ((self.cam.matrix_world.translation.copy(), 3, (1, 0, 0, 1)),
                                (self.target.matrix_world.translation.copy(), 2, (0, 1, 1, 1))):
                bpy.ops.mesh.primitive_uv_sphere_add(radius=r, location=(loc.x, loc.y, zc - 1))
                mm = bpy.data.materials.new('mark')
                b = next(n for n in mm.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
                b.inputs['Emission Color'].default_value, b.inputs['Emission Strength'].default_value = col, 20
                bpy.context.object.data.materials.append(mm)
            self.cam.constraints.clear()
            for fc in fcurves(self.cam):
                fc.mute = True
            self.cam.data.type, self.cam.data.ortho_scale = 'ORTHO', span
            self.cam.location, self.cam.rotation_euler = (cx, cy, zc + 500), (0, 0, 0)
            self.cam.data.clip_start, self.cam.data.clip_end = 500, 2000
            self.bg.inputs['Color'].default_value = (0.6, 0.6, 0.6, 1)
            for o in [o for o in bpy.data.objects if o.name.startswith('fog')]:
                bpy.data.objects.remove(o)
        if a.get('gain'):
            for l in bpy.data.lights:
                l.energy *= float(a['gain'])

    def go(self):
        s = self.scene
        self._debug()
        s.render.resolution_percentage = self.pct
        still = self.a.get('still')
        if still:
            s.frame_set(int(still))
            s.render.image_settings.media_type = 'IMAGE'
            s.render.image_settings.file_format = 'PNG'
            os.makedirs(os.path.join(VD, 'build', 'look'), exist_ok=True)
            s.render.filepath = os.path.join(VD, 'build', 'look', f'{self.name}_{int(still):04d}.png')
            bpy.ops.render.render(write_still=True)
            print('STILL', s.render.filepath)
            return
        outdir = os.path.join(VD, 'renders', 'shots')
        os.makedirs(outdir, exist_ok=True)
        v = 1
        while os.path.exists(os.path.join(outdir, f'{self.name}_v{v}.mp4')):
            v += 1
        im = s.render.image_settings
        im.media_type, im.file_format = 'VIDEO', 'FFMPEG'
        f = s.render.ffmpeg
        f.format, f.codec, f.constant_rate_factor, f.ffmpeg_preset, f.gopsize = 'MPEG4', 'H264', 'PERC_LOSSLESS', 'GOOD', 12
        s.render.filepath = os.path.join(outdir, f'{self.name}_v{v}.mp4')
        bpy.ops.render.render(animation=True)
        print('RENDERED', s.render.filepath)
