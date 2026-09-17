# <pep8 compliant>
# Written by Stephan Vedder and Michael Schnabel

from ..import_utils import *
from ..common.structs.animation import *
from ..common.structs.collision_box import *
from ..common.structs.data_context import *
from ..common.structs.hierarchy import *
from ..common.structs.hlod import *
from ..common.structs.mesh import *
from ..common.structs.mesh_structs.texture import *
from ..w3x.structs.include import *
from ..common.utils.hierarchy_export import *
from ..common.utils.hlod_export import *


def record_loaded_file(context, path):
    loaded_files = getattr(context, '_w3d_loaded_files', None)
    if loaded_files is None:
        return
    if path not in loaded_files:
        loaded_files.append(path)


def load_file(context, data_context, path=None):
    if path is None:
        path = context.filepath

    path = os.path.abspath(path)
    path_key = os.path.normcase(path)
    loaded_paths = getattr(data_context, '_w3x_loaded_paths', None)
    if loaded_paths is None:
        loaded_paths = set()
        if data_context is not None:
            data_context._w3x_loaded_paths = loaded_paths
    if path_key in loaded_paths:
        return True

    record_loaded_file(context, path)
    context.info(f'Loading file: {path}')

    if not os.path.exists(path):
        context.error(f'file not found: {path}')
        return False

    root = find_root(context, path)
    if root is None:
        return False
    # Mark before descending so shared includes and cycles are processed once.
    loaded_paths.add(path_key)

    directory = os.path.dirname(path)
    for node in root:
        if node.tag == 'Includes':
            for xml_include in node:
                include = Include.parse(xml_include)
                source = include.source.replace('ART:', '')
                load_file(context, data_context, os.path.join(directory, source))

        elif node.tag == 'W3DMesh':
            mesh = Mesh.parse(context, node)
            mesh._w3x_source = path_key
            data_context.meshes.append(mesh)
        elif node.tag == 'W3DCollisionBox':
            data_context.collision_boxes.append(CollisionBox.parse(context, node))
        elif node.tag == 'W3DContainer':
            data_context.hlod = HLod.parse(context, node)
        elif node.tag == 'W3DHierarchy':
            data_context.hierarchy = Hierarchy.parse(context, node)
        elif node.tag == 'W3DAnimation':
            data_context.animation = Animation.parse(context, node)
        elif node.tag == 'Texture':
            data_context.textures.append(Texture.parse(node))
        else:
            context.warning('unsupported node ' + node.tag + ' in file: ' + path)
    return True


##########################################################################
# Load
##########################################################################

skl_find_hint = ['', '_HRC', '_SKL']
ctr_find_hint = ['', '_CTR']


def load(context):
    data_context = DataContext(
        meshes=[],
        textures=[],
        collision_boxes=[],
        hierarchy=None,
        hlod=None)

    if not load_file(context, data_context):
        return {'CANCELLED'}

    directory = os.path.dirname(context.filepath) + os.path.sep

    # if loaded w3d container, check if all it's meshes/collision_boxes are loaded
    if data_context.hlod:
        # get number of meshes and collision_boxes registered in the container
        objidentifiers = []
        for array in data_context.hlod.lod_arrays:
            for obj in array.sub_objects:
                if obj.identifier not in objidentifiers:
                    objidentifiers.append(obj.identifier)

        if len(objidentifiers) != len(data_context.meshes) + len(data_context.collision_boxes):
            context.info('Looking for additional mesh files..')
            for array in data_context.hlod.lod_arrays:
                for obj in array.sub_objects:
                    path = directory + obj.identifier + '.w3x'
                    if os.path.exists(path):
                        load_file(context, data_context, path)

        if len(objidentifiers) > len(data_context.meshes) + len(data_context.collision_boxes):
            context.warning('Not all meshes loaded!')

    # if loaded only meshes/collision boxes, we need to find the w3d container
    if data_context.hlod is None and (len(data_context.meshes) == 1 or len(data_context.collision_boxes) == 1):
        container_name = ""
        if len(data_context.meshes) == 1:
            container_name = data_context.meshes[0].container_name()
        else:
            container_name = data_context.collision_boxes[0].container_name()

        context.info('Looking for the container file..')
        ctr_paths_try = []
        for hint in ctr_find_hint:
            ctr_path = directory + container_name + hint + '.w3x'
            if os.path.exists(ctr_path) and ctr_path != context.filepath:
                ctr_paths_try.append(ctr_path)

        for ctr_path in ctr_paths_try:
            context.info(ctr_path)
            if load_file(context, data_context, ctr_path):
                if data_context.hlod:
                    break

    # if not loaded w3d hierarchy, we need to find it
    if data_context.hierarchy is None:
        context.info('Looking for the hierarcy file..')
        skl_paths_try = []
        if data_context.hlod:
            for hint in skl_find_hint:
                skl_path = directory + data_context.hlod.hierarchy_name() + hint + '.w3x'
                if skl_path not in skl_paths_try and os.path.exists(skl_path) and skl_path != context.filepath:
                    skl_paths_try.append(skl_path)
        if data_context.animation:
            for hint in skl_find_hint:
                skl_path = directory + data_context.animation.header.hierarchy_name + hint + '.w3x'
                if skl_path not in skl_paths_try and os.path.exists(skl_path) and skl_path != context.filepath:
                    skl_paths_try.append(skl_path)

        for skl_path in skl_paths_try:
            context.info(skl_path)
            if load_file(context, data_context, skl_path):
                if data_context.hierarchy:
                    break

    # must load hierarchy file if animation is loaded.
    if data_context.animation and data_context.hierarchy is None:
        # check if we already have the container and hierarchy in blener
        rigs = get_objects('ARMATURE')
        if len(rigs) > 0:
            hierarchy, _ = retrieve_hierarchy(context, "")
            if hierarchy.header.name == data_context.animation.header.hierarchy_name:
                data_context.hierarchy = hierarchy
            else:
                context.error(
                    f'Hierarchy not found: {data_context.animation.header.hierarchy_name}. Make sure it is in the current scene')
                return {'CANCELLED'}
        else:
            context.error(
                f'Hierarchy file not found: {data_context.animation.header.hierarchy_name}. Make sure it is right next to the file you are importing.')
            return {'CANCELLED'}

    # issue warning if single mesh is loaded without any container
    if data_context.hlod is None and (len(data_context.meshes) == 1 or len(data_context.collision_boxes) == 1):
        context.warning('Loaded only single mesh! This may cause problems to export the scene.')

    # Animation/container includes may reference a model already in the scene.
    # Reuse only dependencies with the same source file and asset identifier;
    # explicitly importing a model again still creates a separate copy.
    entry_path = os.path.normcase(os.path.abspath(context.filepath))
    existing_meshes = {(obj.get('_w3x_source'), obj.get('_w3x_id'))
                       for obj in bpy.context.scene.objects if obj.type == 'MESH'}
    meshes = [mesh for mesh in data_context.meshes
              if mesh._w3x_source == entry_path
              or (mesh._w3x_source, mesh.name()) not in existing_meshes]
    hierarchy = data_context.hierarchy
    boxes = data_context.collision_boxes
    hlod = data_context.hlod
    animation = data_context.animation

    import_state = create_data(context, meshes, hlod, hierarchy, boxes, animation) or {}
    import_state['source_path'] = context.filepath
    import_state['loaded_files'] = list(getattr(context, '_w3d_loaded_files', []) or [])
    context._w3d_import_state = import_state
    context.info("Finished!")
    return {'FINISHED'}
