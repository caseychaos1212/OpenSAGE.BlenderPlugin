# <pep8 compliant>
# Written by Stephan Vedder and Michael Schnabel

import bpy
import os
import sys
from mathutils import Quaternion, Matrix, Vector
from bpy_extras.image_utils import load_image
from .animation_compat import iter_animation_data_fcurves


def make_transform_matrix(loc, rot):
    mat_loc = Matrix.Translation(loc)
    mat_rot = Quaternion(rot).normalized().to_matrix().to_4x4()
    return mat_loc @ mat_rot

def get_objects(type, object_list=None):  # MESH, ARMATURE
    if object_list is None:
        object_list = bpy.context.scene.objects
    return [obj for obj in object_list if obj.type == type]


def switch_to_pose(rig, pose):
    if rig is not None:
        rig.data.pose_position = pose
        bpy.context.view_layer.update()


def iter_action_fcurves(animation_data):
    # Keep upstream's entry point while sharing the fork's action-slot handling.
    yield from iter_animation_data_fcurves(animation_data)


# 'Material.blend_method' is deprecated since Blender 4.2 and has no effect in EEVEE Next,
# which uses 'Material.surface_render_method' instead
SURFACE_RENDER_METHODS = {
    'OPAQUE': 'DITHERED',
    'CLIP': 'DITHERED',
    'HASHED': 'DITHERED',
    'BLEND': 'BLENDED'}


def set_blend_method(material, blend_method):
    if bpy.app.version < (4, 2, 0):
        material.blend_method = blend_method
        return
    material.surface_render_method = SURFACE_RENDER_METHODS[blend_method]


def uses_nodes(material):
    if bpy.app.version >= (5, 0, 0):
        return material.node_tree is not None
    return material.use_nodes


def enable_nodes(material):
    # 'Material.use_nodes' is deprecated and gets removed in Blender 6.0,
    # since Blender 5.0 materials always come with a node tree
    if not uses_nodes(material):
        material.use_nodes = True


def set_transparency_overlap(material, value):
    # 'Material.show_transparent_back' is deprecated since Blender 4.2
    if bpy.app.version < (4, 2, 0):
        material.show_transparent_back = value
        return
    material.use_transparency_overlap = value


def new_vertex_color_layer(mesh, name):
    # 'Mesh.vertex_colors' is deprecated since Blender 3.2 in favour of color attributes
    if bpy.app.version < (3, 2, 0):
        return mesh.vertex_colors.new(name=name)
    return mesh.color_attributes.new(name=name, type='BYTE_COLOR', domain='CORNER')


def get_vertex_color_layers(mesh):
    if bpy.app.version < (3, 2, 0):
        return list(mesh.vertex_colors)
    return [attribute for attribute in mesh.color_attributes if attribute.domain == 'CORNER']


def set_uv(uv_layer, index, value):
    # 'MeshUVLoopLayer.data' is deprecated since Blender 3.5 in favour of the 'uv' attribute
    if bpy.app.version < (3, 5, 0):
        uv_layer.data[index].uv = value
        return
    uv_layer.uv[index].vector = value


def get_uv(uv_layer, index):
    if bpy.app.version < (3, 5, 0):
        return uv_layer.data[index].uv
    return uv_layer.uv[index].vector


def get_uv_count(uv_layer):
    if bpy.app.version < (3, 5, 0):
        return len(uv_layer.data)
    return len(uv_layer.uv)


def insensitive_path(path):
    # find the io_stream on unix
    directory = os.path.dirname(path)
    name = os.path.basename(path)

    for io_stream_name in os.listdir(directory):
        if io_stream_name.lower() == name.lower():
            path = os.path.join(directory, io_stream_name)
    return path


def get_collection(hlod=None, index=''):
    if hlod is not None:
        name = hlod.model_name() + index
        if name in bpy.data.collections:
            return bpy.data.collections[name]
        coll = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(coll)
        return coll
    return bpy.context.scene.collection


def link_object_to_active_scene(obj, coll):
    coll.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)


def rig_object(obj, hierarchy, rig, sub_object):
    obj.parent = rig
    obj.parent_type = 'OBJECT'
    if rig is None or hierarchy is None or sub_object is None:
        return
    if not 0 <= sub_object.bone_index < len(hierarchy.pivots):
        return

    pivot = hierarchy.pivots[sub_object.bone_index]
    if pivot.name in rig.data.bones:
        obj.parent_bone = pivot.name
        obj.parent_type = 'BONE'
        # Blender parents to the bone tip; file attachments use the pivot origin.
        obj.matrix_parent_inverse = Matrix.Translation((0, -rig.data.bones[pivot.name].length, 0))


def create_uvlayer(context, mesh, b_mesh, tris, mat_pass):
    tx_coords = None
    if mat_pass.tx_coords:
        tx_coords = mat_pass.tx_coords
    else:
        if mat_pass.tx_stages:
            if len(mat_pass.tx_stages[0].tx_coords) == 0:
                context.warning('texture stage did not have texture coordinates!')
                return
            tx_coords = mat_pass.tx_stages[0].tx_coords[0]
            if len(mat_pass.tx_stages[0].tx_coords) > 1:
                context.warning('only one set of texture coordinates per texture stage supported')
        if len(mat_pass.tx_stages) > 1:
            context.warning('only one texture stage per material pass supported')

    if tx_coords is None:
        if mesh is not None:
            uv_layer = mesh.uv_layers.new(do_init=False)
        return

    uv_layer = mesh.uv_layers.new(do_init=False)
    for i, face in enumerate(b_mesh.faces):
        for loop in face.loops:
            idx = tris[i][loop.index % 3]
            set_uv(uv_layer, loop.index, tx_coords[idx].xy)


def create_uvlayer_2(context, mesh, b_mesh, tris, mat_pass):
    tx_coords_2 = None
    if mat_pass.tx_coords_2:
        tx_coords_2 = mat_pass.tx_coords_2
    else:
        uv_layer = mesh.uv_layers.new(do_init=False)
        return

    uv_layer = mesh.uv_layers.new(do_init=False)
    for i, face in enumerate(b_mesh.faces):
        for loop in face.loops:
            idx = tris[i][loop.index % 3]
            set_uv(uv_layer, loop.index, tx_coords_2[idx].xy)


extensions = ['.dds', '.tga', '.jpg', '.jpeg', '.png', '.bmp']


def find_texture(context, file, name=None):
    file = file.rsplit('.', 1)[0]
    if name is None:
        name = file
    else:
        name = name.rsplit('.', 1)[0]

    for extension in extensions:
        combined = name + extension
        if combined in bpy.data.images:
            return bpy.data.images[combined]

    path = insensitive_path(os.path.dirname(context.filepath))
    filepath = path + os.path.sep + file

    img = None
    for extension in extensions:
        img = load_image(filepath + extension, check_existing=True)
        if img is not None:
            context.info('loaded texture: ' + filepath + extension)
            img.name = file
            break

    if img is None:
        context.warning(
            f'texture not found: {filepath} {extensions}. Make sure it is right next to the file you are importing!')
        img = bpy.data.images.new(name, width=2048, height=2048)
        img.generated_type = 'COLOR_GRID'
        img.source = 'GENERATED'
        img.name = name + extensions[0]

    img.alpha_mode = 'STRAIGHT'
    return img


def get_aa_box(vertices):
    minX = sys.float_info.max
    maxX = sys.float_info.min

    minY = sys.float_info.max
    maxY = sys.float_info.min

    minZ = sys.float_info.max
    maxZ = sys.float_info.min

    for vertex in vertices:
        minX = min(vertex.co.x, minX)
        maxX = max(vertex.co.x, maxX)

        minY = min(vertex.co.y, minY)
        maxY = max(vertex.co.y, maxY)

        minZ = min(vertex.co.z, minZ)
        maxZ = max(vertex.co.z, maxZ)

    return Vector((maxX - minX, maxY - minY, maxZ - minZ))
