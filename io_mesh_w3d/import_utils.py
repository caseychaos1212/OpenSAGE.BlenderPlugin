# <pep8 compliant>
# Written by Stephan Vedder and Michael Schnabel

import bpy

from io_mesh_w3d.common.utils.mesh_import import *
from io_mesh_w3d.common.utils.hierarchy_import import *
from io_mesh_w3d.common.utils.animation_import import *
from io_mesh_w3d.common.utils.box_import import *
from io_mesh_w3d.w3d.utils.dazzle_import import *


def create_data(context, meshes, hlod=None, hierarchy=None, boxes=None, animation=None, compressed_animation=None,
                dazzles=None):
    boxes = boxes if boxes is not None else []
    dazzles = dazzles if dazzles is not None else []
    collection = get_collection(hlod)
    freeze_rigid = getattr(context, 'keep_rigid_meshes_static', False)
    reused_rigid_meshes = set()

    def _reuse_rigid_mesh(obj):
        if obj is None:
            return None
        mat = obj.matrix_world.copy()
        obj.parent = None
        obj.matrix_world = mat
        return mat

    def _find_rigid_object(name):
        obj = bpy.data.objects.get(name)
        if obj is None and '.' in name:
            suffix = name.split('.')[-1]
            obj = bpy.data.objects.get(suffix)
        return obj

    mesh_names_map = {}
    reused_rigid_mats = {}
    if hlod is not None:
        current_coll = collection
        for i, lod_array in enumerate(reversed(hlod.lod_arrays)):
            if i > 0:
                current_coll = get_collection(hlod, '.' + str(i))
                current_coll.hide_viewport = True

            for sub_object in lod_array.sub_objects:
                for mesh in meshes:
                    if mesh.name() == sub_object.name:
                        if freeze_rigid and (not mesh.is_skin()):
                            existing_obj = _find_rigid_object(sub_object.name)
                            if existing_obj is not None:
                                reused_rigid_mats[existing_obj.name] = _reuse_rigid_mesh(existing_obj)
                                mesh.header.mesh_name = existing_obj.name
                                mesh_names_map[mesh.name()] = existing_obj.name
                                reused_rigid_meshes.add(existing_obj.name)
                                context.info(f"reusing existing rigid mesh '{existing_obj.name}'")
                                continue
                        newname = create_mesh(context, mesh, current_coll, hierarchy, sub_object)
                        mesh_names_map[mesh.name()] = newname

                for box in boxes:
                    if box.name() == sub_object.name:
                        create_box(box, collection)

                for dazzle in dazzles:
                    if dazzle.name() == sub_object.name:
                        create_dazzle(context, dazzle, collection)

    rig = get_or_create_skeleton(hierarchy, collection)

    if hlod is not None:
        for lod_array in reversed(hlod.lod_arrays):
            for sub_object in lod_array.sub_objects:
                for mesh in meshes:
                    if mesh.name() == sub_object.name:
                        mesh.header.mesh_name = mesh_names_map[mesh.name()]
                        if freeze_rigid and (not mesh.is_skin()) and mesh.header.mesh_name in reused_rigid_meshes:
                            obj = bpy.data.objects.get(mesh.header.mesh_name)
                            if obj is not None:
                                world_mat = reused_rigid_mats.get(obj.name, obj.matrix_world.copy())
                                rig_object(obj, hierarchy, rig, sub_object)
                                obj.matrix_world = world_mat
                            continue
                        rig_mesh(mesh, hierarchy, rig, sub_object)
                for box in boxes:
                    if box.name() == sub_object.name:
                        rig_box(box, hierarchy, rig, sub_object)
                for dazzle in dazzles:
                    if dazzle.name() == sub_object.name:
                        dazzle_object = bpy.data.objects[dazzle.name()]
                        rig_object(dazzle_object, hierarchy, rig, sub_object)

    else:
        for mesh in meshes:
            if freeze_rigid and (not mesh.is_skin()):
                existing_obj = _find_rigid_object(mesh.name())
                if existing_obj is not None:
                    reused_rigid_mats[existing_obj.name] = _reuse_rigid_mesh(existing_obj)
                    mesh.header.mesh_name = existing_obj.name
                    reused_rigid_meshes.add(existing_obj.name)
                    context.info(f"reusing existing rigid mesh '{existing_obj.name}'")
                    continue
            create_mesh(context, mesh, collection, hierarchy)

    create_animation(context, rig, animation, hierarchy)
    create_animation(context, rig, compressed_animation, hierarchy)
