# <pep8 compliant>
# Written by Stephan Vedder and Michael Schnabel

import bpy
from mathutils import Vector, Quaternion
from io_mesh_w3d.common.utils.helpers import *
from io_mesh_w3d.common.utils.primitives import *

REST_LOC_PROP = '_w3d_rest_location'
REST_ROT_PROP = '_w3d_rest_rotation'


def get_or_create_skeleton(hierarchy, coll):
    if hierarchy is None:
        return None

    name = hierarchy.header.name.upper()
    for obj in bpy.data.objects:
        if obj.name.upper() == name and obj.type == 'ARMATURE':
            return obj

    return create_bone_hierarchy(hierarchy, coll)


def create_rig(name, root, coll):
    armature = bpy.data.armatures.new(name)
    armature.show_names = False

    rig = bpy.data.objects.new(name, armature)
    rig.rotation_mode = 'QUATERNION'
    rest_matrix = pivot_rest_matrix(root)
    location, rotation, scale = rest_matrix.decompose()
    rig.location = location
    rig.rotation_quaternion = rotation
    rig.scale = scale
    rig.delta_location = Vector((0.0, 0.0, 0.0))
    rig.delta_rotation_quaternion = Quaternion((1.0, 0.0, 0.0, 0.0))
    rig[REST_LOC_PROP] = (location.x, location.y, location.z)
    rig[REST_ROT_PROP] = (rotation.w, rotation.x, rotation.y, rotation.z)
    rig.track_axis = 'POS_X'
    link_object_to_active_scene(rig, coll)
    bpy.ops.object.mode_set(mode='EDIT')
    return rig, armature


def create_bone_hierarchy(hierarchy, coll):
    root = hierarchy.pivots[0]
    rig, armature = create_rig(hierarchy.name(), root, coll)
    pivot_lookup = {pivot.name: pivot for pivot in hierarchy.pivots}

    for pivot in hierarchy.pivots:
        bone = armature.edit_bones.new(pivot.name)
        matrix = pivot_rest_matrix(pivot)

        if pivot.parent_id >= 0:
            parent_pivot = hierarchy.pivots[pivot.parent_id]
            bone.parent = armature.edit_bones[parent_pivot.name]
            matrix = bone.parent.matrix @ matrix

        bone.head = Vector((0.0, 0.0, 0.0))
        bone.tail = Vector((0.0, 0.0, 0.01))
        bone.matrix = matrix

    bpy.ops.object.mode_set(mode='POSE')
    (basic_sphere, sphere_mesh) = create_sphere()

    for bone in rig.pose.bones:
        bone.custom_shape = basic_sphere
        pivot = pivot_lookup.get(bone.name)
        if pivot is not None:
            bone[REST_LOC_PROP] = (
                pivot.translation.x,
                pivot.translation.y,
                pivot.translation.z)
            bone[REST_ROT_PROP] = (
                pivot.rotation.w,
                pivot.rotation.x,
                pivot.rotation.y,
                pivot.rotation.z)

    bpy.ops.object.mode_set(mode='OBJECT')

    bpy.data.objects.remove(basic_sphere)
    bpy.data.meshes.remove(sphere_mesh)
    return rig


def pivot_local_matrix(pivot):
    matrix = make_transform_matrix(pivot.translation, pivot.rotation)
    return matrix


def pivot_rest_matrix(pivot):
    return pivot_local_matrix(pivot)


def pivot_world_matrix(hierarchy, pivot_idx):
    if hierarchy is None or pivot_idx is None or pivot_idx < 0 or hierarchy.pivots is None:
        return None

    cache = getattr(hierarchy, '_pivot_world_cache', None)
    if cache is None:
        cache = {}
        setattr(hierarchy, '_pivot_world_cache', cache)

    def _build_world_matrix(idx):
        if idx in cache:
            return cache[idx].copy()

        pivot = hierarchy.pivots[idx]
        matrix = pivot_rest_matrix(pivot)
        parent_idx = pivot.parent_id
        if parent_idx is not None and parent_idx >= 0:
            parent_matrix = _build_world_matrix(parent_idx)
            if parent_matrix is not None:
                matrix = parent_matrix @ matrix

        cache[idx] = matrix.copy()
        return matrix.copy()

    return _build_world_matrix(pivot_idx)
