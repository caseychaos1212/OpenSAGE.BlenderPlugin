# <pep8 compliant>
# Written by Stephan Vedder and Michael Schnabel

import configparser
import os
from pathlib import Path

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Material, PropertyGroup, Bone, Mesh, Object


def _sync_object_type_from_settings(settings, context):
    obj = getattr(settings, 'id_data', None)
    if obj is None:
        return
    try:
        from io_mesh_w3d.common.utils.object_settings_bridge import sync_object_type_from_settings
        sync_object_type_from_settings(obj, context=context)
    except Exception:
        # During registration or unit tests Blender data may be unavailable.
        pass


def _sync_scene_objects(scene_settings, context):
    scene = getattr(scene_settings, 'id_data', None)
    if scene is None and context is not None:
        scene = getattr(context, 'scene', None)
    if scene is None:
        return
    try:
        from io_mesh_w3d.common.utils.object_settings_bridge import sync_scene_object_types
        sync_scene_object_types(scene, context=context)
    except Exception:
        pass


W3D_GEOMETRY_TYPE_ITEMS = [
    ('NORMAL', 'Normal', 'Standard geometry.'),
    ('CAM_PARAL', 'Cam-Paral', 'Camera parallel billboard.'),
    ('OBBOX', 'OBBox', 'Oriented bounding box.'),
    ('AABOX', 'AABox', 'Axis-aligned bounding box.'),
    ('CAM_ORIENT', 'Cam-Oriented', 'Camera oriented billboard.'),
    ('NULL_LOD', 'Null LOD', 'LOD placeholder.'),
    ('DAZZLE', 'Dazzle', 'Renegade dazzle sprite.'),
    ('AGGREGATE', 'Aggregate', 'Aggregate geometry.'),
    ('CAM_Z_ORIENT', 'Cam Z-Oriented', 'Camera Z oriented billboard.'),
]

W3D_HLOD_ROLE_ITEMS = [
    ('LOD', 'LOD Geometry', 'Export this object as normal geometry and include it in the HLOD LOD arrays.'),
    ('AGGREGATE', 'Aggregate', 'Export this object as an aggregate attachment entry only; no mesh chunk is written.'),
    ('PROXY', 'Proxy', 'Export this object as a proxy attachment entry only; no mesh chunk is written.'),
]

W3D_STAGE_ANIM_ITEMS = [
    ('LOOP', 'Loop', 'Repeat animation indefinitely.'),
    ('PINGPONG', 'Ping Pong', 'Play forward then backward.'),
    ('ONCE', 'Once', 'Play single time.'),
    ('MANUAL', 'Manual', 'Controlled by code.'),
]

W3D_PASS_HINT_ITEMS = [
    ('BASE_TEXTURE', 'Base Texture', 'Diffuse/base pass.'),
    ('EMISSIVE_LIGHT_MAP', 'Emissive Light Map', 'Light/emissive data.'),
    ('ENVIRONMENT_MAP', 'Environment Map', 'Environment reflection.'),
    ('SHINYNESS_MAP', 'Shinyness Map', 'Specular/shininess data.'),
]

W3D_BLEND_MODE_ITEMS = [
    ('0', 'Opaque', 'Normal color or map with no alpha opacity and no blended overlay.'),
    ('1', 'Add', 'Brighten the base color with additive blending.'),
    ('2', 'Multiply', 'Multiply the base color by the blend color to darken the result.'),
    ('3', 'Multiply and Add', 'Combine multiply-style darkening with additive brightening.'),
    ('4', 'Screen', 'Similar to Add, but with a softer screen blend result.'),
    ('5', 'Alpha Blend', 'Use the map alpha channel as grayscale opacity.'),
    ('6', 'Alpha Test', 'Use a thresholded alpha channel for hard-edged opacity.'),
    ('7', 'Alpha Test and Blend', 'Combine alpha-test and alpha-blend behavior.'),
    ('8', 'Custom', 'Use the source and destination blend factors directly.'),
]

W3D_SOURCE_BLEND_ITEMS = [
    ('0', 'Zero', 'Fragment is not added to the color buffer.'),
    ('1', 'One', 'Fragment is added unmodified to the color buffer.'),
    ('2', 'Src Alpha', 'Multiply fragment RGB by the fragment alpha channel.'),
    ('3', '1-Src Alpha', 'Multiply fragment RGB by one minus the fragment alpha channel.'),
]

W3D_DEST_BLEND_ITEMS = [
    ('0', 'Zero', 'Destination pixel does not contribute to blending.'),
    ('1', 'One', 'Destination pixel is added unmodified.'),
    ('2', 'Src Color', 'Destination pixel is multiplied by fragment RGB.'),
    ('3', '1-Src Color', 'Destination pixel is multiplied by one minus fragment RGB.'),
    ('4', 'Src Alpha', 'Destination pixel is multiplied by fragment alpha.'),
    ('5', '1-Src Alpha', 'Destination pixel is multiplied by one minus fragment alpha.'),
    ('6', 'Src Color PreFog', 'Destination pixel is multiplied by fragment RGB before fogging.'),
]

W3D_DEPTH_COMPARE_ITEMS = [
    ('0', 'Pass Never', 'Never pass the depth comparison test.'),
    ('1', 'Pass Less', 'Pass if the incoming depth is less than the stored depth.'),
    ('2', 'Pass Equal', 'Pass if the incoming depth equals the stored depth.'),
    ('3', 'Pass LEqual', 'Pass if the incoming depth is less than or equal to the stored depth.'),
    ('4', 'Pass Greater', 'Pass if the incoming depth is greater than the stored depth.'),
    ('5', 'Pass NEqual', 'Pass if the incoming depth is not equal to the stored depth.'),
    ('6', 'Pass GEqual', 'Pass if the incoming depth is greater than or equal to the stored depth.'),
    ('7', 'Pass Always', 'Always draw, ignoring the depth test result.'),
]

W3D_PRIMARY_GRADIENT_ITEMS = [
    ('0', 'Disable', 'Disable diffuse-lighting contribution.'),
    ('1', 'Modulate', 'Multiply pixel color by lighting color.'),
    ('2', 'Add', 'Add lighting to the pixel color, useful for lightmaps.'),
    ('3', 'BumpEnvMap', 'Use environment-mapped bump mapping.'),
    ('5', 'Enable', 'Legacy enable mode.'),
]

W3D_SECONDARY_GRADIENT_ITEMS = [
    ('0', 'Disable', 'Disable specular-lighting contribution.'),
    ('1', 'Enable', 'Enable specular-lighting contribution.'),
]

W3D_DETAIL_COLOR_FUNC_ITEMS = [
    ('0', 'Disable', 'Disable detail color contribution.'),
    ('1', 'Detail', 'Override the stage 0 mapping with stage 1 color.'),
    ('2', 'Scale', 'Keep whites unchanged while darker values darken the result.'),
    ('3', 'InvScale', 'Use an inverse-scale blend that preserves brightness better than Add.'),
    ('4', 'Add', 'Brighten the base color with additive overlay.'),
    ('5', 'Sub', 'Darken the result with subtractive overlay.'),
    ('6', 'SubR', 'Reverse subtractive blend.'),
    ('7', 'Blend', 'Blend local and detail color using local alpha.'),
    ('8', 'DetailBlend', 'Use the detail texture and self-illuminate it.'),
    ('9', 'Alt', 'Alternate legacy detail color function.'),
    ('10', 'DetailAlt', 'Alternate detail override function.'),
    ('11', 'ScaleAlt', 'Alternate scale detail function.'),
    ('12', 'InvScaleAlt', 'Alternate inverse-scale detail function.'),
]

W3D_DETAIL_ALPHA_FUNC_ITEMS = [
    ('0', 'Disable', 'Disable stage 1 alpha contribution.'),
    ('1', 'Detail', 'Override the alpha from stage 0.'),
    ('2', 'Scale', 'Keep white unchanged while darker values darken the alpha result.'),
    ('3', 'InvScale', 'Use inverse-scale alpha blending.'),
]

W3D_BLEND_MODE_PRESETS = {
    '0': {'custom_src': '1', 'custom_dest': '0', 'write_z': True, 'alpha_test': False},
    '1': {'custom_src': '1', 'custom_dest': '1', 'write_z': False, 'alpha_test': False},
    '2': {'custom_src': '0', 'custom_dest': '2', 'write_z': False, 'alpha_test': False},
    '3': {'custom_src': '1', 'custom_dest': '2', 'write_z': False, 'alpha_test': False},
    '4': {'custom_src': '1', 'custom_dest': '3', 'write_z': False, 'alpha_test': False},
    '5': {'custom_src': '2', 'custom_dest': '5', 'write_z': False, 'alpha_test': False},
    '6': {'custom_src': '1', 'custom_dest': '0', 'write_z': True, 'alpha_test': True},
    '7': {'custom_src': '2', 'custom_dest': '5', 'write_z': True, 'alpha_test': True},
}

_SHADER_BLEND_SYNC_GUARD = set()


def _shader_guard_key(shader_settings):
    try:
        return shader_settings.as_pointer()
    except Exception:
        return None


def _set_shader_blend_guard(shader_settings, enabled):
    key = _shader_guard_key(shader_settings)
    if key is None:
        return
    if enabled:
        _SHADER_BLEND_SYNC_GUARD.add(key)
    else:
        _SHADER_BLEND_SYNC_GUARD.discard(key)


def _shader_blend_guarded(shader_settings):
    key = _shader_guard_key(shader_settings)
    return key in _SHADER_BLEND_SYNC_GUARD if key is not None else False


def _apply_blend_mode_preset(shader_settings):
    if _shader_blend_guarded(shader_settings):
        return
    preset = W3D_BLEND_MODE_PRESETS.get(shader_settings.blend_mode)
    if preset is None:
        return
    _set_shader_blend_guard(shader_settings, True)
    try:
        shader_settings.custom_src = preset['custom_src']
        shader_settings.custom_dest = preset['custom_dest']
        shader_settings.write_z = preset['write_z']
        shader_settings.alpha_test = preset['alpha_test']
    finally:
        _set_shader_blend_guard(shader_settings, False)


def _infer_blend_mode(shader_settings):
    for blend_mode, preset in W3D_BLEND_MODE_PRESETS.items():
        if (
            shader_settings.custom_src == preset['custom_src']
            and shader_settings.custom_dest == preset['custom_dest']
            and bool(shader_settings.write_z) == preset['write_z']
            and bool(shader_settings.alpha_test) == preset['alpha_test']
        ):
            return blend_mode
    return '8'


def _sync_blend_mode_from_controls(shader_settings):
    if _shader_blend_guarded(shader_settings):
        return
    inferred = _infer_blend_mode(shader_settings)
    if shader_settings.blend_mode == inferred:
        return
    _set_shader_blend_guard(shader_settings, True)
    try:
        shader_settings.blend_mode = inferred
    finally:
        _set_shader_blend_guard(shader_settings, False)

W3D_VERTEX_MAPPER_TYPES = [
    (0x00, 'UV', 'Use authored UV coordinates.'),
    (0x01, 'Environment', 'Use normals to generate environment-map coordinates.'),
    (0x02, 'Classic Environment', 'Use reflection-based environment mapping with stronger contrast.'),
    (0x03, 'Screen', 'Use screen coordinates so the map always faces the camera.'),
    (0x04, 'Linear Offset', 'Scroll the map over time with UPerSec and VPerSec arguments.'),
    (0x05, 'Silhouette', 'Obsolete legacy mapper; not supported in the classic docs.'),
    (0x06, 'Scale', 'Scale UV coordinates with UScale and VScale arguments.'),
    (0x07, 'Grid', 'Animate a grid bitmap with FPS and Log2Width arguments.'),
    (0x08, 'Rotate', 'Rotate coordinates with Speed, UCenter, and VCenter arguments.'),
    (0x09, 'Sine', 'Move coordinates in a lissajous pattern with amplitude, frequency, and phase arguments.'),
    (0x0A, 'Step', 'Move coordinates in discrete steps with UStep, VStep, and SPS arguments.'),
    (0x0B, 'Zigzag', 'Scroll coordinates and periodically reverse direction.'),
    (0x0C, 'WS Classic Environment', 'Use world-space normal environment mapping.'),
    (0x0D, 'WS Environment', 'Use world-space reflection environment mapping.'),
    (0x0E, 'Grid Classic Environment', 'Animate a grid bitmap using classic environment mapping.'),
    (0x0F, 'Grid Environment', 'Animate a grid bitmap using environment mapping.'),
    (0x10, 'Random', 'Apply random step-like offsets and rotations.'),
    (0x11, 'Edge', 'Use the bitmap top row for fuzzy edge or glow-like effects.'),
    (0x12, 'Bump Environment', 'Use environment-mapped bump mapping.'),
]


def _build_stage_mapping_items(shift):
    return [(f'0x{code << shift:08X}', label, description) for code, label, description in W3D_VERTEX_MAPPER_TYPES]


W3D_STAGE0_MAPPING_ITEMS = _build_stage_mapping_items(16)
W3D_STAGE1_MAPPING_ITEMS = _build_stage_mapping_items(8)


def _load_dazzle_items():
    """Load dazzle names from the bundled INI file or fall back to defaults."""
    default_items = [
        ('DEFAULT', 'DEFAULT', 'Default dazzle entry.'),
        ('SUN', 'SUN', 'Sun glare preset.'),
        ('REN_L5_STREETLIGHT', 'REN_L5_STREETLIGHT', 'Renegade streetlight.'),
        ('REN_BRAKELIGHT', 'REN_BRAKELIGHT', 'Renegade brake light.'),
        ('REN_HEADLIGHT', 'REN_HEADLIGHT', 'Renegade headlight.'),
        ('REN_L5_REDLIGHT', 'REN_L5_REDLIGHT', 'Renegade red light.'),
        ('REN_NUKE', 'REN_NUKE', 'Renegade nuke dazzle.'),
        ('REN_BLINKLIGHT_RED', 'REN_BLINKLIGHT_RED', 'Renegade blinking red light.'),
        ('REN_BLINKLIGHT_WHITE', 'REN_BLINKLIGHT_WHITE', 'Renegade blinking white light.'),
        ('REN_VEHICLELIGHT_RED', 'REN_VEHICLELIGHT_RED', 'Renegade vehicle red light.'),
        ('REN_VEHICLELIGHT_WHITE', 'REN_VEHICLELIGHT_WHITE', 'Renegade vehicle white light.'),
    ]

    addon_root = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))
    ini_path = addon_root / 'exporter' / 'max2w3d-master' / 'w3dmaxtools' / 'Content' / 'dazzle.ini'
    if not ini_path.exists():
        return default_items

    parser = configparser.ConfigParser()
    try:
        parser.read(ini_path, encoding='utf-8')
    except (OSError, configparser.Error):
        return default_items

    if 'Dazzles_List' not in parser:
        return default_items

    section = parser['Dazzles_List']
    entries = []
    for key in sorted(section, key=lambda value: int(value) if value.isdigit() else value):
        value = section[key].strip()
        if not value:
            continue
        entries.append((value, value, f'Dazzle preset {value}'))

    return entries or default_items


DEFAULT_DAZZLE_ITEMS = _load_dazzle_items()
_DAZZLE_CACHE = {'path': None, 'items': DEFAULT_DAZZLE_ITEMS}


def _load_items_from_path(path):
    target = Path(path) if path else None
    if not target or not target.exists():
        return DEFAULT_DAZZLE_ITEMS
    parser = configparser.ConfigParser()
    try:
        parser.read(target, encoding='utf-8')
    except (OSError, configparser.Error):
        return DEFAULT_DAZZLE_ITEMS
    if 'Dazzles_List' not in parser:
        return DEFAULT_DAZZLE_ITEMS
    section = parser['Dazzles_List']
    def sort_key(value):
        return (not value.isdigit(), int(value) if value.isdigit() else value)
    entries = []
    for key in sorted(section, key=sort_key):
        value = section[key].strip()
        if not value:
            continue
        entries.append((value, value, f'Dazzle preset {value}'))
    return entries or DEFAULT_DAZZLE_ITEMS


def refresh_dazzle_items(path):
    """Refresh the cached dazzle enum list."""
    resolved = os.path.abspath(path) if path else ''
    if _DAZZLE_CACHE['path'] == resolved:
        return
    _DAZZLE_CACHE['items'] = _load_items_from_path(resolved)
    _DAZZLE_CACHE['path'] = resolved


def get_dazzle_enum_items(self, context):
    if context and getattr(context, 'preferences', None):
        prefs = context.preferences.addons.get(__package__)
        if prefs and getattr(prefs, 'preferences', None):
            refresh_dazzle_items(prefs.preferences.dazzle_ini_path)
    items = _DAZZLE_CACHE.get('items') or [('DEFAULT', 'DEFAULT', 'Default dazzle preset')]
    return items


class W3DStageSettings(PropertyGroup):
    enabled: BoolProperty(name='Enabled', default=False)
    texture: PointerProperty(name='Texture', type=bpy.types.Image)
    clamp_u: BoolProperty(
        name='Clamp U',
        description='Clamp texture sampling on the U axis instead of wrapping.',
        default=False)
    clamp_v: BoolProperty(
        name='Clamp V',
        description='Clamp texture sampling on the V axis instead of wrapping.',
        default=False)
    no_lod: BoolProperty(
        name='No LOD',
        description='Disable texture mip/LOD selection for this stage.',
        default=False)
    publish: BoolProperty(
        name='Publish',
        description='Mark this stage texture for export/publish in the W3D material data.',
        default=False)
    display: BoolProperty(
        name='Display',
        description='Use this enabled stage as the display texture pushed to the Blender material preview.',
        default=False)
    frames: IntProperty(name='Frames', default=1, min=0, max=999)
    fps: FloatProperty(name='FPS', default=15.0, min=0.0, max=120.0)
    animation_mode: EnumProperty(
        name='Animation Mode',
        items=W3D_STAGE_ANIM_ITEMS,
        default='LOOP')
    pass_hint: EnumProperty(
        name='Pass Hint',
        items=W3D_PASS_HINT_ITEMS,
        default='BASE_TEXTURE')
    alpha_bitmap: PointerProperty(name='Alpha Bitmap', type=bpy.types.Image)


class W3DShaderSettings(PropertyGroup):
    blend_mode: EnumProperty(
        name='Blend Mode',
        description='Named blend-mode preset from the classic W3D shader tab.',
        items=W3D_BLEND_MODE_ITEMS,
        default='0',
        update=lambda self, _context: _apply_blend_mode_preset(self))
    custom_src: EnumProperty(
        name='Source Blend',
        description='Source blend factor used by the shader blend equation.',
        items=W3D_SOURCE_BLEND_ITEMS,
        default='1',
        update=lambda self, _context: _sync_blend_mode_from_controls(self))
    custom_dest: EnumProperty(
        name='Destination Blend',
        description='Destination blend factor used by the shader blend equation.',
        items=W3D_DEST_BLEND_ITEMS,
        default='0',
        update=lambda self, _context: _sync_blend_mode_from_controls(self))
    write_z: BoolProperty(
        name='Write Z',
        description='Enable depth-buffer writes for this pass.',
        default=True,
        update=lambda self, _context: _sync_blend_mode_from_controls(self))
    alpha_test: BoolProperty(
        name='Alpha Test',
        description='Enable alpha testing for this pass.',
        default=False,
        update=lambda self, _context: _sync_blend_mode_from_controls(self))
    pri_gradient: EnumProperty(
        name='Primary Gradient',
        description='Control how diffuse lighting affects the first stage.',
        items=W3D_PRIMARY_GRADIENT_ITEMS,
        default='1')
    sec_gradient: EnumProperty(
        name='Secondary Gradient',
        description='Control whether specular-light contribution is enabled.',
        items=W3D_SECONDARY_GRADIENT_ITEMS,
        default='0')
    depth_compare: EnumProperty(
        name='Depth Compare',
        description='Choose how this pass compares against the Z buffer.',
        items=W3D_DEPTH_COMPARE_ITEMS,
        default='3')
    detail_color: EnumProperty(
        name='Detail Color Func',
        description='Choose how stage 1 color combines with stage 0.',
        items=W3D_DETAIL_COLOR_FUNC_ITEMS,
        default='0')
    detail_alpha: EnumProperty(
        name='Detail Alpha Func',
        description='Choose how stage 1 alpha combines with stage 0.',
        items=W3D_DETAIL_ALPHA_FUNC_ITEMS,
        default='0')


class W3DMaterialPass(PropertyGroup):
    name: StringProperty(name='Pass Name', default='Pass')
    ambient: FloatVectorProperty(
        name='Ambient',
        description='Color of the shaded portion of the mesh. For in-game vertex coloring, keep this equal to Diffuse when Emissive is black.',
        subtype='COLOR',
        size=4,
        default=(1.0, 1.0, 1.0, 1.0),
        min=0.0,
        max=1.0)
    diffuse: FloatVectorProperty(
        name='Diffuse',
        description='Base color reflected by lighting. For in-game vertex coloring, match Ambient when Emissive is black.',
        subtype='COLOR',
        size=4,
        default=(1.0, 1.0, 1.0, 1.0),
        min=0.0,
        max=1.0)
    specular: FloatVectorProperty(
        name='Specular',
        description='Specular highlight color. Classic W3D docs mark this as effectively disabled for most assets.',
        subtype='COLOR',
        size=3,
        default=(0.0, 0.0, 0.0),
        min=0.0,
        max=1.0)
    emissive: FloatVectorProperty(
        name='Emissive',
        description='Self-illuminated color. If Emissive is non-black, Ambient and Diffuse should usually be black for in-game vertex coloring.',
        subtype='COLOR',
        size=3,
        default=(0.0, 0.0, 0.0),
        min=0.0,
        max=1.0)
    specular_to_diffuse: BoolProperty(
        name='Specular to Diffuse',
        description='Obsolete legacy option. When enabled it exports the Copy Specular To Diffuse vertex-material flag.',
        default=False)
    opacity: FloatProperty(
        name='Opacity',
        description='1.0 is fully opaque and 0.0 is fully transparent. Visible transparency still depends on the shader blend mode.',
        default=1.0,
        min=0.0,
        max=1.0)
    translucency: FloatProperty(
        name='Translucency',
        description='Legacy translucency value kept for round-trip compatibility.',
        default=0.0,
        min=0.0,
        max=1.0)
    shininess: FloatProperty(
        name='Shininess',
        description='Controls the tightness of specular highlights in the vertex material.',
        default=0.0,
        min=0.0,
        max=100.0)
    stage0_mapping: EnumProperty(
        name='Stage 0 Mapping',
        description='Choose how stage 0 generates its texture coordinates.',
        items=W3D_STAGE0_MAPPING_ITEMS,
        default='0x00000000')
    stage1_mapping: EnumProperty(
        name='Stage 1 Mapping',
        description='Choose how stage 1 generates its texture coordinates.',
        items=W3D_STAGE1_MAPPING_ITEMS,
        default='0x00000000')
    stage0_args: StringProperty(
        name='Stage 0 Args',
        description='Comma-separated, case-sensitive mapper arguments for stage 0, for example UPerSec=-0.3, VPerSec=5.0.',
        default='')
    stage1_args: StringProperty(
        name='Stage 1 Args',
        description='Comma-separated, case-sensitive mapper arguments for stage 1, for example FPS=29.5, Log2Width=2.',
        default='')
    uv_channel_stage0: IntProperty(
        name='Stage 0 UV Channel',
        description='1-based UV channel used when the stage reads authored UV coordinates.',
        default=1,
        min=1,
        max=99)
    uv_channel_stage1: IntProperty(
        name='Stage 1 UV Channel',
        description='1-based UV channel used when the stage reads authored UV coordinates.',
        default=1,
        min=1,
        max=99)
    stage0: PointerProperty(name='Stage 0', type=W3DStageSettings)
    stage1: PointerProperty(name='Stage 1', type=W3DStageSettings)
    shader: PointerProperty(name='Shader Settings', type=W3DShaderSettings)


class W3DMaterialSettings(PropertyGroup):
    passes: CollectionProperty(type=W3DMaterialPass)
    active_pass_index: IntProperty(name='Active Pass', default=0, min=0)
    ui_pass_section: EnumProperty(
        name='Pass Tab',
        items=[
            ('VERTEX', 'Vertex Material', 'Show vertex material properties'),
            ('SHADER', 'Shader', 'Show shader properties'),
            ('TEXTURES', 'Textures', 'Show texture stage properties'),
        ],
        default='VERTEX')
    material_type: EnumProperty(
        name='Material Type',
        items=[
            ('SHADER_MATERIAL', 'Shader', 'Shader material.'),
            ('VERTEX_MATERIAL', 'Vertex', 'Vertex material.'),
            ('PRELIT_MATERIAL', 'Prelit', 'Prelit material.'),
        ],
        default='VERTEX_MATERIAL')
    surface_type: EnumProperty(
        name='Surface Type',
        items=[
            ('0', 'LightMetal', ''),
            ('1', 'HeavyMetal', ''),
            ('2', 'Water', ''),
            ('3', 'Sand', ''),
            ('4', 'Dirt', ''),
            ('5', 'Mud', ''),
            ('6', 'Grass', ''),
            ('7', 'Wood', ''),
            ('8', 'Concrete', ''),
            ('9', 'Flesh', ''),
            ('10', 'Rock', ''),
            ('11', 'Snow', ''),
            ('12', 'Ice', ''),
            ('13', 'Default', ''),
            ('14', 'Glass', ''),
            ('15', 'Cloth', ''),
            ('16', 'TiberiumField', ''),
            ('17', 'FoliagePermeable', ''),
            ('18', 'GlassPermeable', ''),
            ('19', 'IcePermeable', ''),
            ('20', 'ClothPermeable', ''),
            ('21', 'Electrical', ''),
            ('22', 'Flammable', ''),
            ('23', 'Steam', ''),
            ('24', 'ElectricalPermeable', ''),
            ('25', 'FlammablePermeable', ''),
            ('26', 'SteamPermeable', ''),
            ('27', 'WaterPermeable', ''),
            ('28', 'TiberiumWater', ''),
            ('29', 'TiberiumWaterPermeable', ''),
            ('30', 'UnderwaterDirt', ''),
            ('31', 'UnderwaterTiberiumDirt', ''),
        ],
        default='13')
    attributes: EnumProperty(
        name='Attributes',
        items=[
            ('DEFAULT', 'Default', ''),
            ('USE_DEPTH_CUE', 'Use Depth Cue', ''),
            ('ARGB_EMISSIVE_ONLY', 'ARGB Emissive Only', ''),
            ('COPY_SPECULAR_TO_DIFFUSE', 'Copy Specular To Diffuse', ''),
            ('DEPTH_CUE_TO_ALPHA', 'Depth Cue To Alpha', ''),
        ],
        options={'ENUM_FLAG'})


class W3DObjectSettings(PropertyGroup):
    export_transform: BoolProperty(name='Export Transform', default=True)
    export_geometry: BoolProperty(name='Export Geometry', default=True)
    hlod_role: EnumProperty(
        name='HLOD Role',
        description='Choose whether this object exports as regular geometry, an aggregate attachment, or a proxy attachment',
        items=W3D_HLOD_ROLE_ITEMS,
        default='LOD')
    hlod_identifier: StringProperty(
        name='Attachment Identifier',
        description='Exact identifier written to the HLOD aggregate/proxy array. Leave blank to use the object name; proxies strip everything after "~" so unique Blender suffixes do not affect export',
        default='')
    geometry_type: EnumProperty(
        name='Geometry Type',
        items=W3D_GEOMETRY_TYPE_ITEMS,
        default='NORMAL',
        update=_sync_object_type_from_settings)
    static_sort_level: IntProperty(name='Static Sort Level', default=0, min=0, max=32)
    screen_size: FloatProperty(name='Screen Size', default=1.0, min=0.0)
    dazzle_name: EnumProperty(
        name='Dazzle',
        items=get_dazzle_enum_items,
        default=0)
    geom_hide: BoolProperty(name='Hide', default=False)
    geom_two_sided: BoolProperty(name='Two Sided', default=False)
    geom_shadow: BoolProperty(name='Shadow', default=False)
    geom_vertex_alpha: BoolProperty(name='Vertex Alpha', default=False)
    geom_z_normal: BoolProperty(name='Z Normal', default=False)
    geom_shatter: BoolProperty(name='Shatter', default=False)
    geom_tangents: BoolProperty(name='Tangents', default=False)
    geom_keep_normals: BoolProperty(name='Keep Normals', default=False)
    geom_prelit: BoolProperty(name='Prelit', default=False)
    geom_always_dyn_light: BoolProperty(name='Always Dynamic Light', default=False)
    coll_physical: BoolProperty(name='Physical Collision', default=False)
    coll_projectile: BoolProperty(name='Projectile Collision', default=False)
    coll_vis: BoolProperty(name='Vis Collision', default=False)
    coll_camera: BoolProperty(name='Camera Collision', default=False)
    coll_vehicle: BoolProperty(name='Vehicle Collision', default=False)


class W3DSceneSettings(PropertyGroup):
    use_renegade_workflow: BoolProperty(
        name='Use Renegade workflow',
        description='Keep mesh object types in sync with the active W3D geometry context',
        default=False,
        update=_sync_scene_objects)


##########################################################################
# Mesh
##########################################################################

Mesh.userText = StringProperty(
    name='User Text',
    description='This is a text defined by the user',
    default='')

Mesh.sort_level = IntProperty(
    name='Sorting level',
    description='Objects with higher sorting level are rendered after objects with lower levels.',
    default=0,
    min=0,
    max=32)

Mesh.casts_shadow = BoolProperty(
    name='Casts shadow',
    description='Determines if this object casts a shadow',
    default=True)

Mesh.two_sided = BoolProperty(
    name='Two sided',
    description='Determines if this objects faces are visible from front AND back',
    default=False)

Mesh.object_type = EnumProperty(
    name='Type',
    description='Attributes that define the type of this object',
    items=[
        ('MESH', 'Mesh', 'desc: just a normal mesh'),
        ('BOX', 'Box', 'desc: this object defines a boundingbox'),
        ('DAZZLE', 'Dazzle', 'desc: todo'),
        ('GEOMETRY', 'Geometry', 'desc: defines a geometry object'),
        ('BONE_VOLUME', 'Bone Volume', 'desc: defines a bone volume object')],
    default='MESH')

Mesh.dazzle_type = EnumProperty(
    name='Dazzle Type',
    description='defines the dazzle type',
    items=[
        ('DEFAULT', 'default', 'desc: todo'),
        ('SUN', 'sun', 'desc: todo'),
        ('REN_L5_STREETLIGHT', 'Ren L5 streetlight', 'desc: todo'),
        ('REN_BRAKELIGHT', 'Ren brakelight', 'desc: todo'),
        ('REN_HEADLIGHT', 'Ren headlight', 'desc: todo'),
        ('REN_L5_REDLIGHT', 'Ren L5 redlight', 'desc: todo'),
        ('REN_NUKE', 'Ren nuke', 'desc: todo'),
        ('REN_BLINKLIGHT_RED', 'Ren blinklight red', 'desc: todo'),
        ('REN_BLINKLIGHT_WHITE', 'Ren blinklight white', 'desc: todo'),
        ('REN_VEHICLELIGHT_RED', 'Ren vehicle light red', 'desc: todo'),
        ('REN_VEHICLELIGHT_WHITE', 'Ren vehicle light white', 'desc: todo')],
    default='DEFAULT')

Mesh.geometry_type = EnumProperty(
    name='Geometry Type',
    description='defines the geometry type',
    items=[
        ('BOX', 'box', 'desc: box geometry'),
        ('SPHERE', 'sphere', 'desc: sphere geometry'),
        ('CYLINDER', 'cylinder', 'desc: cylinder geometry')],
    default='BOX')

Mesh.contact_points_type = EnumProperty(
    name='ContactPoints Type',
    description='defines the contact points type of this geometry',
    items=[
        ('NONE', 'none', 'desc: no geometry contact points'),
        ('VEHICLE', 'vehicle', 'desc: vehicle contact points'),
        ('STRUCTURE', 'structure', 'desc: structure contact points'),
        ('INFANTRY', 'infantry', 'desc: infantry contact points'),
        ('SQUAD_MEMBER', 'squad_member', 'desc: squad member contact points')],
    default='NONE')

Mesh.box_type = EnumProperty(
    name='Type',
    description='Attributes that define the type of this box object',
    items=[
        ('0', 'default', 'desc: todo'),
        ('1', 'Oriented', 'desc: todo'),
        ('2', 'Aligned', 'desc: todo')],
    default='0')

Mesh.box_collision_types = EnumProperty(
    name='Box Collision Types',
    description='Attributes that define the collision type of this box object',
    items=[
        ('DEFAULT', 'Default', 'desc: todo', 0),
        ('PHYSICAL', 'Physical', 'desc: physical collisions', 0x10),
        ('PROJECTILE', 'Projectile', 'desc: projectiles (rays) collide with this', 0x20),
        ('VIS', 'Vis', 'desc: vis rays collide with this mesh', 0x40),
        ('CAMERA', 'Camera', 'desc: cameras collide with this mesh', 0x80),
        ('VEHICLE', 'Vehicle', 'desc: vehicles collide with this mesh', 0x100)],
    default=set(),
    options={'ENUM_FLAG'})

Mesh.mass = IntProperty(
    name='Mass',
    description='The mass of this bone volume.',
    default=1,
    min=0,
    max=99999)

Mesh.spinniness = FloatProperty(
    name='Spinniness',
    default=0.0,
    min=0.0, max=100.0,
    description='Spinniness of this bone volume.')

Mesh.contact_tag = EnumProperty(
    name='Contact Tag',
    description='defines the contact tag type of this bone volume.',
    items=[
        ('DEBRIS', 'debris', 'desc: debris contact tag')],
    default='DEBRIS')

if bpy.app.version >= (4, 0, 0):
    class SurfaceType(bpy.types.PropertyGroup):
        value: bpy.props.IntProperty(default=0)

    bpy.utils.register_class(SurfaceType)

    class FaceMap(bpy.types.PropertyGroup):
        name: bpy.props.StringProperty(name="Face Map Name", default="Unknown")
        value: CollectionProperty(type=SurfaceType)

    bpy.utils.register_class(FaceMap)

    Mesh.face_maps = CollectionProperty(type=FaceMap)

##########################################################################
# PoseBone
##########################################################################

Bone.visibility = FloatProperty(
    name='Visibility',
    default=1.0,
    min=0.0, max=1.0,
    description='Visibility property')

##########################################################################
# Material
##########################################################################


Material.material_type = EnumProperty(
    name='Material Type',
    description='defines the type of the material',
    items=[
        ('SHADER_MATERIAL', 'Shader Material', 'desc: todo'),
        ('VERTEX_MATERIAL', 'Vertex Material', 'desc: todo'),
        ('PRELIT_MATERIAL', 'Prelit Material', 'desc: todo')],
    default='VERTEX_MATERIAL')

Material.prelit_type = EnumProperty(
    name='Prelit Type',
    description='defines the prelit type of the vertex material',
    items=[
        ('PRELIT_UNLIT', 'Prelit Unlit', 'desc: todo'),
        ('PRELIT_VERTEX', 'Prelit Vertex', 'desc: todo'),
        ('PRELIT_LIGHTMAP_MULTI_PASS', 'Prelit Lightmap multi Pass', 'desc: todo'),
        ('PRELIT_LIGHTMAP_MULTI_TEXTURE', 'Prelit Lightmap multi Texture', 'desc: todo')],
    default='PRELIT_UNLIT')

Material.attributes = EnumProperty(
    name='attributes',
    description='Attributes that define the behaviour of this material',
    items=[
        ('DEFAULT', 'Default', 'desc: todo', 0),
        ('USE_DEPTH_CUE', 'UseDepthCue', 'desc: todo', 1),
        ('ARGB_EMISSIVE_ONLY', 'ArgbEmissiveOnly', 'desc: todo', 2),
        ('COPY_SPECULAR_TO_DIFFUSE', 'CopySpecularToDiffuse', 'desc: todo', 4),
        ('DEPTH_CUE_TO_ALPHA', 'DepthCueToAlpha', 'desc: todo', 8)],
    default=set(),
    options={'ENUM_FLAG'})

Material.surface_type = EnumProperty(
    name='Surface type',
    description='Describes the surface type for this material',
    items=[
        ('0', 'LightMetal', 'desc: todo'),
        ('1', 'HeavyMetal', 'desc: todo'),
        ('2', 'Water', 'desc: todo'),
        ('3', 'Sand', 'desc: todo'),
        ('4', 'Dirt', 'desc: todo'),
        ('5', 'Mud', 'desc: todo'),
        ('6', 'Grass', 'desc: todo'),
        ('7', 'Wood', 'desc: todo'),
        ('8', 'Concrete', 'desc: todo'),
        ('9', 'Flesh', 'desc: todo'),
        ('10', 'Rock', 'desc: todo'),
        ('11', 'Snow', 'desc: todo'),
        ('12', 'Ice', 'desc: todo'),
        ('13', 'Default', 'desc: todo'),
        ('14', 'Glass', 'desc: todo'),
        ('15', 'Cloth', 'desc: todo'),
        ('16', 'TiberiumField', 'desc: todo'),
        ('17', 'FoliagePermeable', 'desc: todo'),
        ('18', 'GlassPermeable', 'desc: todo'),
        ('19', 'IcePermeable', 'desc: todo'),
        ('20', 'ClothPermeable', 'desc: todo'),
        ('21', 'Electrical', 'desc: todo'),
        ('22', 'Flammable', 'desc: todo'),
        ('23', 'Steam', 'desc: todo'),
        ('24', 'ElectricalPermeable', 'desc: todo'),
        ('25', 'FlammablePermeable', 'desc: todo'),
        ('26', 'SteamPermeable', 'desc: todo'),
        ('27', 'WaterPermeable', 'desc: todo'),
        ('28', 'TiberiumWater', 'desc: todo'),
        ('29', 'TiberiumWaterPermeable', 'desc: todo'),
        ('30', 'UnderwaterDirt', 'desc: todo'),
        ('31', 'UnderwaterTiberiumDirt', 'desc: todo')],
    default='13')


Material.translucency = FloatProperty(
    name='Translucency',
    default=0.0,
    min=0.0, max=1.0,
    description='Translucency property')

Material.stage0_mapping = EnumProperty(
    name='Stage 0 Mapping',
    description='defines the stage mapping type of this material',
    items=W3D_STAGE0_MAPPING_ITEMS,
    default='0x00000000')

Material.stage1_mapping = EnumProperty(
    name='Stage 1 Mapping',
    description='defines the stage mapping type of this material',
    items=W3D_STAGE1_MAPPING_ITEMS,
    default='0x00000000')

Material.vm_args_0 = StringProperty(
    name='vm_args_0',
    description='Vertex Material Arguments 0',
    default='')

Material.vm_args_1 = StringProperty(
    name='vm_args_1',
    description='Vertex Material Arguments 1',
    default='')

Material.technique = IntProperty(
    name='Technique',
    description='Dont know yet',
    default=0,
    min=0,
    max=1)

Material.ambient = FloatVectorProperty(
    name='Ambient',
    subtype='COLOR',
    size=4,
    default=(1.0, 1.0, 1.0, 0.0),
    min=0.0, max=1.0,
    description='Ambient color')

Material.specular = FloatVectorProperty(
    name='Specular',
    subtype='COLOR',
    size=3,
    default=(0.0, 0.0, 0.0),
    min=0.0, max=1.0,
    description='Specular color')

Material.alpha_test = BoolProperty(
    name='Alpha test',
    description='Enable the alpha test',
    default=True)

Material.blend_mode = IntProperty(
    name='Blend mode',
    description='Which blend mode should be used',
    default=0,
    min=0,
    max=8)

Material.bump_uv_scale = FloatVectorProperty(
    name='Bump UV Scale',
    subtype='TRANSLATION',
    size=2,
    default=(0.0, 0.0),
    min=0.0, max=1.0,
    description='Bump uv scale')

Material.edge_fade_out = FloatProperty(
    name='Edge fade out',
    description='TODO',
    default=0,
    min=0,
    max=5)

Material.depth_write = BoolProperty(
    name='Depth write',
    description='Todo',
    default=False)

Material.sampler_clamp_uv_no_mip_0 = FloatVectorProperty(
    name='Sampler clamp UV no MIP 0',
    subtype='TRANSLATION',
    size=4,
    default=(0.0, 0.0, 0.0, 0.0),
    min=0.0, max=1.0,
    description='Sampler clampU clampV no mipmap 0')

Material.sampler_clamp_uv_no_mip_1 = FloatVectorProperty(
    name='Sampler clamp UV no MIP 1',
    subtype='TRANSLATION',
    size=4,
    default=(0.0, 0.0, 0.0, 0.0),
    min=0.0, max=1.0,
    description='Sampler clampU clampV no mipmap 1')

Material.num_textures = IntProperty(
    name='NumTextures',
    description='TODO',
    default=0,
    min=0,
    max=5)

Material.texture_1 = StringProperty(
    name='Texture 1',
    description='TODO',
    default='')

Material.damaged_texture = StringProperty(
    name='Damaged Texture',
    description='This texture works with the second uv map. In game, once a certain contact point bone is hit, the bounded vertices will show additional alpha channel with this texture to display damage effects (i.e, holes in the building).',
    default='')

Material.secondary_texture_blend_mode = IntProperty(
    name='Secondary texture blend mode',
    description='TODO',
    default=0,
    min=0,
    max=5)

Material.tex_coord_mapper_0 = IntProperty(
    name='TexCoord mapper 0',
    description='TODO',
    default=0,
    min=0,
    max=5)

Material.tex_coord_mapper_1 = IntProperty(
    name='TexCoord mapper 1',
    description='TODO',
    default=0,
    min=0,
    max=5)

Material.tex_coord_transform_0 = FloatVectorProperty(
    name='TexCoord transform 0',
    subtype='TRANSLATION',
    size=4,
    default=(0.0, 0.0, 0.0, 0.0),
    min=0.0, max=1.0,
    description='TODO')

Material.tex_coord_transform_1 = FloatVectorProperty(
    name='TexCoord transform 1',
    subtype='TRANSLATION',
    size=4,
    default=(0.0, 0.0, 0.0, 0.0),
    min=0.0, max=1.0,
    description='TODO')

Material.environment_texture = StringProperty(
    name='Environment texture',
    description='TODO',
    default='')

Material.environment_mult = FloatProperty(
    name='Environment mult',
    default=0.0,
    min=0.0, max=1.0,
    description='Todo')

Material.recolor_texture = StringProperty(
    name='Recolor texture',
    description='TODO',
    default='')

Material.recolor_mult = FloatProperty(
    name='Recolor mult',
    default=0.0,
    min=0.0, max=1.0,
    description='Todo')

Material.use_recolor = BoolProperty(
    name='Use recolor colors',
    description='Todo',
    default=False)

Material.house_color_pulse = BoolProperty(
    name='House color pulse',
    description='Todo',
    default=False)

Material.scrolling_mask_texture = StringProperty(
    name='Scrolling mask texture',
    description='TODO',
    default='')

Material.tex_coord_transform_angle = FloatProperty(
    name='Texture coord transform angle',
    default=0.0,
    min=0.0, max=1.0,
    description='Todo')

Material.tex_coord_transform_u_0 = FloatProperty(
    name='Texture coord transform u 0',
    default=0.0,
    min=0.0, max=1.0,
    description='Todo')

Material.tex_coord_transform_v_0 = FloatProperty(
    name='Texture coord transform v 0',
    default=0.0,
    min=0.0, max=1.0,
    description='Todo')

Material.tex_coord_transform_u_1 = FloatProperty(
    name='Texture coord transform u 0',
    default=0.0,
    min=0.0, max=1.0,
    description='Todo')

Material.tex_coord_transform_v_1 = FloatProperty(
    name='Texture coord transform v 0',
    default=0.0,
    min=0.0, max=1.0,
    description='Todo')

Material.tex_coord_transform_u_2 = FloatProperty(
    name='Texture coord transform u 0',
    default=0.0,
    min=0.0, max=1.0,
    description='Todo')

Material.tex_coord_transform_v_2 = FloatProperty(
    name='Texture coord transform v 0',
    default=0.0,
    min=0.0, max=1.0,
    description='Todo')

Material.tex_ani_fps_NPR_lastFrame_frameOffset_0 = FloatVectorProperty(
    name='TextureAnimation FPS NumPerRow LastFrame FrameOffset 0',
    subtype='TRANSLATION',
    size=4,
    default=(0.0, 0.0, 0.0, 0.0),
    min=0.0, max=1.0,
    description='TODO')

Material.ion_hull_texture = StringProperty(
    name='Ion hull texture',
    description='TODO',
    default='')

Material.multi_texture_enable = BoolProperty(
    name='Multi texture enable',
    description='Todo',
    default=False)

##########################################################################
# Material.Shader
##########################################################################


class ShaderProperties(PropertyGroup):
    depth_compare: EnumProperty(
        name='Depth Compare',
        description='Describes how to depth check this material',
        items=W3D_DEPTH_COMPARE_ITEMS,
        default='3')

    depth_mask: EnumProperty(
        name='Write Depthmask',
        description='Wether or not to store the depthmask',
        items=[
            ('0', 'DISABLE', 'disable depth buffer writes'),
            ('1', 'ENABLE', 'enable depth buffer writes (default)')],
        default='1')

    color_mask: IntProperty(min=0, max=255, name='Color Mask')

    dest_blend: EnumProperty(
        name='Destination Blendfunc',
        description='Describes how this material blends',
        items=W3D_DEST_BLEND_ITEMS,
        default='0')

    fog_func: IntProperty(min=0, max=255, name='Fog function')

    pri_gradient: EnumProperty(
        name='Primary Gradient',
        description='Specify the primary gradient',
        items=W3D_PRIMARY_GRADIENT_ITEMS,
        default='1')

    sec_gradient: EnumProperty(
        name='Secondary Gradient',
        description='Specify the primary gradient',
        items=W3D_SECONDARY_GRADIENT_ITEMS,
        default='0')

    src_blend: EnumProperty(
        name='Source Blendfunc',
        description='Describes how this material blends',
        items=W3D_SOURCE_BLEND_ITEMS,
        default='1')

    detail_color_func: EnumProperty(
        name='Detail color function',
        items=W3D_DETAIL_COLOR_FUNC_ITEMS,
        default='0')

    detail_alpha_func: EnumProperty(
        name='Detail alpha function',
        items=W3D_DETAIL_ALPHA_FUNC_ITEMS,
        default='0')

    shader_preset: IntProperty(min=0, max=255, name="Shader presets")

    alpha_test: EnumProperty(
        name='Alpha test',
        description='Specify wether or not to alpha check',
        items=[
            ('0', 'Disable', 'disable alpha testing (default)'),
            ('1', 'Enable', 'enable alpha testing')],
        default='0')

    post_detail_color_func: EnumProperty(
        name='Post-Detail color function',
        items=[
            ('0', 'Disable', 'local (default)'),
            ('1', 'Detail', 'other'),
            ('2', 'Scale', 'local * other'),
            ('3', 'InvScale', '~(~local * ~other) = local + (1-local)*other'),
            ('4', 'Add', 'local + other'),
            ('5', 'Sub', 'local - other'),
            ('6', 'SubR', 'other - local'),
            ('7', 'Blend', '(localAlpha)*local + (~localAlpha)*other'),
            ('8', 'DetailBlend', '(otherAlpha)*local + (~otherAlpha)*other'),
            ('9', 'Alt', ''),
            ('10', 'DetailAlt', ''),
            ('11', 'ScaleAlt', ''),
            ('12', 'InvScaleAlt', ''),
        ],
        default='0')

    post_detail_alpha_func: EnumProperty(
        name='Post-Detail alpha function',
        items=[
            ('0', 'Disable', 'local (default)'),
            ('1', 'Detail', 'other'),
            ('2', 'Scale', 'local * other'),
            ('3', 'InvScale', '~(~local * ~other) = local + (1-local)*other'),
        ],
        default='0')
