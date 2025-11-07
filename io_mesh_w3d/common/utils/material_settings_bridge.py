# <pep8 compliant>

import bpy


def _ensure_pass(settings, index=None):
    if settings.passes:
        idx = settings.active_pass_index if index is None else index
        return settings.passes[min(idx, len(settings.passes) - 1)]
    new_pass = settings.passes.add()
    settings.active_pass_index = 0
    return new_pass


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

    return {
        'material_type': material.material_type,
        'surface_type': material.surface_type,
        'attributes': set(material.attributes),
        'ambient': tuple(material.ambient),
        'specular': tuple(material.specular),
        'diffuse_color': tuple(material.diffuse_color),
        'translucency': material.translucency,
        'alpha_test': material.alpha_test,
        'blend_method': material.blend_method,
        'texture_1': material.texture_1,
        'damaged_texture': material.damaged_texture,
        'num_textures': material.num_textures,
        'multi_texture_enable': material.multi_texture_enable,
        'shader': shader_state,
    }


def restore_material_state(material, state):
    if not state:
        return
    material.material_type = state['material_type']
    material.surface_type = state['surface_type']
    material.attributes = state['attributes']
    material.ambient = state['ambient']
    material.specular = state['specular']
    material.diffuse_color = state['diffuse_color']
    material.translucency = state['translucency']
    material.alpha_test = state['alpha_test']
    material.blend_method = state['blend_method']
    material.texture_1 = state['texture_1']
    material.damaged_texture = state['damaged_texture']
    material.num_textures = state['num_textures']
    material.multi_texture_enable = state['multi_texture_enable']

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
    material.attributes = settings.attributes if settings.attributes else {'DEFAULT'}

    material.ambient = tuple(pass_settings.ambient)
    material.specular = tuple(pass_settings.specular)
    material.diffuse_color = pass_settings.diffuse[:3]
    material.use_nodes = True

    material.translucency = pass_settings.translucency
    material.alpha_test = pass_settings.opacity < 1.0
    material.blend_method = 'BLEND' if pass_settings.opacity < 1.0 else 'OPAQUE'

    shader_props = getattr(material, 'shader', None)
    if shader_props is not None:
        shader_props.depth_compare = str(pass_settings.shader.depth_compare)
        shader_props.depth_mask = str(pass_settings.shader.write_z and 1 or 0)
        shader_props.dest_blend = str(pass_settings.shader.custom_dest)
        shader_props.pri_gradient = str(pass_settings.shader.pri_gradient)
        shader_props.sec_gradient = str(pass_settings.shader.sec_gradient)
        shader_props.src_blend = str(pass_settings.shader.custom_src)
        shader_props.detail_color_func = str(pass_settings.shader.detail_color)
        shader_props.detail_alpha_func = str(pass_settings.shader.detail_alpha)
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

    active_pass.translucency = material.translucency
    active_pass.opacity = 0.0 if material.alpha_test else 1.0

    shader_props = getattr(material, 'shader', None)
    if shader_props is not None:
        active_pass.shader.depth_compare = int(shader_props.depth_compare)
        active_pass.shader.write_z = shader_props.depth_mask == '1'
        active_pass.shader.custom_dest = int(shader_props.dest_blend)
        active_pass.shader.pri_gradient = int(shader_props.pri_gradient)
        active_pass.shader.sec_gradient = int(shader_props.sec_gradient)
        active_pass.shader.custom_src = int(shader_props.src_blend)
        active_pass.shader.detail_color = int(shader_props.detail_color_func)
        active_pass.shader.detail_alpha = int(shader_props.detail_alpha_func)
        active_pass.shader.alpha_test = shader_props.alpha_test == '1'

    stage0 = active_pass.stage0
    stage0.enabled = bool(material.texture_1)
    if material.texture_1:
        stage0.texture = bpy.data.images.get(material.texture_1)

    stage1 = active_pass.stage1
    stage1.enabled = bool(material.damaged_texture)
    if material.damaged_texture:
        stage1.texture = bpy.data.images.get(material.damaged_texture)
