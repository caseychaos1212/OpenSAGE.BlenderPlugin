# <pep8 compliant>
# Written by Stephan Vedder and Michael Schnabel

import bpy
from mathutils import Vector, Quaternion
from io_mesh_w3d.w3d.adaptive_delta import decode
from io_mesh_w3d.common.structs.animation import *
from io_mesh_w3d.w3d.structs.compressed_animation import *

REST_LOC_PROP = '_w3d_rest_location'
REST_ROT_PROP = '_w3d_rest_rotation'


def is_roottransform(channel):
    return channel.pivot < 0


def is_translation(channel):
    return channel.type < 3


def is_visibility(channel):
    return isinstance(channel, AnimationBitChannel) or channel.type == CHANNEL_VIS


def _vector_from_prop(owner, prop_name, fallback=None):
    data = owner.get(prop_name)
    if data is not None:
        return Vector(data)
    if fallback is not None:
        return fallback.copy()
    return Vector((0.0, 0.0, 0.0))


def _quat_from_prop(owner, prop_name, fallback=None):
    data = owner.get(prop_name)
    if data is not None:
        return Quaternion(data)
    if fallback is not None:
        return fallback.copy()
    return Quaternion((1.0, 0.0, 0.0, 0.0))


def get_bone(context, rig, hierarchy, channel):
    if is_roottransform(channel):
        if is_visibility(channel):
            context.warning(
                f'armature \'{hierarchy.name()}\' might have been hidden due to visibility animation channels!')
        rest_loc = _vector_from_prop(rig, REST_LOC_PROP, rig.location)
        rest_rot = _quat_from_prop(rig, REST_ROT_PROP, rig.rotation_quaternion)
        return rig, rest_loc, rest_rot

    if channel.pivot >= len(hierarchy.pivots):
        context.warning(
            f'animation channel for bone with ID \'{channel.pivot}\' is invalid -> armature has only {len(hierarchy.pivots)} bones!')
        return None
    pivot = hierarchy.pivots[channel.pivot]

    if is_visibility(channel) and pivot.name in rig.data.bones:
        return rig.data.bones[pivot.name], None, None

    pose_bone = rig.pose.bones[pivot.name]
    rest_loc = _vector_from_prop(pose_bone, REST_LOC_PROP)
    rest_rot = _quat_from_prop(pose_bone, REST_ROT_PROP)
    return pose_bone, rest_loc, rest_rot


def setup_animation(animation):
    bpy.context.scene.render.fps = animation.header.frame_rate
    bpy.context.scene.frame_start = 0
    bpy.context.scene.frame_end = animation.header.num_frames - 1


creation_options = {'INSERTKEY_NEEDED'}
BASELINE_TRANSLATIONS = {}
BASELINE_ROTATIONS = {}


def set_translation(bone, index, frame, value, rest_location=None):
    if isinstance(bone, bpy.types.Object):
        base = rest_location[index] if rest_location is not None else 0.0
        bone.location[index] = base + value
    else:
        bone.location[index] = value
    bone.keyframe_insert(data_path='location', index=index, frame=frame, options=creation_options)


def set_rotation(bone, frame, value, rest_rotation=None):
    if isinstance(bone, bpy.types.Object):
        base = rest_rotation if rest_rotation is not None else Quaternion((1.0, 0.0, 0.0, 0.0))
        bone.rotation_quaternion = base @ value
    else:
        bone.rotation_quaternion = value
    bone.keyframe_insert(data_path='rotation_quaternion', frame=frame)


def set_visibility(context, bone, frame, value):
    if isinstance(bone, bpy.types.Bone):
        if bpy.app.version != (4, 4, 3):  # TODO fix 4.4.3
            bone.visibility = value
            bone.keyframe_insert(data_path='visibility', frame=frame, options=creation_options)
        else:
            context.warning(f'bone visibility channels are currently not supported for blender 4.4.3!')
    else:
        bone.hide_viewport = bool(value)
        bone.keyframe_insert(data_path='hide_viewport', frame=frame, options=creation_options)


def _log_channel_debug(context, bone, channel, rest_location, rest_rotation, value):
    reporter = getattr(context, 'info', None)
    if reporter is None or not callable(reporter):
        return
    name = getattr(bone, 'name', getattr(getattr(bone, 'data', None), 'name', 'UNKNOWN'))
    if is_translation(channel):
        axis = ['X', 'Y', 'Z'][channel.type] if channel.type < 3 else str(channel.type)
        rest_val = rest_location[channel.type] if rest_location is not None else 0.0
        reporter(f'[AnimDebug] {name} axis {axis}: rest={rest_val:.6f} first_key={value:.6f}')
    else:
        if isinstance(value, Quaternion):
            first = (value.w, value.x, value.y, value.z)
        else:
            first = tuple(value) if isinstance(value, (tuple, list)) else value
        rest = (rest_rotation.w, rest_rotation.x, rest_rotation.y, rest_rotation.z) if rest_rotation else (1.0, 0.0, 0.0, 0.0)
        reporter(f'[AnimDebug] {name} rotation: rest={rest} first_key={first}')


def _apply_baseline(bone, channel, value, baselines):
    if isinstance(bone, bpy.types.Object) or baselines is None:
        return value
    trans_baselines, rot_baselines = baselines
    if is_translation(channel):
        key = (channel.pivot, channel.type)
        baseline = trans_baselines.setdefault(key, value)
        return value - baseline
    else:
        baseline = rot_baselines.setdefault(channel.pivot, Quaternion(value))
        return baseline.inverted() @ Quaternion(value)


def set_keyframe(context, bone, channel, frame, value, rest_location=None, rest_rotation=None, baselines=None):
    if not isinstance(bone, bpy.types.Object):
        value = _apply_baseline(bone, channel, value, baselines)
    if is_visibility(channel):
        set_visibility(context, bone, frame, value)
    elif is_translation(channel):
        set_translation(bone, channel.type, frame, value, rest_location)
    else:
        set_rotation(bone, frame, value, rest_rotation)


def apply_timecoded(context, bone, channel, rest_location=None, rest_rotation=None, baselines=None):
    logged = False
    for key in channel.time_codes:
        if not logged:
            _log_channel_debug(context, bone, channel, rest_location, rest_rotation, key.value)
            logged = True
        set_keyframe(context, bone, channel, key.time_code, key.value, rest_location, rest_rotation, baselines)


def apply_motion_channel_time_coded(context, bone, channel, rest_location=None, rest_rotation=None, baselines=None):
    logged = False
    for datum in channel.data:
        if not logged:
            _log_channel_debug(context, bone, channel, rest_location, rest_rotation, datum.value)
            logged = True
        set_keyframe(context, bone, channel, datum.time_code, datum.value, rest_location, rest_rotation, baselines)


def apply_motion_channel_adaptive_delta(context, bone, channel, rest_location=None, rest_rotation=None, baselines=None):
    data = decode(channel.type, channel.vector_len, channel.num_time_codes, channel.data.scale, channel.data.data)
    logged = False
    for i in range(channel.num_time_codes):
        if not logged:
            _log_channel_debug(context, bone, channel, rest_location, rest_rotation, data[i])
            logged = True
        set_keyframe(context, bone, channel, i, data[i], rest_location, rest_rotation, baselines)


def apply_adaptive_delta(context, bone, channel, rest_location=None, rest_rotation=None, baselines=None):
    data = decode(channel.type, channel.vector_len, channel.num_time_codes, channel.scale, channel.data)
    logged = False
    for i in range(channel.num_time_codes):
        if not logged:
            _log_channel_debug(context, bone, channel, rest_location, rest_rotation, data[i])
            logged = True
        set_keyframe(context, bone, channel, i, data[i], rest_location, rest_rotation, baselines)


def apply_uncompressed(context, bone, channel, rest_location=None, rest_rotation=None, baselines=None):
    logged = False
    for index in range(channel.last_frame - channel.first_frame + 1):
        data = channel.data[index]
        frame = index + channel.first_frame
        if not logged:
            _log_channel_debug(context, bone, channel, rest_location, rest_rotation, data)
            logged = True
        set_keyframe(context, bone, channel, frame, data, rest_location, rest_rotation, baselines)


def process_channels(context, hierarchy, channels, rig, apply_func, baselines):
    for channel in channels:
        bone_info = get_bone(context, rig, hierarchy, channel)
        if bone_info is None:
            continue

        obj, rest_location, rest_rotation = bone_info
        apply_func(context, obj, channel, rest_location, rest_rotation, baselines)


def process_motion_channels(context, hierarchy, channels, rig, baselines):
    for channel in channels:
        bone_info = get_bone(context, rig, hierarchy, channel)
        if bone_info is None:
            continue

        obj, rest_location, rest_rotation = bone_info
        if channel.delta_type == 0:
            apply_motion_channel_time_coded(context, obj, channel, rest_location, rest_rotation, baselines)
        else:
            apply_motion_channel_adaptive_delta(context, obj, channel, rest_location, rest_rotation, baselines)


def create_animation(context, rig, animation, hierarchy):
    if animation is None:
        return

    setup_animation(animation)
    rig_id = id(rig) if rig is not None else None
    baselines = (BASELINE_TRANSLATIONS.setdefault(rig_id, {}), BASELINE_ROTATIONS.setdefault(rig_id, {}))

    if isinstance(animation, CompressedAnimation):
        process_channels(context, hierarchy, animation.time_coded_channels, rig, apply_timecoded, baselines)
        process_channels(context, hierarchy, animation.adaptive_delta_channels, rig, apply_adaptive_delta, baselines)
        process_motion_channels(context, hierarchy, animation.motion_channels, rig, baselines)
    else:
        process_channels(context, hierarchy, animation.channels, rig, apply_uncompressed, baselines)

    if rig is not None and rig.animation_data is not None and rig.animation_data.action is not None:
        rig.animation_data.action.name = animation.header.name
    elif rig is not None and rig.data is not None and rig.data.animation_data is not None and rig.data.animation_data.action is not None:
        rig.data.animation_data.action.name = animation.header.name

    bpy.context.scene.frame_set(0)
    if rig_id in BASELINE_TRANSLATIONS:
        del BASELINE_TRANSLATIONS[rig_id]
    if rig_id in BASELINE_ROTATIONS:
        del BASELINE_ROTATIONS[rig_id]
