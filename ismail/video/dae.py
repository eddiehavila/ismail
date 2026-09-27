"""DAE -> (manifest.json, arrays.npz) for tools/blend_build.py. Blender 5 dropped Collada; pycollada reads it here.

python tools/dae_extract.py <in.dae> <out_stem>
"""
import json, os, sys
import numpy as np
import collada
from collada import scene as S
from PIL import Image


def local_matrix(node):
    return np.array(node.matrix, dtype=np.float64) if hasattr(node, 'matrix') else np.eye(4)


def image_info(path, base):
    if not path:
        return None, False
    p = path.replace('file://', '').replace('%20', ' ')
    full = p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p))
    if not os.path.exists(full):
        alt = os.path.join(base, os.path.basename(p))
        full = alt if os.path.exists(alt) else full
    alpha = False
    try:
        im = Image.open(full)
        if im.mode in ('RGBA', 'LA', 'P'):
            a = np.asarray(im.convert('RGBA'))[..., 3]
            alpha = bool((a < 250).mean() > 0.002)
    except Exception:
        pass
    return full, alpha


def material_info(mat, base):
    eff = mat.effect
    out = {'image': None, 'alpha_tex': False, 'color': [0.8, 0.8, 0.8, 1.0]}
    dif = eff.diffuse
    if isinstance(dif, collada.material.Map):
        out['image'], out['alpha_tex'] = image_info(dif.sampler.surface.image.path, base)
    elif dif is not None:
        out['color'] = [float(x) for x in dif]
    return out


def main(src, stem):
    base = os.path.dirname(os.path.abspath(src))
    d = collada.Collada(src, ignore=[collada.common.DaeUnsupportedError, collada.common.DaeBrokenRefError])
    mats = {m.id: material_info(m, base) for m in d.materials}
    joints, jindex = [], {}
    meshes, arrays = [], {}

    def add_joint(node, parent, world):
        nm = node.xmlnode.get('sid') or node.xmlnode.get('name') or node.id
        jindex[nm] = len(joints)
        joints.append({'name': nm, 'parent': parent, 'matrix': world.tolist()})
        return nm

    def mesh_from(geom, matbind, world, skin=None):
        i = len(meshes)
        pos = np.asarray(geom.primitives[0].vertex if geom.primitives else np.zeros((0, 3)), np.float32)
        tris, uvi, coli, matidx = [], [], [], []
        uv, col = None, None
        slots = []
        for p in geom.primitives:
            if isinstance(p, (collada.polylist.Polylist, collada.polygons.Polygons)):
                p = p.triangleset()
            if not isinstance(p, collada.triangleset.TriangleSet) or len(p) == 0:
                continue
            sym = p.material
            mid = matbind.get(sym, sym)
            if mid not in slots:
                slots.append(mid)
            tris.append(np.asarray(p.vertex_index, np.int32))
            matidx.append(np.full(len(p.vertex_index), slots.index(mid), np.int32))
            if p.texcoordset:
                uv = np.asarray(p.texcoordset[0], np.float32)
                uvi.append(np.asarray(p.texcoord_indexset[0], np.int32))
            else:
                uvi.append(np.zeros_like(p.vertex_index, dtype=np.int32))
            cs = p.sources.get('COLOR') if hasattr(p, 'sources') else None
            if cs:
                off = cs[0][0]
                col = np.asarray(cs[0][4].data, np.float32)
                coli.append(np.asarray(p.indices[:, :, off], np.int32))
            else:
                coli.append(None)
        if not tris:
            return
        arrays[f'm{i}_pos'] = pos
        arrays[f'm{i}_tri'] = np.concatenate(tris)
        arrays[f'm{i}_mat'] = np.concatenate(matidx)
        if uv is not None:
            arrays[f'm{i}_uv'] = uv
            arrays[f'm{i}_uvi'] = np.concatenate(uvi)
        if col is not None and all(c is not None for c in coli):
            arrays[f'm{i}_col'] = col
            arrays[f'm{i}_coli'] = np.concatenate(coli)
        entry = {'name': geom.name or geom.id, 'matrix': world.tolist(), 'materials': slots, 'skinned': skin is not None}
        if skin is not None:
            bsm = np.asarray(skin.bind_shape_matrix, np.float64)
            p4 = np.c_[pos, np.ones(len(pos))] @ bsm.T
            arrays[f'm{i}_pos'] = p4[:, :3].astype(np.float32)
            names = [str(x) for x in np.ravel(skin.weight_joints.data)]
            wsrc = np.ravel(skin.weights.data) if hasattr(skin.weights, 'data') else np.ravel(skin.weights)
            vi, ji, ww = [], [], []
            for v, pairs in enumerate(skin.index):
                for jj, wi in np.asarray(pairs).reshape(-1, 2):
                    vi.append(v); ji.append(jj); ww.append(wsrc[wi])
            arrays[f'm{i}_wv'] = np.asarray(vi, np.int32)
            arrays[f'm{i}_wj'] = np.asarray(ji, np.int32)
            arrays[f'm{i}_ww'] = np.asarray(ww, np.float32)
            entry['joint_names'] = names
            entry['inv_bind'] = {str(k): np.asarray(m, np.float64).tolist() for k, m in skin.joint_matrices.items()}
        meshes.append(entry)

    def walk(node, world, parent_joint):
        w = world @ local_matrix(node)
        pj = parent_joint
        if isinstance(node, S.Node) and node.xmlnode.get('type') == 'JOINT':
            pj = add_joint(node, parent_joint, w)
        for ch in getattr(node, 'children', []):
            if isinstance(ch, S.Node):
                walk(ch, w, pj)
            elif isinstance(ch, S.GeometryNode):
                mesh_from(ch.geometry, {m.symbol: m.target.id for m in ch.materials}, w)
            elif isinstance(ch, S.ControllerNode):
                c = ch.controller
                mesh_from(c.geometry, {m.symbol: m.target.id for m in ch.materials}, w, skin=c)

    for n in d.scene.nodes:
        walk(n, np.eye(4), None)
    man = {'source': os.path.abspath(src), 'upaxis': d.assetInfo.upaxis, 'unit': d.assetInfo.unitmeter,
           'materials': mats, 'meshes': meshes, 'joints': joints}
    with open(stem + '.json', 'w') as f:
        json.dump(man, f)
    np.savez_compressed(stem + '.npz', **arrays)
    nv = sum(len(arrays[f'm{i}_pos']) for i in range(len(meshes)) if f'm{i}_pos' in arrays)
    print(f"{os.path.basename(src)}: {len(meshes)} meshes, {nv} verts, {len(joints)} joints, {len(mats)} materials, up={d.assetInfo.upaxis}")


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
