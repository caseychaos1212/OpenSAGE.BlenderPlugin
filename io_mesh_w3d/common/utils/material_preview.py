# <pep8 compliant>
"""Blender preview of W3D fixed-function texture stages and material passes."""

import bpy
from .helpers import set_blend_method


class _Preview:
    def __init__(self, tree):
        self.tree = tree
        self.frame = None
        self.index = 0

    def node(self, kind, label):
        node = self.tree.nodes.new(kind)
        node['_w3d_preview'] = True
        node.label = label
        node.parent = self.frame
        node.location = ((self.index % 4) * 230, -(self.index // 4) * 280)
        self.index += 1
        return node

    def connect(self, value, socket):
        for link in list(socket.links):
            self.tree.links.remove(link)
        if isinstance(value, bpy.types.NodeSocket):
            self.tree.links.new(value, socket)
        elif socket.type == 'RGBA' and isinstance(value, (int, float)):
            socket.default_value = (value, value, value, 1.0)
        else:
            socket.default_value = value

    def math(self, operation, a, b, label):
        node = self.node('ShaderNodeMath', label)
        node.operation = operation
        self.connect(a, node.inputs[0])
        self.connect(b, node.inputs[1])
        return node.outputs[0]

    def color(self, operation, a, b, label, factor=1.0, clamp=True):
        node = self.node('ShaderNodeMixRGB', label)
        node.blend_type = operation
        node.use_clamp = clamp
        self.connect(factor, node.inputs[0])
        self.connect(a, node.inputs[1])
        self.connect(b, node.inputs[2])
        return node.outputs[0]

    def inverse(self, value):
        return self.math('SUBTRACT', 1.0, value, 'One minus alpha')

    def texture(self, stage, channel, mesh, label):
        if not stage.enabled or stage.texture is None:
            return None
        node = self.node('ShaderNodeTexImage', label)
        node.image = stage.texture
        if 0 <= channel < len(mesh.uv_layers):
            uv = self.node('ShaderNodeUVMap', label + ' UV')
            uv.uv_map = mesh.uv_layers[channel].name
            self.connect(uv.outputs['UV'], node.inputs['Vector'])
        return node


def _detail(preview, color, alpha, texture, shader, extra):
    # OpenW3D shader.cpp applies PostDetail at stage 1: TEXTURE is the
    # second texture and CURRENT is the already shaded first texture.
    # Preserve this order for subtraction and both alpha blend operations.
    mode = str(extra.get('post_detail_color_func', shader.detail_color))
    alpha_mode = str(extra.get('post_detail_alpha_func', shader.detail_alpha))
    other = texture.outputs['Color']
    other_alpha = texture.outputs['Alpha']
    if mode == '1':
        color = other
    elif mode in ('2', '3', '4'):
        color = preview.color({'2': 'MULTIPLY', '3': 'SCREEN', '4': 'ADD'}[mode],
                              color, other, 'Detail color')
    elif mode == '5':
        color = preview.color('SUBTRACT', other, color, 'Detail minus base')
    elif mode == '6':
        color = preview.color('SUBTRACT', color, other, 'Base minus detail')
    elif mode in ('7', '8'):
        color = preview.color('MIX', color, other, 'Detail texture blend',
                              factor=other_alpha if mode == '7' else alpha)
    if alpha_mode == '1':
        alpha = other_alpha
    elif alpha_mode == '2':
        alpha = preview.math('MULTIPLY', alpha, other_alpha, 'Detail alpha')
    elif alpha_mode == '3':
        alpha = preview.inverse(preview.math('MULTIPLY', preview.inverse(alpha),
                                            preview.inverse(other_alpha), 'Inverse-scale alpha'))
    return color, alpha


def _blend_pass(preview, base, color, alpha, shader):
    # Framebuffer blending: source * sourceFactor + destination * destFactor.
    source = {'0': 0.0, '1': 1.0, '2': alpha}.get(shader.custom_src)
    if source is None:
        source = preview.inverse(alpha)
    if shader.custom_dest == '3':
        dest = preview.color('SUBTRACT', 1.0, color, 'One minus source color')
    elif shader.custom_dest == '5':
        dest = preview.inverse(alpha)
    else:
        dest = {'0': 0.0, '1': 1.0, '2': color, '4': alpha, '6': color}[shader.custom_dest]
    src_color = preview.color('MULTIPLY', color, source, 'Source contribution', clamp=False)
    dst_color = preview.color('MULTIPLY', base, dest, 'Destination contribution', clamp=False)
    return preview.color('ADD', src_color, dst_color, 'Combined passes')


def create_pass_preview(material, mesh):
    """Build the imported preview without altering stored W3D pass settings."""
    tree = material.node_tree
    bsdf = tree.nodes.get('Principled BSDF')
    if bsdf is None:
        return
    for node in list(tree.nodes):
        if node.get('_w3d_preview'):
            tree.nodes.remove(node)
    preview = _Preview(tree)
    layers = {layer.name for layer in (mesh.vertex_colors if bpy.app.version < (3, 2, 0)
                                      else mesh.color_attributes)}
    base_color = base_alpha = None
    for pass_index, config in enumerate(material.w3d_material_settings.passes):
        preview.frame = None
        frame = preview.node('NodeFrame', f'W3D Pass {pass_index + 1}')
        frame.location = (-1600, -pass_index * 1300)
        preview.frame = frame
        preview.index = 0
        shader = config.shader
        diffuse, opacity = tuple(config.diffuse), config.opacity
        for prefix in ('DCG', 'DIG'):
            name = f'{prefix}_{pass_index}'
            if name not in layers:
                continue
            vertex = preview.node('ShaderNodeVertexColor', name)
            vertex.layer_name = name
            diffuse = preview.color('MULTIPLY', diffuse, vertex.outputs['Color'], name + ' color')
            # DIG is lighting only; its alpha is not a terrain blend mask.
            if prefix == 'DCG' and not config.blend_mask:
                opacity = preview.math('MULTIPLY', opacity, vertex.outputs['Alpha'], 'Vertex alpha x opacity')

        if config.blend_mask in layers:
            mask = preview.node('ShaderNodeVertexColor', 'Painted blend mask')
            mask.layer_name = config.blend_mask
            average = preview.node('ShaderNodeVectorMath', 'Grayscale mask')
            average.operation = 'DOT_PRODUCT'
            preview.connect(mask.outputs['Color'], average.inputs[0])
            average.inputs[1].default_value = (1 / 3, 1 / 3, 1 / 3)
            mask_alpha = average.outputs['Value']
            opacity = preview.math('MULTIPLY', config.opacity, mask_alpha, 'Mask x opacity')

        textures = [preview.texture(getattr(config, f'stage{i}'),
                                    getattr(config, f'uv_channel_stage{i}') - 1, mesh,
                                    f'Pass {pass_index + 1}, Stage {i}') for i in range(2)]
        color, alpha = diffuse, opacity
        if textures[0] is not None:
            color, alpha = textures[0].outputs['Color'], textures[0].outputs['Alpha']
            if shader.pri_gradient != '0':
                operation = 'ADD' if shader.pri_gradient == '2' else 'MULTIPLY'
                color = preview.color(operation, color, diffuse, 'Texture and diffuse color')
                alpha = preview.math('MULTIPLY', alpha, opacity, 'Texture alpha x diffuse alpha')
        if textures[1] is not None:
            color, alpha = _detail(preview, color, alpha, textures[1], shader,
                                   config.get('_w3d_shader_extra', {}))

        gate = 1.0
        if shader.alpha_test:
            # OpenW3D uses 0x60, reversing the comparison for inverse alpha.
            if shader.custom_src == '3':
                rejected = preview.math('GREATER_THAN', alpha, 159 / 255, 'Alpha test reject')
            else:
                rejected = preview.math('LESS_THAN', alpha, 96 / 255, 'Alpha test reject')
            gate = preview.inverse(rejected)
        coverage = alpha if shader.custom_src == '2' else (
            preview.inverse(alpha) if shader.custom_src == '3' else 1.0)
        if shader.alpha_test:
            coverage = preview.math('MULTIPLY', coverage, gate, 'Visible pass alpha')

        if base_color is None:
            base_color, base_alpha = color, coverage
        else:
            combined = _blend_pass(preview, base_color, color, alpha, shader)
            base_color = (preview.color('MIX', base_color, combined, 'Alpha-tested pass', factor=gate)
                          if shader.alpha_test else combined)
            # Blend masks mix layers within this surface; they must not punch
            # holes through an opaque base. Track surface coverage separately.
            if shader.custom_src != '0':
                base_alpha = preview.inverse(preview.math(
                    'MULTIPLY', preview.inverse(base_alpha), preview.inverse(coverage), 'Uncovered surface'))

    if base_color is not None:
        preview.connect(base_color, bsdf.inputs['Base Color'])
        preview.connect(base_alpha, bsdf.inputs['Alpha'])
        # Dithered transparency supports smooth alpha and multiple terrain layers.
        set_blend_method(material, 'HASHED')
