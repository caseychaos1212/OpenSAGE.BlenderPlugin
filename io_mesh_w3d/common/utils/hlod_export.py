# <pep8 compliant>
# Written by Stephan Vedder and Michael Schnabel

import bpy

from io_mesh_w3d.common.utils.helpers import *
from io_mesh_w3d.common.structs.hlod import *
from io_mesh_w3d.common.utils.object_settings_bridge import (
    get_hlod_identifier,
    get_hlod_role,
    get_screen_size,
    should_export_geometry,
)


screen_sizes = [MAX_SCREEN_SIZE, 1.0, 0.3, 0.03]


def _find_bone_index(hierarchy, obj):
    if hierarchy is None or not getattr(hierarchy, 'pivots', None):
        return 0

    parent_bone = getattr(obj, 'parent_bone', '')
    for index, pivot in enumerate(hierarchy.pivots):
        if pivot.name == parent_bone or pivot.name == obj.name:
            return index
    return 0


def _create_sub_object(obj, hierarchy, identifier, is_box=False, name=None):
    return HLodSubObject(
        name=identifier if name is None else name,
        identifier=identifier,
        bone_index=_find_bone_index(hierarchy, obj),
        is_box=is_box)


def create_lod_array(meshes, hierarchy, container_name, lod_arrays):
    filtered_meshes = [
        mesh for mesh in meshes
        if should_export_geometry(mesh) and get_hlod_role(mesh) == 'LOD'
    ]
    if not filtered_meshes:
        return lod_arrays

    index = min(len(lod_arrays), len(screen_sizes) - 1)
    sizes = [get_screen_size(mesh, screen_sizes[index]) for mesh in filtered_meshes]
    max_screen = min(sizes) if sizes else screen_sizes[index]

    lod_array = HLodLodArray(
        header=HLodArrayHeader(
            model_count=len(filtered_meshes),
            max_screen_size=max_screen),
        sub_objects=[])

    for mesh in filtered_meshes:
        lod_array.sub_objects.append(_create_sub_object(
            mesh,
            hierarchy,
            container_name + '.' + mesh.name,
            is_box=mesh.data.object_type == 'BOX',
            name=mesh.name))

    lod_arrays.append(lod_array)
    return lod_arrays


def create_attachment_array(role, hierarchy, objects):
    attachments = [
        obj for obj in objects
        if should_export_geometry(obj) and get_hlod_role(obj) == role
    ]
    if not attachments:
        return None

    array_type = HLodAggregateArray if role == 'AGGREGATE' else HLodProxyArray
    array = array_type(
        header=HLodArrayHeader(
            model_count=len(attachments),
            max_screen_size=0.0),
        sub_objects=[])

    for obj in attachments:
        array.sub_objects.append(_create_sub_object(
            obj,
            hierarchy,
            get_hlod_identifier(obj),
            name=get_hlod_identifier(obj)))

    return array


def create_hlod(hierarchy, container_name):
    hlod = HLod(
        header=HLodHeader(
            model_name=container_name,
            hierarchy_name=hierarchy.name()),
        lod_arrays=[])

    meshes = get_objects('MESH', bpy.context.scene.collection.objects)
    lod_arrays = create_lod_array(meshes, hierarchy, container_name, [])

    for coll in bpy.data.collections:
        meshes = get_objects('MESH', coll.objects)
        lod_arrays = create_lod_array(
            meshes, hierarchy, container_name, lod_arrays)

    for lod_array in reversed(lod_arrays):
        hlod.lod_arrays.append(lod_array)
    hlod.aggregate_array = create_attachment_array('AGGREGATE', hierarchy, bpy.context.scene.objects)
    hlod.proxy_array = create_attachment_array('PROXY', hierarchy, bpy.context.scene.objects)
    if not hlod.lod_arrays and (hlod.aggregate_array is not None or hlod.proxy_array is not None):
        hlod.lod_arrays.append(HLodLodArray(
            header=HLodArrayHeader(model_count=0, max_screen_size=MAX_SCREEN_SIZE),
            sub_objects=[]))
    hlod.header.lod_count = len(hlod.lod_arrays)
    return hlod
