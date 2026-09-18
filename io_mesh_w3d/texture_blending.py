# <pep8 compliant>
"""Create and paint W3D terrain texture blends."""

import bpy
from bpy.props import StringProperty
from bpy_extras.node_shader_utils import PrincipledBSDFWrapper
from .common.utils.helpers import enable_nodes, new_vertex_color_layer
from .common.utils.material_preview import create_pass_preview
from .common.utils.material_settings_bridge import apply_pass_to_material


def color_layers(mesh):
    return mesh.vertex_colors if bpy.app.version < (3, 2, 0) else mesh.color_attributes


def ensure_blend_mask(obj, config, pass_index, initial=1.0):
    layers = color_layers(obj.data)
    mask = layers.get(config.blend_mask) if config.blend_mask else None
    if mask is None:
        original = layers.get(f'DCG_{pass_index}')
        mask = new_vertex_color_layer(obj.data, f'W3D Blend {pass_index + 1}')
        for index, datum in enumerate(mask.data):
            value = original.data[index].color[3] if original is not None else initial
            datum.color = (value, value, value, 1.0)
        config.blend_mask = mask.name
    if bpy.app.version < (3, 2, 0):
        layers.active = mask
    else:
        layers.active_color_index = list(layers).index(mask)
    return mask


def refresh_preview(obj):
    material = obj.active_material
    settings = material.w3d_material_settings
    enable_nodes(material)
    if settings.passes:
        apply_pass_to_material(material, settings, settings.passes[0])
    PrincipledBSDFWrapper(material, is_readonly=False).roughness = 1.0
    create_pass_preview(material, obj.data)


class W3D_OT_create_texture_blend(bpy.types.Operator):
    bl_idname = 'w3d.create_texture_blend'
    bl_label = 'Create Texture Blend'
    bl_description = 'Create a new base and blend material in the active slot, with a paintable mask'
    bl_options = {'REGISTER', 'UNDO'}

    base_texture: StringProperty(name='Base Texture')
    blend_texture: StringProperty(name='Blend Texture')

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == 'MESH'

    def invoke(self, context, _event):
        material = context.object.active_material
        if material and material.w3d_material_settings.passes:
            image = material.w3d_material_settings.passes[0].stage0.texture
            if image is not None:
                self.base_texture = image.name
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, _context):
        self.layout.prop_search(self, 'base_texture', bpy.data, 'images')
        self.layout.prop_search(self, 'blend_texture', bpy.data, 'images')
        self.layout.label(text='You can also open textures in the material panel afterward.')

    def execute(self, context):
        obj = context.object
        if len(obj.data.materials) > 1:
            self.report({'ERROR'}, 'Texture blend setup needs a mesh with one material slot. Separate material regions first.')
            return {'CANCELLED'}
        if not obj.data.uv_layers:
            self.report({'ERROR'}, 'UV unwrap the mesh before creating a texture blend')
            return {'CANCELLED'}
        for name in (self.base_texture, self.blend_texture):
            if name and name not in bpy.data.images:
                self.report({'ERROR'}, f'Texture {name!r} is not loaded')
                return {'CANCELLED'}
        if obj.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        if obj.data.users > 1:
            obj.data = obj.data.copy()
        material = bpy.data.materials.new(obj.name + ' Blend')
        material.material_type = 'VERTEX_MATERIAL'
        settings = material.w3d_material_settings
        settings.material_type = 'VERTEX_MATERIAL'
        for index, (name, texture) in enumerate((('Base', self.base_texture), ('Blend', self.blend_texture))):
            config = settings.passes.add()
            config.name = name
            config.shader.blend_mode = '0' if index == 0 else '5'
            config.stage0.enabled = True
            config.stage0.texture = bpy.data.images.get(texture)
            config.stage1.enabled = False
        settings.active_pass_index = 1
        settings.ui_pass_section = 'TEXTURES'
        if obj.data.materials:
            obj.data.materials[0] = material
        else:
            obj.data.materials.append(material)
        obj.active_material_index = 0
        ensure_blend_mask(obj, settings.passes[1], 1, initial=0.0)
        refresh_preview(obj)
        self.report({'INFO'}, 'Blend created. Paint its mask: black = base, white = blend.')
        return {'FINISHED'}


class W3D_OT_refresh_blend_preview(bpy.types.Operator):
    bl_idname = 'w3d.refresh_blend_preview'
    bl_label = 'Update Blend Preview'
    bl_description = 'Rebuild the Blender preview from all W3D texture stages, passes, and paint masks'
    bl_options = {'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return bool(obj and obj.type == 'MESH' and obj.active_material
                    and obj.active_material.w3d_material_settings.passes)

    def execute(self, context):
        refresh_preview(context.object)
        return {'FINISHED'}


class W3D_OT_paint_blend_mask(bpy.types.Operator):
    bl_idname = 'w3d.paint_blend_mask'
    bl_label = 'Paint Blend Mask'
    bl_description = 'Paint the selected pass: black hides it, white shows it, gray blends it'
    bl_options = {'UNDO'}

    @classmethod
    def poll(cls, context):
        return W3D_OT_refresh_blend_preview.poll(context)

    def execute(self, context):
        obj = context.object
        settings = obj.active_material.w3d_material_settings
        index = min(settings.active_pass_index, len(settings.passes) - 1)
        config = settings.passes[index]
        if config.shader.pri_gradient == '0' or not (
                config.shader.custom_src in ('2', '3') or config.shader.custom_dest in ('4', '5')
                or config.shader.alpha_test or config.shader.detail_color == '8'):
            self.report({'ERROR'}, 'Select an alpha-blended pass with Primary Gradient enabled')
            return {'CANCELLED'}
        if obj.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        if obj.data.users > 1:
            obj.data = obj.data.copy()
        if obj.active_material.users > 1:
            obj.active_material = obj.active_material.copy()
            settings = obj.active_material.w3d_material_settings
            config = settings.passes[index]
        ensure_blend_mask(obj, config, index)
        refresh_preview(obj)
        bpy.ops.object.mode_set(mode='VERTEX_PAINT')
        for area in getattr(context.screen, 'areas', []):
            if area.type == 'VIEW_3D':
                area.spaces.active.shading.type = 'MATERIAL'
        self.report({'INFO'}, 'Paint white to reveal this texture, black to hide it. More vertices give finer blends.')
        return {'FINISHED'}
