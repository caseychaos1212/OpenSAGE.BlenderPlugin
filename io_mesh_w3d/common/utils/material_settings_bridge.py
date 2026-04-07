# <pep8 compliant>

import bpy
from bpy_extras import node_shader_utils


def _ensure_pass(settings, index=None):
    if settings.passes:
        idx = settings.active_pass_index if index is None else index
        return settings.passes[min(idx, len(settings.passes) - 1)]
    new_pass = settings.passes.add()
    settings.active_pass_index = 0
    return new_pass


def _get_principled(material, readonly):
    try:
        if not material.use_nodes and readonly:
            return None
        if not material.use_nodes:
            material.use_nodes = True
        return node_shader_utils.PrincipledBSDFWrapper(material, is_readonly=readonly)
    except Exception:
        return None


def snapshot_material_state(material):
    shader = getattr(material, 'shader', None)
    shader_state = None
    if shader is not None:
        shader_state = {
            'depth_compare': shader.depth_compare,
            'depth_mask': shader.depth_mask,
            'dest_blend': shader.dest_blend,
            'pri_gradient': shader.pri_gradient,
            'sec_gradient': shader.sec_gradient,
            'src_blend': shader.src_blend,
            'detail_color_func': shader.detail_color_func,
            'detail_alpha_func': shader.detail_alpha_func,
            'alpha_test': shader.alpha_test,
        }

    principled = _get_principled(material, True)

    return {
        'use_nodes': material.use_nodes,
        'material_type': material.material_type,
        'surface_type': material.surface_type,
        'attributes': set(material.attributes),
        'ambient': tuple(material.ambient),
        'specular': tuple(material.specular),
        'diffuse_color': tuple(material.diffuse_color),
        'translucency': material.translucency,
        'alpha_test': material.alpha_test,
        'blend_method': material.blend_method,
        'blend_mode': material.blend_mode,
        'stage0_mapping': material.stage0_mapping,
        'stage1_mapping': material.stage1_mapping,
        'vm_args_0': material.vm_args_0,
        'vm_args_1': material.vm_args_1,
        'texture_1': material.texture_1,
        'damaged_texture': material.damaged_texture,
        'num_textures': material.num_textures,
        'multi_texture_enable': material.multi_texture_enable,
        'principled': {
            'alpha': principled.alpha if principled is not None else None,
            'emission_color': tuple(principled.emission_color[:3]) if principled is not None else None,
            'specular': principled.specular if principled is not None else None,
        },
        'shader': shader_state,
    }


def restore_material_state(material, state):
    if not state:
        return
    material.use_nodes = state['use_nodes']
    material.material_type = state['material_type']
    material.surface_type = state['surface_type']
    material.attributes = state['attributes']
    material.ambient = state['ambient']
    material.specular = state['specular']
    material.diffuse_color = state['diffuse_color']
    material.translucency = state['translucency']
    material.alpha_test = state['alpha_test']
    material.blend_method = state['blend_method']
    material.blend_mode = state['blend_mode']
    material.stage0_mapping = state['stage0_mapping']
    material.stage1_mapping = state['stage1_mapping']
    material.vm_args_0 = state['vm_args_0']
    material.vm_args_1 = state['vm_args_1']
    material.texture_1 = state['texture_1']
    material.damaged_texture = state['damaged_texture']
    material.num_textures = state['num_textures']
    material.multi_texture_enable = state['multi_texture_enable']

    principled_state = state['principled']
    if state['use_nodes'] and principled_state['alpha'] is not None:
        principled = _get_principled(material, False)
        if principled is not None:
            principled.alpha = principled_state['alpha']
            principled.emission_color = principled_state['emission_color']
            principled.specular = principled_state['specular']

    shader_state = state['shader']
    shader = getattr(material, 'shader', None)
    if shader is not None and shader_state is not None:
        shader.depth_compare = shader_state['depth_compare']
        shader.depth_mask = shader_state['depth_mask']
        shader.dest_blend = shader_state['dest_blend']
        shader.pri_gradient = shader_state['pri_gradient']
        shader.sec_gradient = shader_state['sec_gradient']
        shader.src_blend = shader_state['src_blend']
        shader.detail_color_func = shader_state['detail_color_func']
        shader.detail_alpha_func = shader_state['detail_alpha_func']
        shader.alpha_test = shader_state['alpha_test']


def apply_pass_to_material(material, settings, pass_settings):
    material.material_type = settings.material_type
    material.surface_type = settings.surface_type
    attributes = set(settings.attributes) if settings.attributes else {'DEFAULT'}
    if pass_settings.specular_to_diffuse:
        attributes.add('COPY_SPECULAR_TO_DIFFUSE')
    else:
        attributes.discard('COPY_SPECULAR_TO_DIFFUSE')
        if not attributes:
            attributes = {'DEFAULT'}
    material.attributes = attributes

    material.ambient = tuple(pass_settings.ambient)
    material.specular = tuple(pass_settings.specular)
    material.diffuse_color = tuple(pass_settings.diffuse)
    material.use_nodes = True
    material.blend_mode = int(pass_settings.shader.blend_mode)
    material.stage0_mapping = pass_settings.stage0_mapping
    material.stage1_mapping = pass_settings.stage1_mapping
    material.vm_args_0 = pass_settings.stage0_args
    material.vm_args_1 = pass_settings.stage1_args

    principled = _get_principled(material, False)
    if principled is not None:
        principled.base_color = tuple(pass_settings.diffuse[:3])
        principled.alpha = pass_settings.opacity
        principled.emission_color = tuple(pass_settings.emissive)
        principled.specular = pass_settings.shininess

    material.translucency = pass_settings.translucency
    material.alpha_test = pass_settings.opacity < 1.0
    material.blend_method = 'BLEND' if pass_settings.opacity < 1.0 else 'OPAQUE'

    shader_props = getattr(material, 'shader', None)
    if shader_props is not None:
        shader_props.depth_compare = pass_settings.shader.depth_compare
        shader_props.depth_mask = str(pass_settings.shader.write_z and 1 or 0)
        shader_props.dest_blend = pass_settings.shader.custom_dest
        shader_props.pri_gradient = pass_settings.shader.pri_gradient
        shader_props.sec_gradient = pass_settings.shader.sec_gradient
        shader_props.src_blend = pass_settings.shader.custom_src
        shader_props.detail_color_func = pass_settings.shader.detail_color
        shader_props.detail_alpha_func = pass_settings.shader.detail_alpha
        shader_props.alpha_test = str(int(pass_settings.shader.alpha_test))

    stage0 = pass_settings.stage0
    stage1 = pass_settings.stage1

    textures = 0
    if stage0.enabled and stage0.texture:
        material.texture_1 = stage0.texture.name
        textures += 1
    else:
        material.texture_1 = ''

    if stage1.enabled and stage1.texture:
        material.damaged_texture = stage1.texture.name
        textures += 1
    else:
        material.damaged_texture = ''

    material.num_textures = textures
    material.multi_texture_enable = textures > 1


def apply_material_settings_to_legacy(material):
    settings = getattr(material, 'w3d_material_settings', None)
    if settings is None or not settings.passes:
        return
    active_pass = _ensure_pass(settings)
    apply_pass_to_material(material, settings, active_pass)


def populate_settings_from_material(material):
    settings = getattr(material, 'w3d_material_settings', None)
    if settings is None:
        return

    active_pass = _ensure_pass(settings)

    settings.material_type = material.material_type
    settings.surface_type = material.surface_type
    settings.attributes = set(material.attributes)

    active_pass.ambient = tuple(material.ambient)
    active_pass.specular = tuple(material.specular)
    active_pass.diffuse = (
        material.diffuse_color[0],
        material.diffuse_color[1],
        material.diffuse_color[2],
        1.0,
    )
    active_pass.specular_to_diffuse = 'COPY_SPECULAR_TO_DIFFUSE' in material.attributes
    active_pass.stage0_mapping = material.stage0_mapping
    active_pass.stage1_mapping = material.stage1_mapping
    active_pass.stage0_args = material.vm_args_0
    active_pass.stage1_args = material.vm_args_1

    active_pass.translucency = material.translucency
    principled = _get_principled(material, True)
    if principled is not None:
        active_pass.emissive = tuple(principled.emission_color[:3])
        active_pass.opacity = principled.alpha
        active_pass.shininess = principled.specular
    else:
        active_pass.opacity = 0.0 if material.alpha_test else 1.0

    active_pass.shader.blend_mode = str(material.blend_mode)
    shader_props = getattr(material, 'shader', None)
    if shader_props is not None:
        active_pass.shader.depth_compare = shader_props.depth_compare
        active_pass.shader.write_z = shader_props.depth_mask == '1'
        active_pass.shader.custom_dest = shader_props.dest_blend
        active_pass.shader.pri_gradient = shader_props.pri_gradient
        active_pass.shader.sec_gradient = shader_props.sec_gradient
        active_pass.shader.custom_src = shader_props.src_blend
        active_pass.shader.detail_color = shader_props.detail_color_func
        active_pass.shader.detail_alpha = shader_props.detail_alpha_func
        active_pass.shader.alpha_test = shader_props.alpha_test == '1'

    stage0 = active_pass.stage0
    stage0.enabled = bool(material.texture_1)
    if material.texture_1:
        stage0.texture = bpy.data.images.get(material.texture_1)

    stage1 = active_pass.stage1
    stage1.enabled = bool(material.damaged_texture)
    if material.damaged_texture:
        stage1.texture = bpy.data.images.get(material.damaged_texture)
