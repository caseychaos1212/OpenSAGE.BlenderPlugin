# <pep8 compliant>
# Written by Stephan Vedder and Michael Schnabel

import bpy
from bpy_extras import node_shader_utils

from ...common.utils.helpers import *
from ...w3d.structs.mesh_structs.vertex_material import *
from ...common.utils.material_settings_bridge import populate_settings_from_material, apply_pass_to_material


##########################################################################
# vertex material
##########################################################################

def _material_id(ids, index, default=0):
    # W3D stores either one ID for the whole mesh or an ID array.
    return ids[index] if len(ids) > 1 and index < len(ids) else ids[0] if ids else default


def _populate_imported_pass(config, vertex_material, shader):
    info = vertex_material.vm_info
    config.name = vertex_material.vm_name
    config['_w3d_vertex_material_name'] = vertex_material.vm_name
    config.ambient = info.ambient.to_vector_rgba()
    config.diffuse = info.diffuse.to_vector_rgba()
    config.specular = info.specular.to_vector_rgb()
    config.emissive = info.emissive.to_vector_rgb()
    config.opacity = info.opacity
    config.shininess = info.shininess
    config.translucency = info.translucency
    config.specular_to_diffuse = bool(info.attributes & COPY_SPECULAR_TO_DIFFUSE)
    config.stage0_mapping = '0x%08X' % (info.attributes & STAGE0_MAPPING_MASK)
    config.stage1_mapping = '0x%08X' % (info.attributes & STAGE1_MAPPING_MASK)
    config.stage0_args = vertex_material.vm_args_0.replace('\r\n', ', ')
    config.stage1_args = vertex_material.vm_args_1.replace('\r\n', ', ')
    target = config.shader
    target.custom_src = str(shader.src_blend)
    target.custom_dest = str(shader.dest_blend)
    target.write_z = bool(shader.depth_mask)
    target.alpha_test = bool(shader.alpha_test)
    target.depth_compare = str(shader.depth_compare)
    target.pri_gradient = str(shader.pri_gradient)
    target.sec_gradient = str(shader.sec_gradient)
    target.detail_color = str(shader.detail_color_func)
    target.detail_alpha = str(shader.detail_alpha_func)
    # These legacy shader fields do not have per-pass UI controls.
    config['_w3d_shader_extra'] = {key: getattr(shader, key) for key in (
        'color_mask', 'fog_func', 'shader_preset', 'post_detail_color_func',
        'post_detail_alpha_func')}


def _populate_imported_stage(context, config, texture):
    config.enabled = True
    config.texture = find_texture(context, texture.file, texture.id)
    info = texture.texture_info
    if info is not None:
        config.frames = info.frame_count
        config.fps = info.frame_rate
        config.animation_mode = {0: 'LOOP', 1: 'PINGPONG', 2: 'ONCE', 3: 'MANUAL'}.get(
            info.animation_type, 'LOOP')
        config.publish = bool(info.attributes & 0x01)
        config.no_lod = bool(info.attributes & 0x04)
        config.clamp_u = bool(info.attributes & 0x08)
        config.clamp_v = bool(info.attributes & 0x10)


def _create_pass_preview(material, mesh):
    # Approximate common terrain detail/alpha passes. Keep every texture node
    # available even for engine-specific mapping modes Blender cannot reproduce.
    tree = material.node_tree
    base_color = base_alpha = None
    for pass_index, config in enumerate(material.w3d_material_settings.passes):
        textures = []
        for stage_index in range(2):
            stage = getattr(config, f'stage{stage_index}')
            if not stage.enabled or stage.texture is None:
                textures.append(None)
                continue
            node = tree.nodes.new('ShaderNodeTexImage')
            node.image = stage.texture
            node.label = f'Pass {pass_index + 1}, Stage {stage_index}'
            node.location = (-900, -pass_index * 600 - stage_index * 260)
            channel = getattr(config, f'uv_channel_stage{stage_index}') - 1
            if channel < len(mesh.uv_layers):
                uv = tree.nodes.new('ShaderNodeUVMap')
                uv.uv_map = mesh.uv_layers[channel].name
                uv.location = (-1150, node.location.y)
                tree.links.new(uv.outputs['UV'], node.inputs['Vector'])
            textures.append(node)
        if textures[0] is None:
            continue
        color = textures[0].outputs['Color']
        alpha = textures[0].outputs['Alpha']
        detail = textures[1]
        if detail is not None:
            if config.shader.detail_color == '1':
                color = detail.outputs['Color']
            elif config.shader.detail_color in ('2', '3', '4', '5'):
                mix = tree.nodes.new('ShaderNodeMixRGB')
                mix.blend_type = {'2': 'MULTIPLY', '3': 'SCREEN', '4': 'ADD', '5': 'SUBTRACT'}[
                    config.shader.detail_color]
                mix.inputs[0].default_value = 1.0
                mix.location = (-550, -pass_index * 600)
                tree.links.new(color, mix.inputs[1])
                tree.links.new(detail.outputs['Color'], mix.inputs[2])
                color = mix.outputs[0]
            if config.shader.detail_alpha == '1':
                alpha = detail.outputs['Alpha']
            elif config.shader.detail_alpha == '2':
                multiply = tree.nodes.new('ShaderNodeMath')
                multiply.operation = 'MULTIPLY'
                multiply.location = (-550, -pass_index * 600 - 180)
                tree.links.new(alpha, multiply.inputs[0])
                tree.links.new(detail.outputs['Alpha'], multiply.inputs[1])
                alpha = multiply.outputs[0]
        if base_color is None:
            base_color, base_alpha = color, alpha
        elif config.shader.custom_src == '2' and config.shader.custom_dest == '5':
            mix = tree.nodes.new('ShaderNodeMixRGB')
            mix.location = (-250, -pass_index * 250)
            tree.links.new(alpha, mix.inputs[0])
            tree.links.new(base_color, mix.inputs[1])
            tree.links.new(color, mix.inputs[2])
            base_color = mix.outputs[0]
    bsdf = tree.nodes.get('Principled BSDF')
    if base_color is not None:
        tree.links.new(base_color, bsdf.inputs['Base Color'])
        first = material.w3d_material_settings.passes[0]
        if first.shader.alpha_test or first.shader.custom_src == '2':
            tree.links.new(base_alpha, bsdf.inputs['Alpha'])


def create_vertex_material(context, principleds, structure, mesh, b_mesh, name, triangles, mesh_ob):
    from ...w3d.structs.mesh_structs.shader import Shader

    uv_channels = []
    for mat_pass in structure.material_passes:
        channels = []
        for stage_index in range(max(1, len(mat_pass.tx_stages))):
            layer = create_uvlayer(context, mesh, b_mesh, triangles, mat_pass, stage_index)
            channels.append(list(mesh.uv_layers).index(layer) + 1 if layer is not None else 1)
        uv_channels.append(channels)

    # A Blender slot represents the complete pass stack for a face, not a
    # texture-table index. Two stages in one pass are not two face materials.
    slots = {}
    warned_vertex_ids = False
    for face_index, polygon in enumerate(mesh.polygons):
        selections = []
        for mat_pass in structure.material_passes:
            vertex_ids = {_material_id(mat_pass.vertex_material_ids, v) for v in polygon.vertices}
            if len(vertex_ids) > 1 and not warned_vertex_ids:
                context.warning(f"mesh '{name}' has different vertex materials within a face; "
                                'using the first vertex material for that face')
                warned_vertex_ids = True
            selections.append((
                _material_id(mat_pass.vertex_material_ids, polygon.vertices[0]),
                _material_id(mat_pass.shader_ids, face_index),
                tuple(_material_id(stage.tx_ids[0] if stage.tx_ids else [], face_index, -1)
                      for stage in mat_pass.tx_stages)))
        key = tuple(selections)
        if key not in slots:
            slot = len(slots)
            first_id = selections[0][0] if selections else 0
            first_id = first_id if 0 <= first_id < len(structure.vert_materials) else 0
            vertex_material = structure.vert_materials[first_id]
            material_name = name if slot == 0 else f'{name}_{slot}'
            material, principled = create_material_from_vertex_material(material_name, vertex_material)
            settings = material.w3d_material_settings
            settings.passes.clear()
            for pass_index, (vertex_id, shader_id, texture_ids) in enumerate(selections):
                if not 0 <= vertex_id < len(structure.vert_materials):
                    context.warning(f"mesh '{name}' references invalid vertex material {vertex_id}; using 0")
                    vertex_id = 0
                shader = structure.shaders[shader_id] if 0 <= shader_id < len(structure.shaders) else Shader()
                config = settings.passes.add()
                _populate_imported_pass(config, structure.vert_materials[vertex_id], shader)
                if pass_index == 0:
                    set_shader_properties(material, shader)
                for stage_index in range(2):
                    stage_config = getattr(config, f'stage{stage_index}')
                    stage_config.enabled = False
                    if stage_index >= len(texture_ids):
                        continue
                    setattr(config, f'uv_channel_stage{stage_index}', uv_channels[pass_index][stage_index])
                    texture_id = texture_ids[stage_index]
                    if texture_id in (-1, 0xFFFFFFFF):
                        continue
                    if not 0 <= texture_id < len(structure.textures):
                        context.warning(f"mesh '{name}' references invalid texture {texture_id}; skipping texture")
                        continue
                    _populate_imported_stage(context, stage_config, structure.textures[texture_id])
                    stage_config['_w3d_texture_id'] = texture_id
                if len(texture_ids) > 2:
                    context.warning(f"mesh '{name}' has more than two texture stages; importing the first two")
            settings.active_pass_index = 0
            if settings.passes:
                apply_pass_to_material(material, settings, settings.passes[0])
            _create_pass_preview(material, mesh)
            set_blend_method(material, 'CLIP')
            mesh.materials.append(material)
            principleds.append(principled)
            slots[key] = slot
        polygon.material_index = slots[key]


def create_material_from_vertex_material(name, vert_mat):
    name = name + "." + vert_mat.vm_name
    if name in bpy.data.materials:
        material = bpy.data.materials[name]
        principled = node_shader_utils.PrincipledBSDFWrapper(material, is_readonly=False)
        return material, principled

    material = bpy.data.materials.new(name)
    material.material_type = 'VERTEX_MATERIAL'
    enable_nodes(material)
    set_transparency_overlap(material, False)

    attributes = {'DEFAULT'}
    attribs = vert_mat.vm_info.attributes
    if attribs & USE_DEPTH_CUE:
        attributes.add('USE_DEPTH_CUE')
    if attribs & ARGB_EMISSIVE_ONLY:
        attributes.add('ARGB_EMISSIVE_ONLY')
    if attribs & COPY_SPECULAR_TO_DIFFUSE:
        attributes.add('COPY_SPECULAR_TO_DIFFUSE')
    if attribs & DEPTH_CUE_TO_ALPHA:
        attributes.add('DEPTH_CUE_TO_ALPHA')

    principled = node_shader_utils.PrincipledBSDFWrapper(material, is_readonly=False)
    principled.base_color = vert_mat.vm_info.diffuse.to_vector_rgb()
    principled.alpha = vert_mat.vm_info.opacity
    principled.specular = vert_mat.vm_info.shininess
    principled.emission_color = vert_mat.vm_info.emissive.to_vector_rgb()

    material.attributes = attributes
    material.specular = vert_mat.vm_info.specular.to_vector_rgb()
    material.ambient = vert_mat.vm_info.ambient.to_vector_rgba()
    material.translucency = vert_mat.vm_info.translucency

    material.stage0_mapping = '0x%08X' % (attribs & STAGE0_MAPPING_MASK)
    material.stage1_mapping = '0x%08X' % (attribs & STAGE1_MAPPING_MASK)

    material.vm_args_0 = vert_mat.vm_args_0.replace('\r\n', ', ')
    material.vm_args_1 = vert_mat.vm_args_1.replace('\r\n', ', ')

    populate_settings_from_material(material)
    # Textures are connected after this helper returns. Leave a new stage
    # unconfigured so legacy node textures remain available on export.
    settings = material.w3d_material_settings
    settings.passes[0].stage0.property_unset('enabled')
    settings.passes[0].stage1.property_unset('enabled')
    return material, principled


##########################################################################
# shader material
##########################################################################

def create_material_from_shader_material(context, name, shader_mat):
    name = name + '.' + shader_mat.header.type_name
    if name in bpy.data.materials:
        material = bpy.data.materials[name]
        principled = node_shader_utils.PrincipledBSDFWrapper(material, is_readonly=False)
        return material, principled

    material = bpy.data.materials.new(name)
    material.material_type = 'SHADER_MATERIAL'
    enable_nodes(material)
    set_transparency_overlap(material, False)

    material.technique = shader_mat.header.technique

    principled = node_shader_utils.PrincipledBSDFWrapper(material, is_readonly=False)

    for prop in shader_mat.properties:
        if prop.name == 'DiffuseTexture' and prop.value != '':
            principled.base_color_texture.image = find_texture(context, prop.value)
            principled.base_color_texture.image.name = prop.value
        elif prop.name == 'NormalMap' and prop.value != '':
            principled.normalmap_texture.image = find_texture(context, prop.value)
            principled.normalmap_texture.image.name = prop.value
        elif prop.name == 'BumpScale':
            principled.normalmap_strength = prop.value
        elif prop.name == 'SpecMap' and prop.value != '':
            principled.specular_texture.image = find_texture(context, prop.value)
            principled.specular_texture.image.name = prop.value
        elif prop.name == 'SpecularExponent' or prop.name == 'Shininess':
            material.specular_intensity = prop.value / 200.0
        elif prop.name == 'DiffuseColor' or prop.name == 'ColorDiffuse':
            material.diffuse_color = prop.to_rgba()
        elif prop.name == 'SpecularColor' or prop.name == 'ColorSpecular':
            material.specular_color = prop.to_rgb()
        elif prop.name == 'CullingEnable':
            material.use_backface_culling = prop.value
        elif prop.name == 'Texture_0':
            principled.base_color_texture.image = find_texture(context, prop.value)
            principled.base_color_texture.image.name = prop.value

        # all props below have no effect on shading -> custom properties for roundtrip purpose
        elif prop.name == 'AmbientColor' or prop.name == 'ColorAmbient':
            material.ambient = prop.to_rgba()
        elif prop.name == 'EmissiveColor' or prop.name == 'ColorEmissive':
            principled.emission_color = prop.to_rgb()
        elif prop.name == 'Opacity':
            principled.alpha = prop.value
        elif prop.name == 'AlphaTestEnable':
            material.alpha_test = prop.value
        elif prop.name == 'BlendMode':  # is blend_method ?
            material.blend_mode = prop.value
        elif prop.name == 'BumpUVScale':
            material.bump_uv_scale = prop.value.xy
        elif prop.name == 'EdgeFadeOut':
            material.edge_fade_out = prop.value
            material['_w3d_edge_fade_type'] = prop.type
        elif prop.name == 'DepthWriteEnable':
            material.depth_write = prop.value
        elif prop.name == 'Sampler_ClampU_ClampV_NoMip_0':
            material.sampler_clamp_uv_no_mip_0 = prop.value
        elif prop.name == 'Sampler_ClampU_ClampV_NoMip_1':
            material.sampler_clamp_uv_no_mip_1 = prop.value
        elif prop.name == 'NumTextures':
            material.num_textures = prop.value  # is 1 if texture_0 and texture_1 are set
        elif prop.name == 'Texture_1':  # second diffuse texture
            # find texture just load the texture in blender
            # multiple diffuse textures still need to be switched by hand by the user
            find_texture(context, prop.value)
            material.texture_1 = prop.value
        elif prop.name == 'DamagedTexture':
            find_texture(context, prop.value)
            material.damaged_texture = prop.value
        elif prop.name == 'SecondaryTextureBlendMode':
            material.secondary_texture_blend_mode = prop.value
        elif prop.name == 'TexCoordMapper_0':
            material.tex_coord_mapper_0 = prop.value
        elif prop.name == 'TexCoordMapper_1':
            material.tex_coord_mapper_1 = prop.value
        elif prop.name == 'TexCoordTransform_0':
            material.tex_coord_transform_0 = prop.value
        elif prop.name == 'TexCoordTransform_1':
            material.tex_coord_transform_1 = prop.value
        elif prop.name == 'EnvironmentTexture':
            material.environment_texture = prop.value
        elif prop.name == 'EnvMult':
            material.environment_mult = prop.value
        elif prop.name == 'RecolorTexture':
            material.recolor_texture = prop.value
        elif prop.name == 'RecolorMultiplier':
            material.recolor_mult = prop.value
        elif prop.name == 'UseRecolorColors':
            material.use_recolor = prop.value
        elif prop.name == 'HouseColorPulse':
            material.house_color_pulse = prop.value
        elif prop.name == 'ScrollingMaskTexture':
            material.scrolling_mask_texture = prop.value
        elif prop.name == 'TexCoordTransformAngle_0':
            material.tex_coord_transform_angle = prop.value
        elif prop.name == 'TexCoordTransformU_0':
            material.tex_coord_transform_u_0 = prop.value
        elif prop.name == 'TexCoordTransformV_0':
            material.tex_coord_transform_v_0 = prop.value
        elif prop.name == 'TexCoordTransformU_1':
            material.tex_coord_transform_u_1 = prop.value
        elif prop.name == 'TexCoordTransformV_1':
            material.tex_coord_transform_v_1 = prop.value
        elif prop.name == 'TexCoordTransformU_2':
            material.tex_coord_transform_u_2 = prop.value
        elif prop.name == 'TexCoordTransformV_2':
            material.tex_coord_transform_v_2 = prop.value
        elif prop.name == 'TextureAnimation_FPS_NumPerRow_LastFrame_FrameOffset_0':
            material.tex_ani_fps_NPR_lastFrame_frameOffset_0 = prop.value
        elif prop.name == 'IonHullTexture':
            material.ion_hull_texture = prop.value
        elif prop.name == 'MultiTextureEnable':
            material.multi_texture_enable = prop.value
        else:
            context.error('shader property not implemented: ' + prop.name)

    populate_settings_from_material(material)
    return material, principled


##########################################################################
# set shader properties
##########################################################################


def set_shader_properties(material, shader):
    material.shader.depth_compare = str(shader.depth_compare)
    material.shader.depth_mask = str(shader.depth_mask)
    material.shader.color_mask = shader.color_mask
    material.shader.dest_blend = str(shader.dest_blend)
    material.shader.fog_func = shader.fog_func
    material.shader.pri_gradient = str(shader.pri_gradient)
    material.shader.sec_gradient = str(shader.sec_gradient)
    material.shader.src_blend = str(shader.src_blend)
    material.shader.texturing = str(shader.texturing)
    material.shader.detail_color_func = str(shader.detail_color_func)
    material.shader.detail_alpha_func = str(shader.detail_alpha_func)
    material.shader.shader_preset = shader.shader_preset
    material.shader.alpha_test = str(shader.alpha_test)
    material.shader.post_detail_color_func = str(shader.post_detail_color_func)
    material.shader.post_detail_alpha_func = str(shader.post_detail_alpha_func)
