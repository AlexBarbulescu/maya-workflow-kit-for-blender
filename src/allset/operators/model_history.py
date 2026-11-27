# SPDX-License-Identifier: GPL-3.0-or-later
"""Versioned modeling recipes with one immutable input mesh and transactional replay."""

from collections import OrderedDict
from copy import deepcopy
import json
from types import SimpleNamespace
from uuid import uuid4

import bmesh
import bpy

from . import history_references as references

from .. import update_summary

KEY = 'allset_model_history'
BASE = 'allset_model_history_base'
VERSION = 3
OWNED = 'allset_history_input'
_cache = {}
_active = {}
_busy = set()
_valid = {}
CACHE_BUDGET = 256*1024*1024
_recent = OrderedDict()
_pending = {}


def primitive_topology(creation):
    from . import prim_history
    return [[name,value] for name,value in sorted(creation['attrs'].items()) if name != 'createUVs'
            and prim_history.entry_kind(creation['type'],name) in {'INT','BOOL','ENUM'}]


def seed_references(bm, creation=None):
    handles = references.layers(bm)
    if creation is not None:
        topology = primitive_topology(creation)
        original = creation.setdefault('topology', topology)
        if topology != original:
            for index, vertex in enumerate(bm.verts):
                references.assign(vertex, handles, references.generated(creation['id'], ('PRIMITIVE',topology,index)))


def trim_cache(protect=()):
    """Bound estimated inactive BMesh memory. Active selections and live edits remain resident."""
    from . import extrude
    protected = set(protect)
    protected.update(ob.name for ob in getattr(bpy.context, 'selected_objects', ()))
    live = {mesh.session_uid for mesh in bpy.data.meshes if mesh.users}
    for uid in set(_cache)-live:
        _cache.pop(uid, None)
        _active.pop(uid, None)
        _valid.pop(uid, None)
        _pending.pop(uid, None)
    costs = {}
    for name, rec in tuple(extrude.RECORDS.items()):
        ob = bpy.data.objects.get(name)
        if ob is None or ob.type != 'MESH' or ob.data.session_uid != rec.mesh_uid:
            rec.free()
            extrude.RECORDS.pop(name, None)
            _recent.pop(name, None)
            continue
        if rec.pre is None or rec.history_id is None:
            continue
        costs[name] = (len(rec.pre.verts)*96+len(rec.pre.edges)*80+len(rec.pre.faces)*352
                       +len(rec.moved)*640)
        _recent.setdefault(name, None)
    total = sum(costs.values())
    for name in tuple(_recent):
        rec = extrude.RECORDS.get(name)
        if rec is None:
            _recent.pop(name, None)
        elif total > CACHE_BUDGET and name not in protected and not rec.live and name in costs:
            total -= costs[name]
            rec.free()
            extrude.RECORDS.pop(name, None)
            _recent.pop(name, None)
    return total


def enabled():
    """Preferences > Persistent Modeling History (off by default): without it nothing is recorded or read, so a
    mesh keeps only its newest node, for the session (a recipe already in a file stays there unused)."""
    from .. import preferences
    try:
        return bool(preferences.get().model_history_files)
    except (AttributeError, KeyError):
        return False


def read(ob):
    if not isinstance(ob, bpy.types.Object) or ob.type != 'MESH' or not enabled():
        return None
    text = ob.data.get(KEY)
    if not isinstance(text, str):
        return None
    uid = ob.data.session_uid
    cached = _cache.get(uid)
    if cached is not None and cached[0] == text:
        return cached[1]
    _valid.pop(uid, None)
    try:
        data = json.loads(text)
        if (data['version'] not in (1, 2, VERSION) or not isinstance(data['nodes'], list)
                or not data['nodes'] or not isinstance(ob.data.get(BASE), bpy.types.Mesh)):
            return None
        from . import extrude
        for node in data['nodes']:
            if (node['kind'] not in extrude.SPECS or not isinstance(node['params'], dict)
                    or not isinstance(node['selection'], dict)):
                return None
            if node['kind'] == 'BRIDGE':
                node['params'].setdefault('evaluation_version', 0)
    except (KeyError, TypeError, ValueError):
        return None
    _cache[uid] = text, data
    if data['version'] < VERSION:
        upgraded = deepcopy(data)
        try:
            bm, checkpoint, _result, _moved = _evaluate(ob, upgraded)
            try:
                bm.to_mesh(checkpoint)
                full = extrude.mesh_coords_hash(checkpoint)
                if data['result_hash'] in (full, extrude.mesh_coords_hash(checkpoint, legacy=True)):
                    upgraded['result_hash'], upgraded['version'] = full, VERSION
                    data = upgraded
            finally:
                bm.free()
                bpy.data.meshes.remove(checkpoint)
        except (ValueError, RuntimeError, KeyError):
            pass
        _cache[uid] = text, data
    return data


def encode(data):
    data['version'] = VERSION
    for node in data['nodes']:
        node['selection'] = references.pack(node['selection'])
    return json.dumps(data, separators=(',', ':'), allow_nan=False)


def write(ob, data, text=None):
    text = encode(data) if text is None else text
    ob.data[KEY] = text
    _cache[ob.data.session_uid] = text, data
    _valid[ob.data.session_uid] = True


def token(data):
    upstream = [(node['id'], node['kind'], node['params'], node['unit'], node['input_hash'],
                 node.get('binding_revision',''))
                for node in data['nodes'][:-1]]
    last = data['nodes'][-1]
    return json.dumps((data.get('creation'), upstream, last['input_hash'], last.get('binding_revision','')),
                      sort_keys=True, separators=(',', ':'))


def _selection(bm):
    bm.verts.index_update()
    bm.edges.index_update()
    bm.faces.index_update()
    vertices = [v for v in bm.verts if v.select]
    edges = [e for e in bm.edges if e.select]
    faces = [f for f in bm.faces if f.select]
    selection = dict(vertices=None if len(vertices) == len(bm.verts) else [v.index for v in vertices],
                edges=None if len(edges) == len(bm.edges) else [[e.index, [v.index for v in e.verts]] for e in edges],
                faces=None if len(faces) == len(bm.faces) else [[f.index, [v.index for v in f.verts]] for f in faces],
                counts=[len(bm.verts), len(bm.edges), len(bm.faces)], mode=sorted(bm.select_mode))
    selection['references'] = references.capture(bm, selection)
    return selection


def _select(bm, selection, name, node_id=None):
    from . import extrude
    selection = references.unpack(selection)
    bm.select_mode = set(selection['mode']) or {'FACE'}
    bm.verts.index_update()
    bm.edges.index_update()
    bm.faces.index_update()
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    if 'references' in selection:
        resolved = references.resolve(bm, selection, node_id, name)
        extrude.deselect_all(bm)
        for field, sequence in (('vertices', bm.verts), ('edges', bm.edges), ('faces', bm.faces)):
            for element in sequence if resolved[field] is None else resolved[field]:
                element.select = True
        return
    counts = [len(bm.verts), len(bm.edges), len(bm.faces)]
    # References to generated components need an explicit rebind after upstream topology changes.
    if counts != selection['counts']:
        raise ValueError(name+' needs its component selection rebound after the upstream topology change')
    for sequence, entries in ((bm.edges, selection['edges']), (bm.faces, selection['faces'])):
        for index, vertices in entries or ():
            if index >= len(sequence) or set(vertices) != {v.index for v in sequence[index].verts}:
                raise ValueError(name+' has an incompatible component reference')
    extrude.deselect_all(bm)
    for index in selection['vertices'] or ():
        if not 0 <= index < len(bm.verts):
            raise ValueError(name+' references a missing vertex')
        bm.verts[index].select = True
    for sequence, entries in ((bm.edges, selection['edges']), (bm.faces, selection['faces'])):
        for index, _vertices in entries or ():
            sequence[index].select = True
    for sequence, entries in ((bm.verts, selection['vertices']), (bm.edges, selection['edges']),
                              (bm.faces, selection['faces'])):
        if entries is None:
            for element in sequence:
                element.select = True
    selection['references'] = references.capture(bm, selection)


def _build(bm, spec, params, unit, ob, node_id=None):
    from . import extrude
    if spec is extrude.FACE:
        caps, moved = extrude.extrude(bm, [f for f in bm.faces if f.select], unit=unit,
                                      history_id=node_id, matrix=ob.matrix_world.copy(), **params,
                                      **extrude.mesh_axes(ob))
        return caps, moved
    values = {key: params[key] for key in spec.fields+spec.hidden if key in params}
    values['_history_id'] = node_id
    tracked = spec.build(bm, values, unit, **({'ob': ob} if spec.with_object else {}))
    if not tracked and not spec.allow_empty:
        raise ValueError(spec.node_type+' did not produce valid geometry')
    references.tag_generic(bm, spec, params, node_id, tracked)
    return tracked, None


def creation_recipe(ob):
    """Uncommitted starting recipe for a primitive that has not yet acquired modeling nodes."""
    from . import extrude, prim_history, prim_shapes
    if ob.type != 'MESH':
        return None
    creation = prim_history.node_dict(prim_history.owner_of(ob))
    if creation is None or creation['type'] not in prim_shapes.POLY:
        return None
    creation['id'] = uuid4().hex
    creation['topology'] = primitive_topology(creation)
    data = dict(version=VERSION, nodes=[], creation=creation)
    bm, checkpoint, _result, _moved = _evaluate(ob, data)
    try:
        bm.to_mesh(checkpoint)
        data['result_hash'] = extrude.mesh_coords_hash(checkpoint)
    finally:
        bm.free()
        bpy.data.meshes.remove(checkpoint)
    return data


def _with_tweaks(ob, bm, snapshot, data, input_hash):
    """Represent coordinate-only edits as relative adjustments, preserving authored attributes and identities."""
    from . import extrude, shape_history
    evaluated, checkpoint, _result, _moved = _evaluate(ob, deepcopy(data))
    try:
        evaluated.to_mesh(checkpoint)
        if (extrude.mesh_coords_hash(checkpoint) != data['result_hash']
                or extrude.mesh_coords_hash(checkpoint, coordinates=False)
                != extrude.mesh_coords_hash(snapshot, coordinates=False)):
            return None
        handles = references.layers(evaluated)
        keys = [references.identity(vertex, handles) for vertex in evaluated.verts]
        if len(set(keys)) != len(keys):
            return None
        current = (bm.verts.layers.int.get(references.HIGH), bm.verts.layers.int.get(references.LOW))
        if all(current) and [references.identity(vertex, current) for vertex in bm.verts] != keys:
            return None
        deltas = [[*key, *(float(value)-float(old) for value, old in zip(vertex.co, original.co))]
                  for key, vertex, original in zip(keys, bm.verts, evaluated.verts)
                  if tuple(vertex.co) != tuple(original.co)]
        if not deltas:
            return None
        shape_history._tweak(evaluated, dict(deltas=deltas), 1.0)
        evaluated.to_mesh(checkpoint)
        if extrude.mesh_coords_hash(checkpoint) != input_hash:
            return None
        if not all(current):
            current = references.layers(bm)
            for vertex, key in zip(bm.verts, keys):
                references.assign(vertex, current, key)
        proposed = deepcopy(data)
        selection = dict(vertices=None, edges=None, faces=None,
                         counts=[len(bm.verts), len(bm.edges), len(bm.faces)], mode=sorted(bm.select_mode),
                         references=dict(vertices=None, edges=None, faces=None))
        proposed['nodes'].append(dict(id=uuid4().hex, name=extrude.next_name(bpy.context.scene, shape_history.TWEAK),
                                      kind='TWEAK', params=dict(deltas=deltas), selection=selection,
                                      unit=1.0, input_hash=data['result_hash'], binding_revision=uuid4().hex))
        proposed['result_hash'] = input_hash
        return proposed
    finally:
        evaluated.free()
        bpy.data.meshes.remove(checkpoint)


def prepare_input(ob, bm):
    """Capture once for input validation and persistence. Migrate identities before the next operation."""
    from . import extrude
    import numpy as np
    snapshot = bpy.data.meshes.new('.allset_history_input')
    try:
        bm.to_mesh(snapshot)
        input_hash = extrude.mesh_coords_hash(snapshot)
        data = read(ob) or creation_recipe(ob)
        replacing = (data is not None and data['nodes'] and data['nodes'][-1].get('input_hash') == input_hash)
        if data is not None and data.get('result_hash') != input_hash and not replacing:
            try:
                data = _with_tweaks(ob, bm, snapshot, data, input_hash) or data
            except (ValueError, RuntimeError, KeyError):
                pass
        new_base = data is None or (data.get('result_hash') != input_hash and not replacing)
        if new_base:
            references.layers(bm, reset=True)
            references.write_arrays(snapshot, (np.zeros(len(bm.verts), dtype=np.int32),
                                               np.arange(1, len(bm.verts)+1, dtype=np.int32)))
        elif bm.verts.layers.int.get(references.HIGH) is None:
            evaluated, checkpoint, _result, _moved = _evaluate(ob, data)
            try:
                if extrude.coords_hash(evaluated) != input_hash:
                    raise ValueError('The saved modeling recipe does not match its visible result')
                values = references.arrays(evaluated)
                handles = references.layers(bm)
                for vertex, high, low in zip(bm.verts, *values):
                    vertex[handles[0]], vertex[handles[1]] = int(high), int(low)
                references.write_arrays(snapshot, values)
            finally:
                evaluated.free()
                bpy.data.meshes.remove(checkpoint)
        references.write_arrays(snapshot, references.arrays(bm))
        return snapshot, input_hash, data
    except Exception:
        bpy.data.meshes.remove(snapshot)
        raise


def append(ob, rec, unit):
    """Record the already successful operation. Existing unsupported edits become a new input base."""
    if not enabled():
        return
    from . import extrude
    data = getattr(rec, 'input_history', None) or read(ob)
    rec.input_history = None
    snapshot = getattr(rec, 'input_snapshot', None)
    rec.input_snapshot = None
    try:
        if snapshot is None:
            snapshot = bpy.data.meshes.new('.allset_history_input')
            rec.pre.to_mesh(snapshot)
            input_hash = extrude.mesh_coords_hash(snapshot)
        else:
            input_hash = rec.input_hash
        replacing = (data is not None and data['nodes'] and data['nodes'][-1]['name'] == rec.name
                     and data['nodes'][-1].get('input_hash') == input_hash)
        fresh = ob.data.get(BASE) is None
        if fresh or data is None or (data.get('result_hash') != input_hash and not replacing):
            from . import prim_history, prim_shapes
            seed = fresh and data is not None and data.get('result_hash') == input_hash
            creation = data.get('creation') if seed else prim_history.node_dict(ob.data)
            if (creation is not None and creation['type'] in prim_shapes.POLY
                    and (seed or prim_history._sig_mesh(snapshot) == creation.get('sig'))):
                if not seed:
                    creation['id'] = uuid4().hex
                    creation['topology'] = primitive_topology(creation)
            else:
                creation = None
            for material in ob.data.materials:
                snapshot.materials.append(material)
            previous = ob.data.get(BASE)
            snapshot[OWNED] = True
            ob.data[BASE] = snapshot
            if previous is not None and previous.users == 0 and previous.get(OWNED):
                bpy.data.meshes.remove(previous)
            snapshot.name = '.'+ob.data.name+'_modelInput'
            snapshot = None
            baked = list(data.get('baked', ())) if data is not None else []
            if data is not None and not seed:
                original = data.get('creation')
                if original is not None:
                    baked.append(dict(id=original['id'], name=original['name'], kind='CREATION',
                                      node_type=original['type'], params=original['attrs']))
                for item in data['nodes']:
                    baked.append({key:item[key] for key in ('id', 'name', 'kind', 'params')})
            data = (deepcopy(data) if seed else dict(version=VERSION, nodes=[], creation=creation, baked=baked))
        else:
            data = deepcopy(data)
        node = dict(id=rec.history_id or uuid4().hex, name=rec.name, kind=rec.spec.kind, params=dict(rec.params),
                    selection=_selection(rec.pre), unit=unit, input_hash=input_hash,
                    binding_revision=uuid4().hex)
        # Re-running an operator on the same original input updates its node.
        if data['nodes'] and data['nodes'][-1]['name'] == rec.name:
            node['id'] = data['nodes'][-1]['id']
            node['binding_revision'] = data['nodes'][-1].get('binding_revision','')
            data['nodes'][-1] = node
        else:
            data['nodes'].append(node)
        data['result_hash'] = rec.states[-1][3]
        write(ob, data)
        rec.history_id = node['id']
        rec.history_token = token(data)
        _active[ob.data.session_uid] = node['id']
        _recent[ob.name] = None
        _recent.move_to_end(ob.name)
        trim_cache((ob.name,))
    finally:
        if snapshot is not None:
            bpy.data.meshes.remove(snapshot)


def update(ob, rec):
    data = read(ob)
    if data is None or data['nodes'][-1]['id'] != getattr(rec, 'history_id', None):
        return
    data = deepcopy(data)
    data['nodes'][-1]['params'] = dict(rec.params)
    data['result_hash'] = rec.states[-1][3]
    write(ob, data)
    rec.history_token = token(data)


def records(ob):
    data = read(ob)
    if data is None:
        return []
    from . import extrude
    baked = [SimpleNamespace(history_id=node['id'], name=node['name'], baked=True,
                             spec=extrude.SPECS.get(node['kind'], SimpleNamespace(
                                 kind=node['kind'], node_type=node.get('node_type', node['kind']), fields=(), labels={})),
                             params=dict(node['params']), pre=None, dismissed=True, cap_verts=[], cap_faces=[])
             for node in data.get('baked', ())]
    return baked + [SimpleNamespace(history_id=node['id'], name=node['name'], spec=extrude.SPECS[node['kind']],
                            params=dict(node['params']), pre=None, dismissed=False,
                            cap_verts=[], cap_faces=[]) for node in data['nodes']]


def find(ob, name_or_id):
    data = read(ob)
    if data is None:
        return None
    creation = data.get('creation')
    if creation is not None and name_or_id in (creation['id'], creation['name']):
        return SimpleNamespace(history_id=creation['id'], name=creation['name'], creation=creation)
    node = next((node for node in data['nodes'] if name_or_id in (node['id'], node['name'])), None)
    if node is None:
        return None
    from . import extrude
    return SimpleNamespace(history_id=node['id'], name=node['name'], spec=extrude.SPECS[node['kind']],
                           params=dict(node['params']), pre=None, dismissed=False, cap_verts=[], cap_faces=[])


def activate(ob, name_or_id):
    rec = find(ob, name_or_id)
    if rec is not None:
        _active[ob.data.session_uid] = rec.history_id
        wm = bpy.context.window_manager
        if wm is not None and hasattr(wm, 'allset_ae_tab'):
            last = read(ob)['nodes'][-1]['id']
            wm.allset_ae_tab = ('CH' if hasattr(rec, 'creation') else
                                'H' if rec.history_id == last else 'H:'+rec.history_id)
            wm.allset_ae_kind = 'CH' if hasattr(rec, 'creation') else 'H'
    return rec


def selected(ob):
    data = read(ob)
    if data is None:
        return None
    name = _active.get(ob.data.session_uid, data['nodes'][-1]['id'])
    return find(ob, name) or find(ob, data['nodes'][-1]['id'])


def drop(ob):
    if not isinstance(ob, bpy.types.Object) or ob.type != 'MESH':
        return
    references.drop(ob)
    base = ob.data.get(BASE)
    for key in (KEY, BASE):
        if key in ob.data:
            del ob.data[key]
    if base is not None and base.users == 0 and base.get(OWNED):
        bpy.data.meshes.remove(base)
    _cache.pop(ob.data.session_uid, None)
    _active.pop(ob.data.session_uid, None)
    _valid.pop(ob.data.session_uid, None)
    _pending.pop(ob.data.session_uid, None)


def _evaluate(ob, data):
    """Build off-screen. Keep one compact native Mesh checkpoint for the final node's input."""
    from . import extrude
    bm = bmesh.new()
    checkpoint = bpy.data.meshes.new('.allset_history_checkpoint')
    result, moved = [], None
    try:
        creation = data.get('creation')
        if creation is not None:
            from . import prim_history, prim_shapes
            values = {**prim_shapes.defaults(creation['type']), **creation['attrs']}
            prim_history.fill_bmesh(bm, prim_shapes.build(creation['type'], values),
                                    creation.get('unit', 1.0), prim_history.uvs_on(values, creation))
        else:
            bm.from_mesh(ob.data[BASE])
        seed_references(bm, creation)
        for index, node in enumerate(data['nodes']):
            _select(bm, node['selection'], node['name'], node['id'])
            if index == len(data['nodes'])-1:
                bm.to_mesh(checkpoint)
                node['input_hash'] = extrude.mesh_coords_hash(checkpoint)
            result, moved = _build(bm, extrude.SPECS[node['kind']], node['params'], node['unit'], ob, node['id'])
        return bm, checkpoint, result, moved
    except Exception:
        bm.free()
        bpy.data.meshes.remove(checkpoint)
        raise


def input_mesh(ob, node_id):
    """A detached input for a node preparing an explicit path or another dependency."""
    from . import extrude
    data = read(ob)
    if data is None:
        raise ValueError('The modeling history is no longer available')
    bm = bmesh.new()
    try:
        creation = data.get('creation')
        if creation is None:
            bm.from_mesh(ob.data[BASE])
        else:
            from . import prim_history, prim_shapes
            values = {**prim_shapes.defaults(creation['type']), **creation['attrs']}
            prim_history.fill_bmesh(bm, prim_shapes.build(creation['type'], values),
                                    creation.get('unit', 1), prim_history.uvs_on(values, creation))
        seed_references(bm, creation)
        for node in data['nodes']:
            _select(bm, node['selection'], node['name'], node['id'])
            if node['id'] == node_id:
                return bm
            _build(bm, extrude.SPECS[node['kind']], node['params'], node['unit'], ob, node['id'])
        raise ValueError('The modeling node is no longer available')
    except Exception:
        bm.free()
        raise


def _record(ob, data, bm, checkpoint, result, moved):
    from . import extrude
    last = data['nodes'][-1]
    pre = bmesh.new()
    pre.from_mesh(checkpoint)
    rec = extrude.Record(last['name'], pre, last['params'], extrude.SPECS[last['kind']])
    rec.mesh_uid = ob.data.session_uid
    rec.history_id = last['id']
    rec.history_token = token(data)
    if rec.spec is extrude.FACE:
        extrude._store(rec, bm, result, moved, last['params'], data['result_hash'])
    else:
        extrude._store_generic(rec, bm, result, last['params'], data['result_hash'])
    old = extrude.RECORDS.get(ob.name)
    if old is not None:
        old.free()
    extrude.RECORDS[ob.name] = rec
    _recent[ob.name] = None
    _recent.move_to_end(ob.name)
    trim_cache((ob.name,))
    return rec


def ensure(ob):
    from . import extrude
    rec = extrude.RECORDS.get(ob.name)
    data = read(ob)
    if data is None or ob.data.session_uid in _busy:
        return rec
    uid = ob.data.session_uid
    if rec is None or not rec.live:
        valid = _valid.get(uid)
        if valid is None:
            actual = (extrude.coords_hash(bmesh.from_edit_mesh(ob.data)) if ob.mode == 'EDIT'
                      else extrude.mesh_coords_hash(ob.data))
            valid = actual == data.get('result_hash')
            _valid[uid] = valid
        if not valid:
            return None
    if (rec is not None and rec.pre is not None and rec.mesh_uid == ob.data.session_uid
            and getattr(rec, 'history_id', None) == data['nodes'][-1]['id']
            and (rec.live or rec.params == data['nodes'][-1]['params'])
            and getattr(rec, 'history_token', None) == token(data)):
        if ob.name in _recent:
            _recent.move_to_end(ob.name)
        return rec
    _busy.add(ob.data.session_uid)
    try:
        bm, checkpoint, result, moved = _evaluate(ob, data)
        try:
            if extrude.coords_hash(bm) != data['result_hash']:
                return None
            return _record(ob, data, bm, checkpoint, result, moved)
        finally:
            bm.free()
            bpy.data.meshes.remove(checkpoint)
    except (ValueError, RuntimeError, KeyError):
        return None
    finally:
        _busy.discard(ob.data.session_uid)


def edit(ob, node_id, params, data=None):
    """Replay an earlier node and every downstream node before replacing visible geometry."""
    from . import extrude
    data = deepcopy(read(ob) if data is None else data)
    if data is None:
        raise ValueError('The modeling history is no longer available')
    if any(node['id'] == node_id for node in data.get('baked', ())):
        raise ValueError('This input was baked by a later mesh edit')
    snapshot = bpy.data.meshes.new('.allset_history_edit')
    source = bmesh.from_edit_mesh(ob.data) if ob.mode == 'EDIT' else bmesh.new()
    try:
        if ob.mode != 'EDIT':
            source.from_mesh(ob.data)
        source.to_mesh(snapshot)
        source_hash = extrude.mesh_coords_hash(snapshot)
        if source_hash != data.get('result_hash'):
            data = _with_tweaks(ob, source, snapshot, data, source_hash)
            if data is None:
                raise ValueError('The mesh has unrecorded topology or attribute edits; earlier inputs remain visible '
                                 'and will be kept as baked history when the next modeling operation is recorded')
    finally:
        if ob.mode != 'EDIT':
            source.free()
        bpy.data.meshes.remove(snapshot)
    node = next((node for node in data['nodes'] if node['id'] == node_id), None)
    creation = data.get('creation')
    editing_creation = creation is not None and creation['id'] == node_id
    if editing_creation:
        creation.setdefault('topology', primitive_topology(creation))
        creation['attrs'] = dict(params)
    elif node is None:
        raise ValueError('The modeling node is no longer available')
    else:
        node['params'] = dict(params)
    return apply_recipe(ob, data, node_id, source_hash=source_hash)


def apply_recipe(ob, data, origin_id, source_hash=None):
    from . import extrude
    saved = read(ob)
    actual = (extrude.coords_hash(bmesh.from_edit_mesh(ob.data)) if ob.mode == 'EDIT'
              else extrude.mesh_coords_hash(ob.data))
    if ((saved is None and (source_hash is None or not data.get('creation')))
            or actual != (source_hash if source_hash is not None else saved.get('result_hash'))):
        raise ValueError('The mesh has unrecorded edits; undo them or delete history before editing earlier inputs')
    json.dumps((data.get('creation'), [node['params'] for node in data['nodes']]), allow_nan=False)
    _busy.add(ob.data.session_uid)
    try:
        try:
            bm, checkpoint, result, moved = _evaluate(ob, data)
        except references.BindingError as error:
            _pending[ob.data.session_uid] = dict(data=data, node_id=error.node_id,
                                                origin_id=origin_id, original=ob.data.get(KEY), message=str(error),
                                                source_hash=actual)
            raise
        try:
            data['result_hash'] = extrude.coords_hash(bm)
            text = encode(data)
            creation = data.get('creation')
            legacy_creation = None
            if creation is not None:
                from . import prim_history
                legacy_creation = {key:value for key,value in creation.items() if key not in {'id','topology'}}
                checkpoint[prim_history.KEY] = legacy_creation
            if ob.mode == 'EDIT':
                extrude.restore_mesh(bmesh.from_edit_mesh(ob.data), bm)
                bmesh.update_edit_mesh(ob.data)
            else:
                bm.to_mesh(ob.data)
                ob.data.update()
            if ob.data.get(BASE) is None:
                base = checkpoint.copy()
                base[OWNED] = True
                ob.data[BASE] = base
            rec = _record(ob, data, bm, checkpoint, result, moved)
            write(ob, data, text)
            _pending.pop(ob.data.session_uid, None)
            if creation is not None:
                from . import prim_history
                ob.data[prim_history.KEY] = legacy_creation
            return rec
        finally:
            bm.free()
            bpy.data.meshes.remove(checkpoint)
    finally:
        _busy.discard(ob.data.session_uid)


def pending(ob):
    if not isinstance(ob, bpy.types.Object) or ob.type != 'MESH':
        return None
    info = _pending.get(ob.data.session_uid)
    if info is not None and ob.data.get(KEY) != info['original']:
        _pending.pop(ob.data.session_uid, None)
        return None
    return info


def binding_input(ob):
    """The proposed input of the first unresolved node, detached from the visible object."""
    info = pending(ob)
    if info is None:
        raise ValueError('There is no pending component binding')
    data = deepcopy(info['data'])
    from . import extrude
    bm = bmesh.new()
    try:
        creation = data.get('creation')
        if creation is None:
            bm.from_mesh(ob.data[BASE])
        else:
            from . import prim_history, prim_shapes
            values = {**prim_shapes.defaults(creation['type']), **creation['attrs']}
            prim_history.fill_bmesh(bm, prim_shapes.build(creation['type'], values),
                                    creation.get('unit', 1), prim_history.uvs_on(values, creation))
        seed_references(bm, creation)
        for node in data['nodes']:
            if node['id'] == info['node_id']:
                extrude.deselect_all(bm)
                bm.select_mode = set(node['selection']['mode'])
                return bm, node
            _select(bm, node['selection'], node['name'], node['id'])
            _build(bm, extrude.SPECS[node['kind']], node['params'], node['unit'], ob, node['id'])
        raise ValueError('The pending history node is no longer available')
    except Exception:
        bm.free()
        raise


def rebind(ob, selection):
    info = pending(ob)
    if info is None:
        raise ValueError('The pending edit is no longer available')
    from . import extrude
    actual = (extrude.coords_hash(bmesh.from_edit_mesh(ob.data)) if ob.mode == 'EDIT'
              else extrude.mesh_coords_hash(ob.data))
    if actual != info['source_hash']:
        _pending.pop(ob.data.session_uid, None)
        raise ValueError('The original mesh changed while its replacement selection was being prepared')
    data = deepcopy(info['data'])
    node = next(node for node in data['nodes'] if node['id'] == info['node_id'])
    node['selection'] = selection
    node['binding_revision'] = uuid4().hex
    return apply_recipe(ob, data, info['origin_id'], source_hash=info['source_hash'])


@bpy.app.handlers.persistent
def clear(_dummy=None):
    _cache.clear()
    _active.clear()
    _busy.clear()
    _valid.clear()
    _recent.clear()
    _pending.clear()


def invalidate():
    _valid.clear()


@bpy.app.handlers.persistent
def changed(_scene, depsgraph):
    # a Mesh in the update flags the type (one array read; a pass over the update walks every ID of the depsgraph)
    if not depsgraph.id_type_updated('MESH'):
        return
    for update in update_summary.updates(depsgraph, changed):
        data = update.id.original
        if isinstance(data, bpy.types.Mesh) and update.is_updated_geometry and KEY in data:
            if data.session_uid not in _busy and _valid.get(data.session_uid) is not False:
                _valid.pop(data.session_uid, None)
