# <pep8 compliant>
# Written by Stephan Vedder and Michael Schnabel

import os
import re

import bpy

from io_mesh_w3d.common.utils.animation_compat import iter_action_fcurves, iter_animation_data_fcurves

POSE_BONE_PATTERN = re.compile(r'pose\.bones\["([^"]+)"\]')


def default_import_log_path(source_path):
    directory = os.path.dirname(source_path) if source_path else os.getcwd()
    basename = os.path.splitext(os.path.basename(source_path))[0] if source_path else 'w3d-import'
    version = '.'.join(str(value) for value in bpy.app.version)
    return os.path.join(directory, f'{basename}.import.blender-{version}.log.txt')


def write_import_log(operator, context):
    lines = build_import_log_lines(operator, context)
    path = default_import_log_path(getattr(operator, 'filepath', ''))
    with open(path, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write('\n'.join(lines))
        handle.write('\n')
    return path


def build_import_log_lines(operator, context):
    state = getattr(operator, '_w3d_import_state', None) or {}
    source_path = state.get('source_path') or getattr(operator, 'filepath', '')
    lines = [
        'W3D Import Review Log',
        f'BlenderVersion: {getattr(bpy.app, "version_string", bpy.app.version)}',
        f'SourceFile: {source_path or "-"}',
        f'FileFormat: {getattr(operator, "file_format", "") or "-"}',
    ]

    loaded_files = state.get('loaded_files') or getattr(operator, '_w3d_loaded_files', None) or []
    lines.append('')
    lines.append('[LoadedFiles]')
    if loaded_files:
        for path in loaded_files:
            lines.append(path)
    else:
        lines.append('-')

    messages = getattr(operator, '_w3d_log_buffer', None) or []
    lines.append('')
    lines.append('[Messages]')
    if messages:
        lines.extend(messages)
    else:
        lines.append('-')

    lines.append('')
    lines.append('[ImportState]')
    lines.append(f'CaptureSource: {state.get("capture_source") or "-"}')
    lines.append(f'Collection: {state.get("collection_name") or "-"}')
    lines.append(f'Hierarchy: {state.get("hierarchy_name") or "-"}')
    lines.append(f'Rig: {state.get("rig_name") or "-"}')
    animation_names = state.get('animation_names') or []
    lines.append(f'Animations: {", ".join(animation_names) if animation_names else "-"}')

    object_names = state.get('object_names') or []
    if not object_names and state.get('collection_name'):
        collection = bpy.data.collections.get(state['collection_name'])
        if collection is not None:
            collection_objects = getattr(collection, 'all_objects', collection.objects)
            object_names = [obj.name for obj in collection_objects]
    if not object_names:
        object_names = _infer_object_names(messages, state.get('rig_name'))
    lines.append(f'Objects: {len(object_names)}')
    lines.append(f'ObjectNames: {", ".join(object_names) if object_names else "-"}')

    objects = _resolve_objects(object_names)
    if objects:
        lines.append('')
        lines.append('[Objects]')
        for obj in objects:
            _append_object_summary(lines, obj)

        _append_samples(lines, context, objects, state.get('rig_name'))

    return lines


def _resolve_objects(object_names):
    objects = []
    for name in sorted(set(object_names)):
        obj = bpy.data.objects.get(name)
        if obj is not None:
            objects.append(obj)
    return objects


def _infer_object_names(messages, rig_name=None):
    object_names = []
    for message in messages:
        match = re.search(r"creating mesh '([^']+)'", message)
        if match is not None:
            object_names.append(match.group(1))
    if rig_name:
        object_names.append(rig_name)
    return sorted(set(object_names))


def _append_object_summary(lines, obj):
    lines.append(f'Object: {obj.name}')
    lines.append(f'  Type: {obj.type}')
    lines.append(f'  Data: {getattr(getattr(obj, "data", None), "name", "-")}')
    lines.append(f'  Parent: {obj.parent.name if obj.parent else "-"}')
    lines.append(f'  ParentType: {obj.parent_type or "-"}')
    lines.append(f'  ParentBone: {obj.parent_bone or "-"}')
    lines.append(f'  HiddenViewport: {bool(getattr(obj, "hide_viewport", False))}')
    lines.append(f'  LocalLocation: {_format_vector(obj.location)}')
    lines.append(f'  LocalRotation: {_format_local_rotation(obj)}')
    lines.append(f'  LocalScale: {_format_vector(obj.scale)}')
    lines.append(f'  Dimensions: {_format_vector(obj.dimensions)}')

    world_location, world_rotation, world_scale = obj.matrix_world.decompose()
    lines.append(f'  WorldLocation: {_format_vector(world_location)}')
    lines.append(f'  WorldRotation: {_format_quaternion(world_rotation)}')
    lines.append(f'  WorldScale: {_format_vector(world_scale)}')

    if obj.type == 'MESH':
        armature_modifiers = [mod for mod in obj.modifiers if mod.type == 'ARMATURE']
        lines.append(
            f'  MeshDeform: vertex_groups={len(obj.vertex_groups)} armature_modifiers={len(armature_modifiers)}')
        if obj.vertex_groups:
            lines.append(f'  VertexGroups: {", ".join(group.name for group in obj.vertex_groups)}')
        else:
            lines.append('  VertexGroups: -')
        if armature_modifiers:
            modifiers = []
            for mod in armature_modifiers:
                target = mod.object.name if mod.object else '-'
                modifiers.append(
                    f'{mod.name}(target={target},use_vertex_groups={mod.use_vertex_groups},'
                    f'use_bone_envelopes={mod.use_bone_envelopes})')
            lines.append(f'  ArmatureModifiers: {", ".join(modifiers)}')
        else:
            lines.append('  ArmatureModifiers: -')

    _append_action_summary(lines, 'ObjectAction', getattr(obj, 'animation_data', None))
    data_block = getattr(obj, 'data', None)
    _append_action_summary(lines, 'DataAction', getattr(data_block, 'animation_data', None))


def _append_action_summary(lines, label, animation_data):
    action = getattr(animation_data, 'action', None) if animation_data is not None else None
    if action is None:
        lines.append(f'  {label}: -')
        return

    lines.append(f'  {label}: {action.name}')
    fcurves = sorted(list(iter_animation_data_fcurves(animation_data)), key=lambda item: (item.data_path, item.array_index))
    if not fcurves:
        all_curves = sorted(list(iter_action_fcurves(action)), key=lambda item: (item.data_path, item.array_index))
        if not all_curves:
            lines.append('    FCurves: -')
            return
        lines.append('    FCurves: [all slots fallback]')
        fcurves = all_curves

    for fcurve in fcurves:
        keyframes = []
        for keyframe in fcurve.keyframe_points:
            keyframes.append(
                f'({_format_float(keyframe.co.x)}, {_format_float(keyframe.co.y)}, {keyframe.interpolation})')
        payload = '; '.join(keyframes) if keyframes else '-'
        lines.append(f'    {fcurve.data_path}[{fcurve.array_index}]: {payload}')


def _append_samples(lines, context, objects, rig_name):
    scene = getattr(context, 'scene', None)
    if scene is None:
        return

    frames = _collect_sample_frames(scene, objects)
    if not frames:
        return

    rig = bpy.data.objects.get(rig_name) if rig_name else None
    animated_bones = _collect_animated_bones(rig)
    view_layer = getattr(context, 'view_layer', None)
    current_frame = scene.frame_current
    current_subframe = scene.frame_subframe

    lines.append('')
    lines.append('[Samples]')
    lines.append(f'Frames: {", ".join(str(frame) for frame in frames)}')

    try:
        for frame in frames:
            scene.frame_set(frame)
            if view_layer is not None:
                view_layer.update()

            lines.append(f'Frame: {frame}')
            for obj in objects:
                location, rotation, scale = obj.matrix_world.decompose()
                lines.append(
                    f'  ObjectWorld {obj.name}: loc={_format_vector(location)} '
                    f'rot={_format_quaternion(rotation)} scale={_format_vector(scale)} '
                    f'dims={_format_vector(obj.dimensions)}')

            if rig is not None:
                for bone_name in animated_bones:
                    pose_bone = rig.pose.bones.get(bone_name)
                    if pose_bone is None:
                        continue
                    location, rotation, scale = (rig.matrix_world @ pose_bone.matrix).decompose()
                    lines.append(
                        f'  PoseBoneWorld {rig.name}.{bone_name}: loc={_format_vector(location)} '
                        f'rot={_format_quaternion(rotation)} scale={_format_vector(scale)}')
    finally:
        scene.frame_set(current_frame, subframe=current_subframe)
        if view_layer is not None:
            view_layer.update()


def _collect_sample_frames(scene, objects):
    frame_start = int(scene.frame_start)
    frame_end = int(scene.frame_end)
    if frame_end < frame_start:
        return [frame_start]

    if frame_end - frame_start <= 60:
        return list(range(frame_start, frame_end + 1))

    frames = {frame_start, frame_end}
    for obj in objects:
        for action in _get_actions(obj):
            for fcurve in iter_action_fcurves(action):
                for keyframe in fcurve.keyframe_points:
                    frame = int(round(keyframe.co.x))
                    if frame_start <= frame <= frame_end:
                        frames.add(frame)
    return sorted(frames)


def _collect_animated_bones(rig):
    if rig is None:
        return []

    animation_data = getattr(rig, 'animation_data', None)
    action = getattr(animation_data, 'action', None) if animation_data is not None else None
    if action is None:
        return []

    result = set()
    for fcurve in iter_animation_data_fcurves(animation_data):
        match = POSE_BONE_PATTERN.search(fcurve.data_path)
        if match is not None:
            result.add(match.group(1))
    return sorted(result)


def _get_actions(obj):
    actions = []
    for id_block in (obj, getattr(obj, 'data', None)):
        candidate = _get_action(id_block)
        if candidate is not None and candidate not in actions:
            actions.append(candidate)
    return actions


def _get_action(id_block):
    if id_block is None:
        return None
    animation_data = getattr(id_block, 'animation_data', None)
    if animation_data is None:
        return None
    return getattr(animation_data, 'action', None)


def _format_float(value):
    return f'{float(value):.6f}'


def _format_vector(value):
    return '(' + ', '.join(_format_float(component) for component in value) + ')'


def _format_quaternion(value):
    return '(' + ', '.join(_format_float(component) for component in (value.w, value.x, value.y, value.z)) + ')'


def _format_local_rotation(obj):
    if obj.rotation_mode == 'QUATERNION':
        return f'QUATERNION {_format_quaternion(obj.rotation_quaternion)}'
    if obj.rotation_mode == 'AXIS_ANGLE':
        return f'AXIS_ANGLE {_format_vector(obj.rotation_axis_angle)}'
    return f'{obj.rotation_mode} {_format_vector(obj.rotation_euler)}'
