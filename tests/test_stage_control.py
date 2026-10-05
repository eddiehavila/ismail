"""Actor profiles beside their bodies (rig type, named parts, control map presets) and the control map ops."""
import json
import struct
import urllib.error

import pytest

from ismail.api import OPS, OpError
from ismail.stage import rigs
from test_stage import FakePage, _get, stage  # noqa: F401  (the fixture)

HUMAN_BONES = ['Root', 'pelvis', 'spine_01', 'spine_02', 'spine_03', 'neck_01', 'head',
               'clavicle_l', 'upperarm_l', 'lowerarm_l', 'hand_l', 'clavicle_r', 'upperarm_r', 'lowerarm_r', 'hand_r',
               'thigh_l', 'calf_l', 'foot_l', 'ball_l', 'thigh_r', 'calf_r', 'foot_r', 'ball_r']
HUMAN_PARENT = {'pelvis': 'Root', 'spine_01': 'pelvis', 'spine_02': 'spine_01', 'spine_03': 'spine_02', 'neck_01': 'spine_03',
                'head': 'neck_01', 'clavicle_l': 'spine_03', 'upperarm_l': 'clavicle_l', 'lowerarm_l': 'upperarm_l',
                'hand_l': 'lowerarm_l', 'clavicle_r': 'spine_03', 'upperarm_r': 'clavicle_r', 'lowerarm_r': 'upperarm_r',
                'hand_r': 'lowerarm_r', 'thigh_l': 'pelvis', 'calf_l': 'thigh_l', 'foot_l': 'calf_l', 'ball_l': 'foot_l',
                'thigh_r': 'pelvis', 'calf_r': 'thigh_r', 'foot_r': 'calf_r', 'ball_r': 'foot_r'}
for sd in 'lr':
    for fg in rigs.FINGERS:
        for k in (1, 2, 3):
            HUMAN_BONES.append(f'{fg}_0{k}_{sd}')
            HUMAN_PARENT[f'{fg}_0{k}_{sd}'] = f'hand_{sd}' if k == 1 else f'{fg}_0{k - 1}_{sd}'


def glb(names, parent):
    """A .glb with one skin over these bones (no meshes or buffers: enough for the profile)."""
    idx = {n: i for i, n in enumerate(names)}
    nodes = [{'name': n, 'children': [idx[c] for c in names if parent.get(c) == n]} for n in names]
    j = json.dumps({'asset': {'version': '2.0'}, 'nodes': nodes, 'skins': [{'joints': list(range(len(names)))}]}).encode()
    j += b' ' * (-len(j) % 4)
    return b'glTF' + struct.pack('<II', 2, 12 + 8 + len(j)) + struct.pack('<I', len(j)) + b'JSON' + j


DOG = ['root', 'hips', 'spine', 'neck', 'skull', 'tail_1', 'tail_2', 'tail_3', 'leg_fl', 'paw_fl']
DOG_PARENT = {'hips': 'root', 'spine': 'hips', 'neck': 'spine', 'skull': 'neck', 'tail_1': 'hips', 'tail_2': 'tail_1',
              'tail_3': 'tail_2', 'leg_fl': 'spine', 'paw_fl': 'leg_fl'}


def test_a_human_body_reads_as_a_human_rig_with_its_parts():
    bones = rigs.bones_of(glb(HUMAN_BONES, HUMAN_PARENT))
    assert ('hand_l', 'lowerarm_l') in bones and ('Root', None) in bones
    assert rigs.rig_type(b for b, _ in bones) == 'human_game_engine'
    parts = rigs.derived_parts(bones)
    assert parts['leg_l'] == ['thigh_l', 'calf_l', 'foot_l'] and parts['index_r'] == ['index_01_r', 'index_02_r', 'index_03_r']
    assert len(parts['fingers_l']) == 15


def test_any_other_rig_gets_a_part_per_branch():
    bones = rigs.bones_of(glb(DOG, DOG_PARENT))
    assert rigs.rig_type(b for b, _ in bones) == 'unknown_10_bones'
    parts = rigs.derived_parts(bones)
    assert parts == {'root': ['root', 'hips'], 'spine': ['spine'], 'neck': ['neck', 'skull'],
                     'tail_1': ['tail_1', 'tail_2', 'tail_3'], 'leg_fl': ['leg_fl', 'paw_fl']}


def test_drives_are_checked_against_the_rig():
    parts = rigs.derived_parts(rigs.bones_of(glb(HUMAN_BONES, HUMAN_PARENT)))
    assert rigs.check_drive({'part': 'leg_l', 'mode': 'effector', 'joint': 'hand_l', 'scale': None}, parts) == \
        {'part': 'leg_l', 'mode': 'effector', 'joint': 'hand_l'}
    for bad, msg in [({'part': 'tail', 'mode': 'hold'}, 'part is one of'),
                     ({'part': 'head', 'mode': 'effector', 'joint': 'hand_l'}, 'reaches'),
                     ({'part': 'leg_l', 'mode': 'effector'}, 'joint='),
                     ({'part': 'leg_l', 'mode': 'effector', 'joint': 'knee'}, 'joint='),
                     ({'part': 'index_l', 'mode': 'mimic', 'joint': ['hand_r:index-finger-tip'] * 2}, '1:1'),
                     ({'part': 'arm_r', 'mode': 'pin'}, 'at=')]:
        with pytest.raises(ValueError, match=msg):
            rigs.check_drive(bad, parts)


def _body(stage, who='bf_sam', names=HUMAN_BONES, parent=HUMAN_PARENT):
    d = stage['scenes'] / 'room' / 'actors'
    d.mkdir(exist_ok=True)
    (d / f'{who}.glb').write_bytes(glb(names, parent))
    return d


def test_the_profile_lives_beside_the_body(stage):
    d = _body(stage)
    prof = json.loads(OPS['stage_actor_profile'](scene='room', actor='bf_sam'))
    assert prof['rig'] == 'human_game_engine' and prof['maps'] == {} and 'leg_r' in prof['effectors']
    out = OPS['stage_actor_profile'](scene='room', actor='bf_sam', save_map='seated', map={
        'pins': {'hips': 'stool_3'}, 'drives': [{'part': 'leg_l', 'mode': 'effector', 'joint': 'hand_l', 'touch': True}]})
    assert "saved map 'seated'" in out and 'presets now: seated' in out
    own = json.loads((d / 'bf_sam.json').read_text(encoding='utf-8'))
    assert own['maps']['seated']['pins'] == {'hips': 'stool_3'}
    OPS['stage_actor_profile'](scene='room', actor='bf_sam', save_map='default', map={'drives': [{'part': 'head', 'mode': 'hold'}]})
    assert (d / 'bf_sam.json.prev').is_file()
    got = _get(stage['port'], 'actor/profile?scene=room&who=bf_sam')[1]
    assert set(got['maps']) == {'seated', 'default'} and got['file'] == 'bf_sam.json'


def test_a_derived_scene_finds_the_bodies_in_its_assets(stage):
    _body(stage)
    (stage['scenes'] / 'attic' / 'world.json').write_text(json.dumps({'assets': 'room'}), encoding='utf-8')
    assert _get(stage['port'], 'actor/profile?scene=attic&who=bf_sam')[1]['rig'] == 'human_game_engine'
    with pytest.raises(urllib.error.HTTPError):
        _get(stage['port'], 'actor/profile?scene=attic&who=nobody')


def test_a_bad_map_is_not_saved(stage):
    d = _body(stage, 'dog', DOG, DOG_PARENT)
    with pytest.raises(OpError, match='reaches'):
        OPS['stage_actor_profile'](scene='room', actor='dog', save_map='x', map={'drives': [{'part': 'tail_1', 'mode': 'effector', 'joint': 'hand_r'}]})
    with pytest.raises(OpError, match='pins are'):
        OPS['stage_actor_profile'](scene='room', actor='dog', save_map='x', map={'pins': {'tail': 'x'}})
    with pytest.raises(OpError, match='no body'):
        OPS['stage_actor_profile'](scene='room', actor='cat')
    assert not (d / 'dog.json').exists()
    OPS['stage_actor_profile'](scene='room', actor='dog', save_map='wag', map={'drives': [
        {'part': 'tail_1', 'mode': 'mimic', 'joint': ['hand_r:index-finger-metacarpal', 'hand_r:index-finger-phalanx-proximal', 'hand_r:index-finger-tip']}]})
    assert json.loads((d / 'dog.json').read_text(encoding='utf-8'))['maps']['wag']['drives'][0]['part'] == 'tail_1'


def test_control_ops_reach_the_page(stage):
    page = FakePage(stage['port'], 'room')
    try:
        OPS['stage_control_set'](scene='room', person='person_bar_lean', part='leg_l', mode='effector', joint='hand_l', touch=True)
        c = page.seen[-1]
        assert (c['type'], c['part'], c['mode'], c['joint'], c['touch']) == ('control_set', 'leg_l', 'effector', 'hand_l', True)
        OPS['stage_control_set'](scene='room', person='person_bar_lean', part='arm_r', mode='hold')
        assert 'touch' not in page.seen[-1] and 'joint' not in page.seen[-1]
        OPS['stage_control_map'](scene='room', person='person_bar_lean', preset='seated', clear=True)
        assert (page.seen[-1]['type'], page.seen[-1]['preset'], page.seen[-1]['clear']) == ('control_map', 'seated', True)
        for kw, msg in [({'mode': 'fly'}, 'mode is one of'), ({'mode': 'mimic'}, 'joint='), ({'mode': 'pin'}, 'at=')]:
            with pytest.raises(OpError, match=msg):
                OPS['stage_control_set'](scene='room', person='p', part='leg_l', **kw)
        with pytest.raises(OpError, match='stage_control_set'):
            OPS['stage_cmd'](scene='room', type='control_set')
    finally:
        page.stop = True
