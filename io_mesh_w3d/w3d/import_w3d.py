# <pep8 compliant>
# Written by Stephan Vedder and Michael Schnabel

import os

import bpy

from io_mesh_w3d.import_utils import *
from io_mesh_w3d.common.structs.collision_box import *
from io_mesh_w3d.common.structs.data_context import *
from io_mesh_w3d.common.structs.hierarchy import *
from io_mesh_w3d.common.structs.hlod import *
from io_mesh_w3d.common.structs.mesh import *
from io_mesh_w3d.common.structs.mesh_structs.texture import TextureInfo
from io_mesh_w3d.w3d.structs.dazzle import *
from io_mesh_w3d.w3d.structs.compressed_animation import *
from io_mesh_w3d.common.utils.object_settings_bridge import populate_object_settings_from_mesh
from io_mesh_w3d.common.utils.material_settings_bridge import populate_settings_from_material


def load_file(context, data_context, path=None):
    if path is None:
        path = context.filepath

    path = insensitive_path(path)
    context.info(f'Loading file: {path}')

    if not os.path.exists(path):
        context.error(f'file not found: {path}')
        return

    file = open(path, 'rb')
    filesize = os.path.getsize(path)

    while file.tell() < filesize:
        chunk_type, chunk_size, chunk_end = read_chunk_head(file)

        if chunk_type == W3D_CHUNK_MESH:
            data_context.meshes.append(Mesh.read(context, file, chunk_end))
        elif chunk_type == W3D_CHUNK_HIERARCHY:
            if data_context.hierarchy is None:
                data_context.hierarchy = Hierarchy.read(context, file, chunk_end)
            else:
                context.warning('-> already got one hierarchy chunk (skipping this one)!')
                file.seek(chunk_size, 1)
        elif chunk_type == W3D_CHUNK_HLOD:
            if data_context.hlod is None:
                data_context.hlod = HLod.read(context, file, chunk_end)
            else:
                context.warning('-> already got one hlod chunk (skipping this one)!')
                file.seek(chunk_size, 1)
        elif chunk_type == W3D_CHUNK_ANIMATION:
            if data_context.animation is None and data_context.compressed_animation is None:
                data_context.animation = Animation.read(context, file, chunk_end)
            else:
                context.warning('-> already got one animation chunk (skipping this one)!')
                file.seek(chunk_size, 1)
        elif chunk_type == W3D_CHUNK_COMPRESSED_ANIMATION:
            if data_context.animation is None and data_context.compressed_animation is None:
                data_context.compressed_animation = CompressedAnimation.read(context, file, chunk_end)
            else:
                context.warning('-> already got one animation chunk (skipping this one)!')
                file.seek(chunk_size, 1)
        elif chunk_type == W3D_CHUNK_BOX:
            data_context.collision_boxes.append(CollisionBox.read(file))
        elif chunk_type == W3D_CHUNK_DAZZLE:
            data_context.dazzles.append(Dazzle.read(context, file, chunk_end))
        elif chunk_type == W3D_CHUNK_MORPH_ANIMATION:
            context.info('-> morph animation chunk is not supported')
            file.seek(chunk_size, 1)
        elif chunk_type == W3D_CHUNK_HMODEL:
            context.info('-> hmodel chnuk is not supported')
            file.seek(chunk_size, 1)
        elif chunk_type == W3D_CHUNK_LODMODEL:
            context.info('-> lodmodel chunk is not supported')
            file.seek(chunk_size, 1)
        elif chunk_type == W3D_CHUNK_COLLECTION:
            context.info('-> collection chunk not supported')
            file.seek(chunk_size, 1)
        elif chunk_type == W3D_CHUNK_POINTS:
            context.info('-> points chunk is not supported')
            file.seek(chunk_size, 1)
        elif chunk_type == W3D_CHUNK_LIGHT:
            context.info('-> light chunk is not supported')
            file.seek(chunk_size, 1)
        elif chunk_type == W3D_CHUNK_EMITTER:
            context.info('-> emitter chunk is not supported')
            file.seek(chunk_size, 1)
        elif chunk_type == W3D_CHUNK_AGGREGATE:
            context.info('-> aggregate chunk is not supported')
            file.seek(chunk_size, 1)
        elif chunk_type == W3D_CHUNK_NULL_OBJECT:
            context.info('-> null object chunkt is not supported')
            file.seek(chunk_size, 1)
        elif chunk_type == W3D_CHUNK_LIGHTSCAPE:
            context.info('-> lightscape chunk is not supported')
            file.seek(chunk_size, 1)
        elif chunk_type == W3D_CHUNK_SOUNDROBJ:
            context.info('-> soundobj chunk is not supported')
            file.seek(chunk_size, 1)
        else:
            skip_unknown_chunk(context, file, chunk_type, chunk_size)

    file.close()


##########################################################################
# Load
##########################################################################


def load(context):
    data_context = DataContext()

    load_file(context, data_context)
    keep_static = getattr(context, 'keep_rigid_meshes_static', False)

    hierarchy = data_context.hierarchy
    hlod = data_context.hlod
    animation = data_context.animation
    compressed_animation = data_context.compressed_animation

    if hierarchy is None:
        sklpath = None

        if hlod and hlod.header.model_name != hlod.header.hierarchy_name:
            sklpath = os.path.dirname(context.filepath) + os.path.sep + \
                hlod.header.hierarchy_name.lower() + '.w3d'

        # if we load a animation file afterwards and need the hierarchy again
        elif animation and animation.header.name != '':
            sklpath = os.path.dirname(context.filepath) + os.path.sep + \
                animation.header.hierarchy_name.lower() + '.w3d'
        elif compressed_animation and compressed_animation.header.name != '':
            sklpath = os.path.dirname(context.filepath) + os.path.sep + \
                compressed_animation.header.hierarchy_name.lower() + '.w3d'

        if sklpath:
            load_file(context, data_context, sklpath)
            if data_context.hierarchy is None:
                context.error(
                    f'hierarchy file not found: {sklpath}. Make sure it is right next to the file you are importing.')
                return

    create_data(context,
                data_context.meshes,
                data_context.hlod,
                data_context.hierarchy,
                data_context.collision_boxes,
                data_context.animation,
                data_context.compressed_animation,
                data_context.dazzles)
    backfill_w3d_properties(data_context)
    return {'FINISHED'}


##########################################################################
# Unsupported
##########################################################################

W3D_CHUNK_MORPH_ANIMATION = 0x000002C0
W3D_CHUNK_HMODEL = 0x00000300
W3D_CHUNK_LODMODEL = 0x00000400
W3D_CHUNK_COLLECTION = 0x00000420
W3D_CHUNK_POINTS = 0x00000440
W3D_CHUNK_LIGHT = 0x00000460
W3D_CHUNK_EMITTER = 0x00000500
W3D_CHUNK_AGGREGATE = 0x00000600
W3D_CHUNK_NULL_OBJECT = 0x00000750
W3D_CHUNK_LIGHTSCAPE = 0x00000800
W3D_CHUNK_SOUNDROBJ = 0x00000A00
def backfill_w3d_properties(data_context):
    """Populate the new Blender-side property groups using the W3D source data."""
    for mesh_struct in data_context.meshes:
        obj_name = mesh_struct.header.mesh_name or mesh_struct.name()
        if not obj_name:
            continue
        obj = bpy.data.objects.get(obj_name)
        if obj is None:
            continue
        populate_object_settings_from_mesh(obj, mesh_struct)
        populate_material_settings_from_passes(obj, mesh_struct)


ANIM_MODE_FROM_INT = {
    0: 'LOOP',
    1: 'PINGPONG',
    2: 'ONCE',
    3: 'MANUAL',
}


def populate_material_settings_from_passes(obj, mesh_struct):
    materials = list(obj.data.materials) if obj.data else []
    if not materials:
        return

    passes_by_material = {}
    for mat_pass in mesh_struct.material_passes:
        target_idx = None
        if mat_pass.vertex_material_ids:
            target_idx = mat_pass.vertex_material_ids[0]
        elif mat_pass.shader_material_ids:
            target_idx = mat_pass.shader_material_ids[0]
        if target_idx is None:
            continue
        passes_by_material.setdefault(target_idx, []).append(mat_pass)

    for target_idx, passes in passes_by_material.items():
        if target_idx < 0 or target_idx >= len(materials):
            continue
        material = materials[target_idx]
        settings = getattr(material, 'w3d_material_settings', None)
        if settings is None:
            continue

        template = snapshot_pass(settings.passes[0]) if settings.passes else None
        settings.passes.clear()

        for mat_pass in passes:
            pass_prop = settings.passes.add()
            if template:
                apply_pass_template(pass_prop, template)
            populate_stage_from_tx(pass_prop.stage0, mat_pass, 0, mesh_struct)
            populate_stage_from_tx(pass_prop.stage1, mat_pass, 1, mesh_struct)
            pass_prop.name = f'Pass {len(settings.passes)}'

        settings.active_pass_index = 0


def populate_stage_from_tx(stage_prop, mat_pass, stage_index, mesh_struct):
    if stage_index >= len(mat_pass.tx_stages):
        stage_prop.enabled = False
        stage_prop.texture = None
        return

    stage = mat_pass.tx_stages[stage_index]
    tex_struct = resolve_texture_struct(stage, mesh_struct.textures)

    if tex_struct is None:
        stage_prop.enabled = False
        stage_prop.texture = None
        return

    img = find_image_for_texture(tex_struct)
    stage_prop.enabled = img is not None
    stage_prop.texture = img

    info = tex_struct.texture_info or TextureInfo()
    if info.frame_count:
        stage_prop.frames = int(info.frame_count)
    if info.frame_rate:
        stage_prop.fps = info.frame_rate
    stage_prop.animation_mode = ANIM_MODE_FROM_INT.get(int(info.animation_type), stage_prop.animation_mode)


def resolve_texture_struct(stage, textures):
    if not stage.tx_ids:
        return None
    indices = stage.tx_ids[0]
    if not indices:
        return None
    tex_index = indices[0]
    if tex_index < 0 or tex_index >= len(textures):
        return None
    return textures[tex_index]


def find_image_for_texture(tex_struct):
    candidates = [
        tex_struct.id,
        os.path.basename(tex_struct.file),
        tex_struct.file,
    ]
    for name in candidates:
        if not name:
            continue
        img = bpy.data.images.get(name)
        if img:
            return img
    return None


def snapshot_pass(pass_prop):
    if pass_prop is None:
        return None
    return {
        'ambient': tuple(pass_prop.ambient),
        'diffuse': tuple(pass_prop.diffuse),
        'specular': tuple(pass_prop.specular),
        'emissive': tuple(pass_prop.emissive),
        'specular_to_diffuse': pass_prop.specular_to_diffuse,
        'opacity': pass_prop.opacity,
        'translucency': pass_prop.translucency,
        'shininess': pass_prop.shininess,
        'uv0': pass_prop.uv_channel_stage0,
        'uv1': pass_prop.uv_channel_stage1,
    }


def apply_pass_template(target, template):
    if not template:
        return
    target.ambient = template['ambient']
    target.diffuse = template['diffuse']
    target.specular = template['specular']
    target.emissive = template['emissive']
    target.specular_to_diffuse = template['specular_to_diffuse']
    target.opacity = template['opacity']
    target.translucency = template['translucency']
    target.shininess = template['shininess']
    target.uv_channel_stage0 = template['uv0']
    target.uv_channel_stage1 = template['uv1']
