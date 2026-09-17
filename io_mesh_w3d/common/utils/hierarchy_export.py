# <pep8 compliant>
# Written by Stephan Vedder and Michael Schnabel

from mathutils import Vector, Quaternion
from ...common.utils.helpers import *
from ...common.structs.hierarchy import *
from ...common.utils.object_settings_bridge import should_export_object, should_export_transform


pick_plane_names = ['PICK']


def retrieve_hierarchy(context, container_name):
    root = HierarchyPivot(name='ROOTTRANSFORM')
    terrain_mode = getattr(context, '_w3d_export_options', {}).get('terrain_mode', False)

    hierarchy = Hierarchy(
        header=HierarchyHeader(),
        pivots=[root])

    rig = None
    rigs = [obj for obj in get_objects('ARMATURE') if should_export_object(obj)]

    pivot_id_dict = dict()

    if len(rigs) == 0:
        hierarchy.header.name = container_name
        hierarchy.header.center_pos = Vector()
        context.warning('scene does not contain an armature object!')

    if len(rigs) > 0:
        rig = rigs[0]

        switch_to_pose(rig, 'REST')

        root_name = rig.get('_w3d_root_bone')
        # Also recognize rigs imported by earlier versions of this fork.
        if root_name is None and '_w3d_rest_location' in rig and 'ROOTTRANSFORM' in rig.pose.bones:
            root_name = 'ROOTTRANSFORM'
        if root_name and root_name in rig.pose.bones:
            root.name = root_name
            pivot_id_dict[root_name] = 0
            root.translation = Vector(rig['_w3d_rest_location'])
            root.rotation = Quaternion(rig['_w3d_rest_rotation'])
        else:
            root.translation = rig.delta_location.copy()
            root.rotation = rig.delta_rotation_quaternion.copy()

        hierarchy.header.name = rig.data.name
        hierarchy.header.center_pos = Vector(rig.get('_w3d_center', (0, 0, 0))) if root_name else rig.location.copy()

        for bone in rig.pose.bones:
            process_bone(bone, pivot_id_dict, hierarchy)

        switch_to_pose(rig, 'POSE')

    if len(rigs) > 1:
        context.error(f'only one armature per scene allowed! Exporting only the first one: {rigs[0].name}')

    if not terrain_mode:
        meshes = get_objects('MESH')

        for mesh in meshes:
            if not should_export_transform(mesh):
                continue
            process_mesh(context, mesh, hierarchy, pivot_id_dict)

    hierarchy.header.num_pivots = len(hierarchy.pivots)
    return hierarchy, rig


def process_bone(bone, pivot_id_dict, hierarchy):
    if bone.name in pivot_id_dict.keys():
        return

    pivot = HierarchyPivot(name=bone.name, parent_id=0)
    matrix = bone.matrix

    if bone.parent is not None:
        if bone.parent.name not in pivot_id_dict.keys():
            process_bone(bone.parent, pivot_id_dict, hierarchy)

        pivot.parent_id = pivot_id_dict[bone.parent.name]
        matrix = bone.parent.matrix.inverted() @ matrix

    if bone.name in pivot_id_dict.keys():
        return

    translation, rotation, _ = matrix.decompose()
    pivot.translation = translation
    pivot.rotation = rotation
    eulers = rotation.to_euler()
    pivot.euler_angles = Vector((eulers.x, eulers.y, eulers.z))

    pivot_id_dict[pivot.name] = len(hierarchy.pivots)
    hierarchy.pivots.append(pivot)

    for child in bone.children:
        process_bone(child, pivot_id_dict, hierarchy)


def process_mesh(context, mesh, hierarchy, pivot_id_dict):
    if not should_export_transform(mesh):
        return
    if mesh.vertex_groups \
            or mesh.data.object_type == 'BOX' \
            or mesh.data.object_type == 'DAZZLE' \
            or mesh.name in pick_plane_names \
            or mesh.name in pivot_id_dict.keys():
        return

    if not mesh.parent_type == 'BONE':
        pivot = HierarchyPivot(name=mesh.name, parent_id=0)
        matrix = mesh.matrix_local

        if mesh.parent is not None and mesh.parent.type == 'MESH':
            if not should_export_transform(mesh.parent):
                # Keep the child in place without reintroducing an excluded helper pivot.
                matrix = mesh.matrix_world
            else:
                context.warning(f'mesh \'{mesh.name}\' did have an object instead of a bone as parent!')
                if mesh.parent.name not in pivot_id_dict.keys():
                    process_mesh(context, mesh.parent, hierarchy, pivot_id_dict)
                    return

                pivot.parent_id = pivot_id_dict[mesh.parent.name]
                matrix = mesh.parent.matrix_local.inverted() @ matrix

        if mesh.name in pivot_id_dict.keys():
            return

        location, rotation, _ = matrix.decompose()
        eulers = rotation.to_euler()

        pivot.translation = location
        pivot.rotation = rotation
        pivot.euler_angles = Vector((eulers.x, eulers.y, eulers.z))

        pivot_id_dict[pivot.name] = len(hierarchy.pivots)
        hierarchy.pivots.append(pivot)

    for child in mesh.children:
        process_mesh(context, child, hierarchy, pivot_id_dict)
