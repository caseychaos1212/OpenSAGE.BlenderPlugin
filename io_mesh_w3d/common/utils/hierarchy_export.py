# <pep8 compliant>
# Written by Stephan Vedder and Michael Schnabel

from mathutils import Vector, Quaternion
from ...export_status import report_export_progress
from ...common.utils.helpers import *
from ...common.structs.hierarchy import *
from ...common.utils.object_settings_bridge import get_hlod_role, should_export_object, should_export_transform


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

        for index, bone in enumerate(rig.pose.bones):
            report_export_progress(context, 'Building bone hierarchy', object_name=bone.name,
                                   current=index, total=len(rig.pose.bones), unit='Bones')
            process_bone(bone, pivot_id_dict, hierarchy)

        switch_to_pose(rig, 'POSE')

    if len(rigs) > 1:
        context.error(f'only one armature per scene allowed! Exporting only the first one: {rigs[0].name}')

    if not terrain_mode:
        meshes = get_objects('MESH')

        for index, mesh in enumerate(meshes):
            report_export_progress(context, 'Building object hierarchy', object_name=mesh.name,
                                   current=index, total=len(meshes), unit='Objects')
            if not should_export_transform(mesh):
                continue
            process_mesh(context, mesh, hierarchy, pivot_id_dict)

    _shorten_proxy_pivot_names(context, hierarchy)
    hierarchy.header.num_pivots = len(hierarchy.pivots)
    return hierarchy, rig


def _shorten_proxy_pivot_names(context, hierarchy):
    """Fit generated proxy pivots in W3D without renaming Blender objects/bones."""
    if context.file_format != 'W3D':
        return
    proxies = {obj.name for obj in get_objects('MESH') if get_hlod_role(obj) == 'PROXY'}
    # Reserve every existing name before assigning new ones. The engine compares
    # bone names without regard to case, and each instance needs its own pivot.
    used_names = {pivot.name.casefold() for pivot in hierarchy.pivots}
    limit = STRING_LENGTH - 1  # Keep the terminating NUL in the 16-byte field.
    for pivot in hierarchy.pivots:
        source_name = getattr(pivot, '_source_object_name', None)
        if source_name not in proxies or len(pivot.name) <= limit:
            continue
        stem = source_name.split('~', 1)[0].strip() or 'proxy'
        name = stem[:limit]
        suffix = 0
        while name.casefold() in used_names:
            suffix += 1
            ending = '_' + str(suffix)
            name = stem[:limit - len(ending)] + ending
        used_names.add(name.casefold())
        pivot.name = name
        context.info(f"Proxy '{source_name}' uses export pivot '{name}'.")


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
        # Export-only identity survives name shortening; HLOD connections must
        # resolve to the original instance rather than its shortened label.
        pivot._source_object_name = mesh.name
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
