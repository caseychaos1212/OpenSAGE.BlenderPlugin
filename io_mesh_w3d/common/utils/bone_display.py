# <pep8 compliant>
"""Display the axes used by OpenW3D without changing bone or animation transforms.

Engine references:
  Code/Combat/weapons.cpp: muzzle velocity uses +X.
  Code/Combat/vehicle.cpp: turret yaw is Z, barrel pitch is Y.
  Code/wwphys/wheel.h and wheel.cpp: suspension is -Z, axle is Z,
  translation constraints use Z, and fork constraints rotate about Y.
https://github.com/w3dhub/OpenW3D
"""

from math import cos, sin, tau

import bpy
from mathutils import Vector

SHAPE_TAG = '_w3d_game_bone_shape'

# Direction shown by the arrow, optional rotation ring, and UI explanation.
DISPLAYS = {
    'MUZZLE': ((1, 0, 0), None, 'Muzzle: +X firing direction'),
    'TURRET': ((1, 0, 0), (0, 0, 1), 'Turret: +X forward, Z turn axis'),
    'BARREL': ((1, 0, 0), (0, 1, 0), 'Barrel: +X forward, Y pitch axis'),
    'WHEELP': ((0, 0, -1), None, 'WheelP: -Z suspension toward ground'),
    'WHEELC': ((0, 0, 1), (0, 0, 1), 'WheelC: Z wheel axle / rotation axis'),
    'WHEELF': ((0, 1, 0), (0, 1, 0), 'WheelF: Y fork rotation axis'),
    'WHEELT': ((0, 0, 1), None, 'WheelT: Z suspension translation axis'),
}


def game_bone_role(name):
    name = name.upper()
    if name in ('TURRET', 'BARREL'):
        return name
    for prefix in ('MUZZLE', 'WHEELP', 'WHEELC', 'WHEELF', 'WHEELT'):
        if name.startswith(prefix):
            return prefix
    return None


def game_bone_description(name):
    role = game_bone_role(name)
    return DISPLAYS[role][2] if role else ''


def _perpendiculars(axis):
    reference = Vector((0, 0, 1)) if abs(axis.z) < 0.9 else Vector((0, 1, 0))
    first = axis.cross(reference).normalized()
    return first, axis.cross(first).normalized()


def _get_shape(role):
    # Shapes stay outside scene collections, so exporters and renders never see
    # them as scene geometry. Pose-bone references keep them in saved blends.
    for obj in bpy.data.objects:
        if obj.type == 'MESH' and obj.get(SHAPE_TAG) == role:
            return obj

    direction, ring_axis, _ = DISPLAYS[role]
    axis = Vector(direction)
    first, second = _perpendiculars(axis)
    vertices = [Vector((0, 0, 0)), axis.copy()]
    edges = [(0, 1)]
    for side in (first, -first, second, -second):
        vertices.append(axis * 0.72 + side * 0.13)
        edges.append((1, len(vertices) - 1))

    # A small cross marks the actual pivot position.
    for side in (first, second):
        start = len(vertices)
        vertices.extend((-side * 0.09, side * 0.09))
        edges.append((start, start + 1))

    if ring_axis is not None:
        first, second = _perpendiculars(Vector(ring_axis))
        start = len(vertices)
        for index in range(24):
            angle = tau * index / 24
            vertices.append(0.28 * (first * cos(angle) + second * sin(angle)))
            edges.append((start + index, start + (index + 1) % 24))

    mesh = bpy.data.meshes.new('W3D Direction ' + role)
    mesh.from_pydata(vertices, edges, [])
    mesh.update()
    shape = bpy.data.objects.new('W3D Direction ' + role, mesh)
    shape[SHAPE_TAG] = role
    return shape


def apply_game_bone_shapes(rig, enabled=True):
    if rig is None or rig.type != 'ARMATURE':
        return
    if enabled:
        rig.data.show_bone_custom_shapes = True
    for bone in rig.pose.bones:
        current = bone.custom_shape
        owned = current is not None and SHAPE_TAG in current
        role = game_bone_role(bone.name)
        if not enabled or role is None:
            if owned:
                bone.custom_shape = None
            continue
        # Preserve shapes supplied by an animator.
        if current is not None and not owned:
            continue
        bone.custom_shape = _get_shape(role)
        bone.custom_shape_transform = None
        bone.use_custom_shape_bone_size = True
        if hasattr(bone, 'custom_shape_scale_xyz'):
            bone.custom_shape_scale_xyz = (1.0, 1.0, 1.0)
        else:
            bone.custom_shape_scale = 1.0
        if hasattr(bone, 'custom_shape_translation'):
            bone.custom_shape_translation = (0.0, 0.0, 0.0)
            bone.custom_shape_rotation_euler = (0.0, 0.0, 0.0)
