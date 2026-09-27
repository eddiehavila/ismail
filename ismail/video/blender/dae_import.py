"""Inside Blender: rebuild a model from dae_extract.py output (meshes, UVs, vertex colors, textures, skin rig).

    import dae_import; root = dae_import.load('build/x/Hero', 'hero')
"""
import json, os
import bpy
import numpy as np
from mathutils import Matrix

_IMG = {}


def _image(path):
    if path not in _IMG:
        _IMG[path] = bpy.data.images.load(path, check_existing=True)
    return _IMG[path]


def _material(name, info, has_col):
    m = bpy.data.materials.new(name)
    nt = m.node_tree
    bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
    bsdf.inputs['Roughness'].default_value = 0.7
    col_out = None
    if info['image'] and os.path.exists(info['image']):
        tex = nt.nodes.new('ShaderNodeTexImage')
        tex.image = _image(info['image'])
        tex.interpolation = 'Linear'
        col_out = tex.outputs['Color']
        if info['alpha_tex']:
            nt.links.new(tex.outputs['Alpha'], bsdf.inputs['Alpha'])
            m.surface_render_method = 'DITHERED'
    else:
        bsdf.inputs['Base Color'].default_value = info['color']
    if has_col:
        vc = nt.nodes.new('ShaderNodeVertexColor')
        vc.layer_name = 'Col'
        mix = nt.nodes.new('ShaderNodeMix')
        mix.data_type = 'RGBA'
        mix.blend_type = 'MULTIPLY'
        mix.inputs['Factor'].default_value = 1.0
        if col_out is not None:
            nt.links.new(col_out, mix.inputs['A'])
        else:
            mix.inputs['A'].default_value = info['color']
        nt.links.new(vc.outputs['Color'], mix.inputs['B'])
        col_out = mix.outputs['Result']
    if col_out is not None:
        nt.links.new(col_out, bsdf.inputs['Base Color'])
    return m


def load(stem, name, collection=None):
    man = json.load(open(stem + '.json'))
    A = np.load(stem + '.npz')
    coll = collection or bpy.context.scene.collection
    mats = {}
    root = bpy.data.objects.new(name, None)
    coll.objects.link(root)
    if man['upaxis'] == 'Y_UP':
        root.rotation_euler = (np.pi / 2, 0, 0)

    arm = None
    if man['joints']:
        rest = {j['name']: Matrix(j['matrix']) for j in man['joints']}
        for m in man['meshes']:
            for jn, ib in m.get('inv_bind', {}).items():
                rest[jn] = Matrix(ib).inverted()
        ad = bpy.data.armatures.new(name + '_rig')
        arm = bpy.data.objects.new(name + '_rig', ad)
        coll.objects.link(arm)
        arm.parent = root
        bpy.context.view_layer.objects.active = arm
        bpy.ops.object.mode_set(mode='EDIT')
        kids = {}
        for j in man['joints']:
            kids.setdefault(j['parent'], []).append(j['name'])
        ebs = {}
        for j in man['joints']:
            M = rest[j['name']]
            head = M.to_translation()
            ln = 0.0
            for k in kids.get(j['name'], []):
                ln = max(ln, (rest[k].to_translation() - head).length)
            eb = ad.edit_bones.new(j['name'])
            eb.head = (0, 0, 0)
            eb.tail = (0, max(ln, 4.0), 0)
            R = M.to_3x3().normalized().to_4x4()
            R.translation = head
            eb.matrix = R
            ebs[j['name']] = eb
        for j in man['joints']:
            if j['parent'] in ebs:
                ebs[j['name']].parent = ebs[j['parent']]
        bpy.ops.object.mode_set(mode='OBJECT')

    objs = []
    for i, m in enumerate(man['meshes']):
        if f'm{i}_pos' not in A:
            continue
        pos, tri = A[f'm{i}_pos'], A[f'm{i}_tri']
        me = bpy.data.meshes.new(f"{name}_{m['name']}")
        me.from_pydata(pos.tolist(), [], tri.tolist())
        loops = tri.reshape(-1)
        if f'm{i}_uv' in A:
            uvl = me.uv_layers.new(name='UV')
            uv = A[f'm{i}_uv'][A[f'm{i}_uvi'].reshape(-1)]
            uvl.data.foreach_set('uv', uv[:, :2].reshape(-1))
        has_col = f'm{i}_col' in A
        if has_col:
            c = A[f'm{i}_col'][A[f'm{i}_coli'].reshape(-1)]
            if c.shape[1] == 3:
                c = np.c_[c, np.ones(len(c), np.float32)]
            ca = me.color_attributes.new('Col', 'FLOAT_COLOR', 'CORNER')
            ca.data.foreach_set('color', c.reshape(-1))
        for slot in m['materials']:
            key = (slot, has_col)
            if key not in mats:
                mats[key] = _material(f"{name}_{slot}", man['materials'].get(slot, {'image': None, 'alpha_tex': False, 'color': [.8, .8, .8, 1]}), has_col)
            me.materials.append(mats[key])
        me.polygons.foreach_set('material_index', A[f'm{i}_mat'])
        me.polygons.foreach_set('use_smooth', np.ones(len(tri), bool))
        me.validate(); me.update()
        ob = bpy.data.objects.new(me.name, me)
        coll.objects.link(ob)
        if m['skinned'] and arm is not None:
            ob.parent = arm
            names = m['joint_names']
            wv, wj, ww = A[f'm{i}_wv'], A[f'm{i}_wj'], A[f'm{i}_ww']
            groups = {}
            for v, j, w in zip(wv.tolist(), wj.tolist(), ww.tolist()):
                jn = names[j]
                if jn not in groups:
                    groups[jn] = ob.vertex_groups.new(name=jn)
                groups[jn].add([v], w, 'ADD')
            mod = ob.modifiers.new('rig', 'ARMATURE')
            mod.object = arm
        else:
            ob.parent = root
            ob.matrix_parent_inverse = Matrix.Identity(4)
            ob.matrix_basis = Matrix(m['matrix'])
        objs.append(ob)
    root['lm_objects'] = [o.name for o in objs]
    return root
