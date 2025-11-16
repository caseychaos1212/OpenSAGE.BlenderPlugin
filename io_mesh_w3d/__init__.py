# <pep8 compliant>
# Written by Stephan Vedder and Michael Schnabel

import bpy
from bpy.props import (
    PointerProperty,
    BoolProperty,
    EnumProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Panel
from bpy_extras import node_shader_utils
from bpy_extras.io_utils import ImportHelper, ExportHelper
from io_mesh_w3d.utils import ReportHelper
from io_mesh_w3d.export_utils import save_data
from io_mesh_w3d.custom_properties import *
from io_mesh_w3d.geometry_export import *
from io_mesh_w3d.bone_volume_export import *
from io_mesh_w3d.common.utils.material_settings_bridge import apply_pass_to_material

from io_mesh_w3d.blender_addon_updater import addon_updater_ops

_ADDON_UPDATER_REGISTERED = False

W3D_PRESETS = [
    {
        'id': 'TERRAIN_BILLBOARD',
        'name': 'Terrain Billboard',
        'description': 'Camera-parallel billboard suited for foliage/billboards.',
        'mesh': {'object_type': 'MESH', 'sort_level': 0, 'casts_shadow': False, 'two_sided': True},
        'settings': {
            'geometry_type': 'CAM_PARAL',
            'export_geometry': True,
            'export_transform': False,
            'geom_two_sided': True,
            'geom_shadow': False,
            'geom_vertex_alpha': False,
            'coll_physical': False,
            'coll_projectile': False,
            'coll_vis': False,
            'coll_camera': False,
            'coll_vehicle': False,
        },
    },
    {
        'id': 'DAZZLE_LIGHT',
        'name': 'Dazzle Light',
        'description': 'Standard Renegade dazzle sprite settings.',
        'mesh': {'object_type': 'DAZZLE'},
        'settings': {
            'geometry_type': 'DAZZLE',
            'export_geometry': True,
            'export_transform': False,
            'geom_two_sided': True,
            'geom_vertex_alpha': False,
            'coll_physical': False,
            'coll_projectile': False,
            'coll_vis': False,
            'coll_camera': False,
            'coll_vehicle': False,
        },
    },
    {
        'id': 'COLLISION_BOX',
        'name': 'Collision Box',
        'description': 'Physical collision box used for structures.',
        'mesh': {'object_type': 'BOX', 'box_type': '0'},
        'settings': {
            'geometry_type': 'NORMAL',
            'export_geometry': True,
            'coll_physical': True,
            'coll_projectile': True,
            'coll_vis': True,
            'coll_camera': True,
            'coll_vehicle': True,
        },
    },
]

W3D_PRESET_ENUM = [(preset['id'], preset['name'], preset['description']) for preset in W3D_PRESETS]

VERSION = (0, 8, 1)

bl_info = {
    'name': 'Import/Export Westwood W3D Format (.w3d/.w3x)',
    'author': 'OpenW3D Team (built on the work of the OpenSAGE developers)',
    'version': (0, 8, 1),
    "blender": (2, 90, 0),
    'location': 'File > Import/Export > Westwood W3D (.w3d/.w3x)',
    'description': 'Import or Export the Westwood W3D-Format (.w3d/.w3x)',
    'warning': 'Still in Progress',
    'doc_url': 'https://github.com/OpenSAGE/OpenSAGE.BlenderPlugin',
    'tracker_url': 'https://github.com/OpenSAGE/OpenSAGE.BlenderPlugin/issues',
    'support': 'OFFICIAL',
    'category': 'Import-Export'}


def print_version(info):
    version = str(VERSION).replace('(', '').replace(')', '')
    version = version.replace(',', '.').replace(' ', '')
    info(f'plugin version: {version}  unofficial')


def ensure_object_mode(context):
    if context.mode == 'OBJECT':
        return True
    try:
        bpy.ops.object.mode_set(mode='OBJECT')
        return True
    except Exception:
        return False


def select_with_predicate(context, predicate):
    ensure_object_mode(context)
    scene = context.scene
    view_layer = context.view_layer
    active_obj = None
    for obj in scene.objects:
        try:
            obj.select_set(False)
        except Exception:
            continue
    for obj in scene.objects:
        if predicate(obj):
            try:
                obj.select_set(True)
            except Exception:
                continue
            if active_obj is None:
                active_obj = obj
    if active_obj is not None:
        view_layer.objects.active = active_obj
        return True
    return False


def _object_has_alpha_material(obj):
    if obj.type != 'MESH':
        return False
    for slot in obj.material_slots:
        mat = slot.material
        if not mat:
            continue
        if getattr(mat, 'blend_method', 'OPAQUE') != 'OPAQUE':
            return True
        settings = getattr(mat, 'w3d_material_settings', None)
        if settings and len(settings.passes) > 0:
            for m_pass in settings.passes:
                if (m_pass.stage0 and m_pass.stage0.alpha_bitmap) or (m_pass.stage1 and m_pass.stage1.alpha_bitmap):
                    return True
    return False


def _iter_w3d_materials(context):
    """Yield unique materials from the current selection (fallback to the active material)."""
    seen = set()
    for obj in getattr(context, 'selected_objects', []):
        if obj.type != 'MESH':
            continue
        for slot in obj.material_slots:
            mat = slot.material
            if mat is None:
                continue
            if getattr(mat, 'w3d_material_settings', None) is None:
                continue
            ident = id(mat)
            if ident in seen:
                continue
            seen.add(ident)
            yield mat

    obj = getattr(context, 'object', None)
    mat = getattr(obj, 'active_material', None) if obj else None
    settings = getattr(mat, 'w3d_material_settings', None) if mat else None
    if settings is not None:
        ident = id(mat)
        if ident not in seen:
            seen.add(ident)
            yield mat


def _find_display_stage(settings):
    """Return the first (pass_index, stage_name, pass_settings, stage_settings) with display enabled."""
    for pass_index, mat_pass in enumerate(settings.passes):
        for stage_name in ('stage0', 'stage1'):
            stage = getattr(mat_pass, stage_name, None)
            if stage is not None and stage.display:
                return pass_index, stage_name, mat_pass, stage
    return None


def _sync_material_display(material):
    """Apply the display-enabled stage texture to the Blender material graph."""
    settings = getattr(material, 'w3d_material_settings', None)
    if settings is None or not settings.passes:
        return False, 'NO_SETTINGS'

    selection = _find_display_stage(settings)
    if selection is None:
        return False, 'NO_DISPLAY_STAGE'

    pass_index, stage_name, pass_settings, stage_settings = selection
    if not stage_settings.enabled or stage_settings.texture is None:
        return False, 'NO_TEXTURE'

    apply_pass_to_material(material, settings, pass_settings)

    material.use_nodes = True
    principled = node_shader_utils.PrincipledBSDFWrapper(material, is_readonly=False)
    principled.base_color_texture.image = stage_settings.texture

    for idx, mat_pass in enumerate(settings.passes):
        for other_stage in ('stage0', 'stage1'):
            stage = getattr(mat_pass, other_stage, None)
            if stage is None:
                continue
            stage.display = (idx == pass_index and other_stage == stage_name)

    settings.active_pass_index = pass_index
    return True, None


def _collect_objects_with_children(context, include_children):
    result = []
    seen = set()

    def append_with_children(obj):
        if obj in seen:
            return
        seen.add(obj)
        result.append(obj)
        if include_children:
            for child in obj.children:
                append_with_children(child)

    for obj in context.selected_objects:
        append_with_children(obj)
    return result


def copy_object_settings(source_obj, target_obj):
    src_settings = getattr(source_obj, 'w3d_object_settings', None)
    dst_settings = getattr(target_obj, 'w3d_object_settings', None)
    if src_settings is None or dst_settings is None:
        return False
    for prop in src_settings.bl_rna.properties:
        identifier = prop.identifier
        if identifier in {'rna_type'}:
            continue
        setattr(dst_settings, identifier, getattr(src_settings, identifier))
    return True


def apply_preset_to_object(obj, preset_def):
    mesh = getattr(obj, 'data', None)
    settings = getattr(obj, 'w3d_object_settings', None)
    if mesh is None or settings is None:
        return False
    mesh_overrides = preset_def.get('mesh', {})
    for attr, value in mesh_overrides.items():
        if hasattr(mesh, attr):
            setattr(mesh, attr, value)
    setting_overrides = preset_def.get('settings', {})
    for attr, value in setting_overrides.items():
        if hasattr(settings, attr):
            setattr(settings, attr, value)
    return True


def _clamp_frame_start(self, _context):
    if self.animation_frame_start > self.animation_frame_end:
        self.animation_frame_end = self.animation_frame_start


def _clamp_frame_end(self, _context):
    if self.animation_frame_end < self.animation_frame_start:
        self.animation_frame_start = self.animation_frame_end


class ExportW3D(bpy.types.Operator, ExportHelper, ReportHelper):
    """Export to Westwood 3D file format (.w3d/.w3x)"""
    bl_idname = 'export_mesh.westwood_w3d'
    bl_label = 'Export W3D/W3X'
    bl_options = {'UNDO', 'PRESET'}

    filename_ext = ''

    filter_glob: StringProperty(default='*.w3d;*.w3x', options={'HIDDEN'})

    file_format: bpy.props.EnumProperty(
        name="Format",
        items=(
            ('W3D',
             'Westwood 3D Binary (.w3d)',
             'Exports to W3D format, which was used in earlier SAGE games.'
             'Namely Command and Conquer Generals and the Battle for Middleearth series'),
            ('W3X',
             'Westwood 3D XML (.w3x)',
             'Exports to W3X format, which was used in later SAGE games.'
             'Namely everything starting from Command and Conquer 3')),
        description="Select the export file format",
        default='W3D')

    export_mode: EnumProperty(
        name='Mode',
        items=(
            ('HM',
             'Hierarchical Model',
             'This will export all the meshes of the scene with hierarchy/skeleton data'),
            ('HAM',
             'Hierarchical Animated Model',
             'This will export all the meshes of the scene with hierarchy/skeleton and animation data'),
            ('A',
             'Animation',
             'This will export the animation without any geometry or hierarchy/skeleton data'),
            ('H',
             'Hierarchy',
             'This will export the hierarchy/skeleton without any geometry or animation data'),
            ('M',
             'Mesh',
             'This will export a simple mesh (only the first of the scene if there are multiple), \
                without any hierarchy/skeleton and animation data'),
            ('TERRAIN',
             'Terrain',
             'This will export the geometry using the Renegade terrain format')),
        description='Select the export mode',
        default='HM')

    use_existing_skeleton: BoolProperty(
        name='Use existing skeleton', description='Use an already existing skeleton (.skn)', default=False)

    animation_compression: EnumProperty(
        name='Compression',
        items=(('U', 'Uncompressed', 'This will not compress the animations'),
               ('TC', 'TimeCoded', 'This will export the animation with keyframes'),
               # ('AD', 'AdaptiveDelta',
               # 'This will use adaptive delta compression to reduce size'),
               ),
        description='The method used for compressing the animation data',
        default='U')

    force_vertex_materials: BoolProperty(
        name='Force Vertex Materials', description='Export all materials as Vertex Materials only', default=False)

    individual_files: BoolProperty(
        name='Individual files',
        description='Creates an individual file for each mesh, boundingbox and the hierarchy',
        default=False)

    create_texture_xmls: BoolProperty(
        name='Create texture xml files', description='Creates an .xml file for each used texture', default=False)

    smooth_vertex_normals: BoolProperty(
        name='Smooth vertex normals across meshes',
        description='Match vertex normals along mesh seams before exporting',
        default=True)

    optimize_collision: BoolProperty(
        name='Optimise collision detection',
        description='Apply collision-optimisation heuristics before export',
        default=True)

    deduplicate_reference_meshes: BoolProperty(
        name='Eliminate duplicate reference meshes',
        description='Remove duplicate reference meshes before export',
        default=False)

    build_new_aabtree: BoolProperty(
        name='Export new AABTree',
        description='Force regeneration of the AABTree chunk',
        default=True)

    existing_skeleton_path: StringProperty(
        name='Existing skeleton',
        description='Path to an existing .w3d skeleton file',
        subtype='FILE_PATH',
        default='')

    animation_frame_start: IntProperty(
        name='Frame start',
        description='First frame exported to the animation',
        default=0,
        min=0,
        update=_clamp_frame_start)

    animation_frame_end: IntProperty(
        name='Frame end',
        description='Last frame exported to the animation',
        default=0,
        min=0,
        update=_clamp_frame_end)

    export_review_log: BoolProperty(
        name='Review export log',
        description='Display a popup with all export log messages when the process completes',
        default=False)

    will_save_settings: BoolProperty(default=False)

    PERSISTED_PROPS = (
        'file_format',
        'export_mode',
        'use_existing_skeleton',
        'existing_skeleton_path',
        'animation_compression',
        'force_vertex_materials',
        'individual_files',
        'create_texture_xmls',
        'smooth_vertex_normals',
        'optimize_collision',
        'deduplicate_reference_meshes',
        'build_new_aabtree',
        'animation_frame_start',
        'animation_frame_end',
        'export_review_log',
    )

    scene_key = 'w3dExportSettings'

    def invoke(self, context, event):
        settings = context.scene.get(self.scene_key)
        scene = context.scene
        self.animation_frame_start = scene.frame_start
        self.animation_frame_end = scene.frame_end
        self.will_save_settings = False
        if settings:
            try:
                for (k, v) in settings.items():
                    setattr(self, k, v)
                self.will_save_settings = True

            except (AttributeError, TypeError):
                self.error('Loading export settings failed. Removed corrupted settings.')
                del context.scene[self.scene_key]

        return ExportHelper.invoke(self, context, event)

    def save_settings(self, context):
        export_props = {prop: getattr(self, prop) for prop in self.PERSISTED_PROPS}
        context.scene[self.scene_key] = export_props

    def execute(self, context):
        print_version(self.info)
        if self.will_save_settings:
            self.save_settings(context)

        self._w3d_log_buffer = [] if self.export_review_log else None

        export_settings = {
            'mode': self.export_mode,
            'compression': self.animation_compression,
            'use_existing_skeleton': self.use_existing_skeleton,
            'individual_files': self.individual_files,
            'create_texture_xmls': self.create_texture_xmls,
            'smooth_vertex_normals': self.smooth_vertex_normals,
            'optimize_collision': self.optimize_collision,
            'deduplicate_reference_meshes': self.deduplicate_reference_meshes,
            'build_new_aabtree': self.build_new_aabtree,
            'existing_skeleton_path': self.existing_skeleton_path if self.use_existing_skeleton else '',
            'force_vertex_materials': self.force_vertex_materials,
            'frame_range': (self.animation_frame_start, self.animation_frame_end),
        }

        result = save_data(self, export_settings)

        if self.export_review_log and self._w3d_log_buffer is not None:
            log_text = '\n'.join(self._w3d_log_buffer) if self._w3d_log_buffer else 'No messages recorded.'
            bpy.ops.w3d.show_export_log('INVOKE_DEFAULT', log_text=log_text)

        self._w3d_log_buffer = None
        return result

    def draw(self, _context):
        self.draw_general_settings()
        geometry_mode = ('M' in self.export_mode) or (self.export_mode == 'TERRAIN')
        if geometry_mode:
            self.draw_processing_settings()

        if self.export_mode in {'HM', 'HAM', 'A'}:
            self.draw_use_existing_skeleton()
            if self.file_format == 'W3X' and self.export_mode == 'HM':
                self.draw_individual_files()

        if self.file_format == 'W3X' and (('M' in self.export_mode) or self.export_mode == 'TERRAIN'):
            self.draw_create_texture_xmls()

        if self.file_format == 'W3D' and (('M' in self.export_mode) or self.export_mode == 'TERRAIN'):
            self.draw_force_vertex_materials()

        if (self.export_mode == 'A' or self.export_mode == 'HAM') \
                and not self.file_format == 'W3X':
            self.draw_animation_settings()

    def draw_general_settings(self):
        col = self.layout.box().column()
        col.prop(self, 'file_format')
        col = self.layout.box().column()
        col.prop(self, 'export_mode')
        col.prop(self, 'export_review_log')

    def draw_processing_settings(self):
        col = self.layout.box().column()
        col.label(text='Geometry Processing')
        col.prop(self, 'smooth_vertex_normals')
        col.prop(self, 'optimize_collision')
        col.prop(self, 'deduplicate_reference_meshes')
        col.prop(self, 'build_new_aabtree')

    def draw_use_existing_skeleton(self):
        col = self.layout.box().column()
        col.prop(self, 'use_existing_skeleton')
        if self.use_existing_skeleton:
            col.prop(self, 'existing_skeleton_path')

    def draw_animation_settings(self):
        col = self.layout.box().column()
        col.prop(self, 'animation_compression')
        col.prop(self, 'animation_frame_start')
        col.prop(self, 'animation_frame_end')

    def draw_force_vertex_materials(self):
        col = self.layout.box().column()
        col.prop(self, 'force_vertex_materials')

    def draw_individual_files(self):
        col = self.layout.box().column()
        col.prop(self, 'individual_files')

    def draw_create_texture_xmls(self):
        col = self.layout.box().column()
        col.prop(self, 'create_texture_xmls')


class ImportW3D(bpy.types.Operator, ImportHelper, ReportHelper):
    """Import from Westwood 3D file format (.w3d/.w3x)"""
    bl_idname = 'import_mesh.westwood_w3d'
    bl_label = 'Import W3D/W3X'
    bl_options = {'UNDO'}

    file_format = ''

    filter_glob: StringProperty(default='*.w3d;*.w3x', options={'HIDDEN'})
    keep_rigid_meshes_static: BoolProperty(
        name='Keep rigid meshes static',
        description='Reuse existing rigid meshes instead of reparenting them when importing animation data',
        default=False)

    def execute(self, context):
        print_version(self.info)
        if self.filepath.lower().endswith('.w3d'):
            from .w3d.import_w3d import load
            file_format = 'W3D'
            load(self)
        else:
            from .w3x.import_w3x import load
            file_format = 'W3X'
            load(self)

        self.info('finished')
        return {'FINISHED'}

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'keep_rigid_meshes_static')


class W3D_OT_show_export_log(bpy.types.Operator):
    bl_idname = 'w3d.show_export_log'
    bl_label = 'W3D Export Log'
    bl_description = 'Display the messages emitted during the last W3D export'

    log_text: StringProperty(options={'HIDDEN'})

    def invoke(self, context, event):
        width = min(900, max(320, 12 * max(20, len(self.log_text.splitlines())) // 4))
        return context.window_manager.invoke_popup(self, width=width)

    def draw(self, _context):
        layout = self.layout
        box = layout.box()
        if not self.log_text:
            box.label(text='No messages recorded.')
            return
        for line in self.log_text.splitlines():
            box.label(text=line)

class W3D_UL_material_passes(bpy.types.UIList):
    bl_idname = 'W3D_UL_material_passes'

    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.prop(item, 'name', text='', emboss=False, icon='SHADING_RENDERED')
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text=item.name[:6] if item.name else 'Pass')


class W3D_OT_material_pass_add(bpy.types.Operator):
    bl_idname = 'w3d.material_pass_add'
    bl_label = 'Add W3D Material Pass'
    bl_description = 'Add a new W3D material pass'

    def execute(self, context):
        mat = getattr(context.object, 'active_material', None) if context.object else None
        if not mat:
            self.report({'WARNING'}, 'No active material')
            return {'CANCELLED'}
        settings = getattr(mat, 'w3d_material_settings', None)
        if settings is None:
            self.report({'WARNING'}, 'Material missing W3D settings property')
            return {'CANCELLED'}
        new_pass = settings.passes.add()
        new_pass.name = f'Pass {len(settings.passes)}'
        settings.active_pass_index = len(settings.passes) - 1
        return {'FINISHED'}


class W3D_OT_material_pass_remove(bpy.types.Operator):
    bl_idname = 'w3d.material_pass_remove'
    bl_label = 'Remove W3D Material Pass'
    bl_description = 'Remove the selected W3D material pass'

    def execute(self, context):
        mat = getattr(context.object, 'active_material', None) if context.object else None
        if not mat:
            self.report({'WARNING'}, 'No active material')
            return {'CANCELLED'}
        settings = getattr(mat, 'w3d_material_settings', None)
        if settings is None or len(settings.passes) == 0:
            self.report({'WARNING'}, 'Nothing to remove')
            return {'CANCELLED'}
        index = settings.active_pass_index
        settings.passes.remove(index)
        settings.active_pass_index = max(0, index - 1)
        return {'FINISHED'}


class W3D_OT_material_pass_move(bpy.types.Operator):
    bl_idname = 'w3d.material_pass_move'
    bl_label = 'Move W3D Material Pass'
    bl_description = 'Move the selected W3D material pass'

    direction: EnumProperty(
        name='Direction',
        items=(
            ('UP', 'Up', 'Move pass up'),
            ('DOWN', 'Down', 'Move pass down'),
        ),
        default='UP')

    def execute(self, context):
        mat = getattr(context.object, 'active_material', None) if context.object else None
        if not mat:
            self.report({'WARNING'}, 'No active material')
            return {'CANCELLED'}
        settings = getattr(mat, 'w3d_material_settings', None)
        count = len(settings.passes) if settings else 0
        if count < 2:
            return {'CANCELLED'}
        index = settings.active_pass_index
        new_index = index + (-1 if self.direction == 'UP' else 1)
        new_index = max(0, min(count - 1, new_index))
        if new_index == index:
            return {'CANCELLED'}
        settings.passes.move(index, new_index)
        settings.active_pass_index = new_index
        return {'FINISHED'}


class W3D_OT_apply_stage_display(bpy.types.Operator):
    bl_idname = 'w3d.apply_stage_display'
    bl_label = 'Push Display Texture'
    bl_description = 'Apply the Display-enabled W3D stage texture to the Blender material graph for the current selection'
    bl_options = {'UNDO'}

    def execute(self, context):
        materials = list(_iter_w3d_materials(context))
        if not materials:
            self.report({'WARNING'}, 'Select at least one W3D material')
            return {'CANCELLED'}

        updated = 0
        missing_texture = []
        missing_stage = []

        for mat in materials:
            success, error_code = _sync_material_display(mat)
            if success:
                updated += 1
                continue
            if error_code == 'NO_TEXTURE':
                missing_texture.append(mat.name)
            elif error_code == 'NO_DISPLAY_STAGE':
                missing_stage.append(mat.name)

        if updated == 0:
            if missing_texture:
                self.report({'WARNING'}, 'Display stage requires an enabled bitmap before it can be applied')
            else:
                self.report({'WARNING'}, 'No materials had Display enabled stages')
            return {'CANCELLED'}

        info_msg = f'Updated {updated} material(s)'
        skipped = len(missing_texture) + len(missing_stage)
        if skipped:
            info_msg += f'; skipped {skipped}'
        self.report({'INFO'}, info_msg)
        return {'FINISHED'}


class W3D_OT_select_bones(bpy.types.Operator):
    bl_idname = 'w3d.select_bones'
    bl_label = 'Select Bones'
    bl_description = 'Select all armature objects that represent bones'

    def execute(self, context):
        if select_with_predicate(context, lambda obj: obj.type == 'ARMATURE'):
            return {'FINISHED'}
        self.report({'INFO'}, 'No armatures found in scene')
        return {'CANCELLED'}


class W3D_OT_select_geometry(bpy.types.Operator):
    bl_idname = 'w3d.select_geometry'
    bl_label = 'Select Geometry'
    bl_description = 'Select all mesh objects marked for geometry export'

    def execute(self, context):
        def predicate(obj):
            if obj.type != 'MESH':
                return False
            settings = getattr(obj, 'w3d_object_settings', None)
            return settings is not None and settings.export_geometry

        if select_with_predicate(context, predicate):
            return {'FINISHED'}
        self.report({'INFO'}, 'No W3D geometry objects found')
        return {'CANCELLED'}


class W3D_OT_select_alpha_meshes(bpy.types.Operator):
    bl_idname = 'w3d.select_alpha_meshes'
    bl_label = 'Select Alpha Meshes'
    bl_description = 'Select meshes that use alpha-enabled materials'

    def execute(self, context):
        if select_with_predicate(context, _object_has_alpha_material):
            return {'FINISHED'}
        self.report({'INFO'}, 'No alpha meshes detected')
        return {'CANCELLED'}


class W3D_OT_select_collision_objects(bpy.types.Operator):
    bl_idname = 'w3d.select_collision_objects'
    bl_label = 'Select Collision Objects'
    bl_description = 'Select meshes that use the given collision flag'

    flag: EnumProperty(
        name='Collision Flag',
        items=(
            ('PHYSICAL', 'Physical', 'Select physical collision meshes'),
            ('PROJECTILE', 'Projectile', 'Select projectile collision meshes'),
            ('VIS', 'Vis', 'Select visibility collision meshes'),
            ('CAMERA', 'Camera', 'Select camera collision meshes'),
            ('VEHICLE', 'Vehicle', 'Select vehicle collision meshes'),
        ),
        default='PHYSICAL')

    _ATTR_MAP = {
        'PHYSICAL': 'coll_physical',
        'PROJECTILE': 'coll_projectile',
        'VIS': 'coll_vis',
        'CAMERA': 'coll_camera',
        'VEHICLE': 'coll_vehicle',
    }

    def execute(self, context):
        attr_name = self._ATTR_MAP[self.flag]

        def predicate(obj):
            if obj.type != 'MESH':
                return False
            settings = getattr(obj, 'w3d_object_settings', None)
            return settings is not None and getattr(settings, attr_name)

        if select_with_predicate(context, predicate):
            return {'FINISHED'}
        self.report({'INFO'}, f'No meshes use the {self.flag.lower()} collision flag')
        return {'CANCELLED'}


class W3D_OT_assign_node_names(bpy.types.Operator):
    bl_idname = 'w3d.assign_node_names'
    bl_label = 'Assign Node Names'
    bl_description = 'Rename selected objects (and optionally their children) using a sequential pattern'

    base_name: StringProperty(
        name='Base Name',
        description='Prefix used for generated node names',
        default='W3DNode')
    start_index: IntProperty(
        name='Start Index',
        description='Index used for the first node',
        default=0,
        min=0)
    padding: IntProperty(
        name='Digits',
        description='Zero padding for numeric suffix',
        default=2,
        min=0,
        max=6)
    include_children: BoolProperty(
        name='Include Children',
        description='Also rename the children of the selected objects',
        default=True)

    def invoke(self, context, event):
        if not context.selected_objects:
            self.report({'WARNING'}, 'Select at least one object')
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        if not self.base_name.strip():
            self.report({'ERROR'}, 'Base name cannot be empty')
            return {'CANCELLED'}
        targets = _collect_objects_with_children(context, self.include_children)
        if not targets:
            self.report({'WARNING'}, 'No objects to rename')
            return {'CANCELLED'}
        digits = max(0, self.padding)
        index = self.start_index
        for obj in targets:
            suffix = f'{index:0{digits}d}' if digits > 0 else str(index)
            obj.name = f'{self.base_name}_{suffix}'
            index += 1
        return {'FINISHED'}


class W3D_OT_assign_material_names(bpy.types.Operator):
    bl_idname = 'w3d.assign_material_names'
    bl_label = 'Assign Material Names'
    bl_description = 'Rename all materials used by the selection to a sequential pattern'

    base_name: StringProperty(
        name='Base Name',
        description='Prefix used for generated material names',
        default='W3DMat')
    start_index: IntProperty(
        name='Start Index',
        description='Index used for the first material',
        default=0,
        min=0)
    padding: IntProperty(
        name='Digits',
        description='Zero padding for numeric suffix',
        default=2,
        min=0,
        max=6)

    def invoke(self, context, event):
        if not context.selected_objects:
            self.report({'WARNING'}, 'Select at least one object')
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        materials = []
        seen = set()
        for obj in context.selected_objects:
            for slot in obj.material_slots:
                mat = slot.material
                if mat and mat not in seen:
                    materials.append(mat)
                    seen.add(mat)
        if not materials:
            self.report({'WARNING'}, 'No materials found on the selection')
            return {'CANCELLED'}
        digits = max(0, self.padding)
        current = self.start_index
        for mat in materials:
            suffix = f'{current:0{digits}d}' if digits > 0 else str(current)
            mat.name = f'{self.base_name}_{suffix}'
            current += 1
        return {'FINISHED'}


class W3D_OT_assign_extensions(bpy.types.Operator):
    bl_idname = 'w3d.assign_extensions'
    bl_label = 'Assign Extensions'
    bl_description = 'Add numbered extension suffixes (e.g. LOD or damage levels) to selected objects'

    prefix: StringProperty(
        name='Extension Prefix',
        description='Text inserted before the sequential number',
        default='lod')
    start_number: IntProperty(
        name='Start Number',
        description='Number to use for the first object',
        default=0,
        min=0)
    padding: IntProperty(
        name='Digits',
        description='Zero padding for the number',
        default=1,
        min=0,
        max=4)

    def invoke(self, context, event):
        if not context.selected_objects:
            self.report({'WARNING'}, 'Select at least one object')
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        objects = list(context.selected_objects)
        if not objects:
            self.report({'WARNING'}, 'No objects selected')
            return {'CANCELLED'}
        digits = max(0, self.padding)
        base_objects = sorted(objects, key=lambda obj: obj.name)
        for offset, obj in enumerate(base_objects):
            number = self.start_number + offset
            suffix = f'{number:0{digits}d}' if digits > 0 else str(number)
            base_name = obj.name.split('.')[0]
            obj.name = f'{base_name}_{self.prefix}{suffix}'
        return {'FINISHED'}


class W3D_OT_copy_settings_to_selected(bpy.types.Operator):
    bl_idname = 'w3d.copy_settings_to_selected'
    bl_label = 'Copy Settings to Selected'
    bl_description = 'Copy W3D settings from the active object to the selected mesh objects'

    def execute(self, context):
        source = context.active_object
        if source is None or source.type != 'MESH':
            self.report({'WARNING'}, 'Active mesh required')
            return {'CANCELLED'}
        targets = [obj for obj in context.selected_objects if obj is not source and obj.type == 'MESH']
        if not targets:
            self.report({'INFO'}, 'No target meshes selected')
            return {'CANCELLED'}
        copied = 0
        for obj in targets:
            if copy_object_settings(source, obj):
                copied += 1
        self.report({'INFO'}, f'Applied settings to {copied} mesh(es)')
        return {'FINISHED'}


class W3D_OT_copy_settings_to_linked(bpy.types.Operator):
    bl_idname = 'w3d.copy_settings_to_linked'
    bl_label = 'Copy Settings to Linked Instances'
    bl_description = 'Copy W3D settings from the active object to all objects sharing its mesh data'

    def execute(self, context):
        source = context.active_object
        if source is None or source.type != 'MESH':
            self.report({'WARNING'}, 'Active mesh required')
            return {'CANCELLED'}
        mesh_data = source.data
        targets = [obj for obj in bpy.data.objects if obj is not source and obj.type == 'MESH' and obj.data is mesh_data]
        if not targets:
            self.report({'INFO'}, 'No linked instances share this mesh data')
            return {'CANCELLED'}
        copied = 0
        for obj in targets:
            if copy_object_settings(source, obj):
                copied += 1
        self.report({'INFO'}, f'Applied settings to {copied} linked mesh(es)')
        return {'FINISHED'}


class W3D_OT_apply_preset(bpy.types.Operator):
    bl_idname = 'w3d.apply_preset'
    bl_label = 'Apply W3D Preset'
    bl_description = 'Apply a predefined W3D preset to the selected mesh objects'

    preset: EnumProperty(
        name='Preset',
        items=W3D_PRESET_ENUM or [('NONE', 'None', 'No presets defined')],
        default=(W3D_PRESET_ENUM[0][0] if W3D_PRESET_ENUM else 'NONE'))
    include_children: BoolProperty(
        name='Include Children',
        description='Also apply to the children of selected objects',
        default=False)

    def execute(self, context):
        if not W3D_PRESET_ENUM:
            self.report({'WARNING'}, 'No presets are available')
            return {'CANCELLED'}
        preset_def = next((preset for preset in W3D_PRESETS if preset['id'] == self.preset), None)
        if preset_def is None:
            self.report({'WARNING'}, 'Invalid preset selected')
            return {'CANCELLED'}
        targets = [obj for obj in context.selected_objects if obj.type == 'MESH']
        if self.include_children:
            seen = set(targets)
            queue = list(targets)
            while queue:
                current = queue.pop()
                for child in current.children:
                    if child.type != 'MESH' or child in seen:
                        continue
                    seen.add(child)
                    targets.append(child)
                    queue.append(child)
        if not targets:
            self.report({'WARNING'}, 'Select at least one mesh object')
            return {'CANCELLED'}
        applied = 0
        for obj in targets:
            if apply_preset_to_object(obj, preset_def):
                applied += 1
        self.report({'INFO'}, f'Applied preset to {applied} mesh(es)')
        return {'FINISHED'}


def menu_func_export(self, _context):
    self.layout.operator(ExportW3D.bl_idname, text='Westwood W3D (.w3d/.w3x)')


def menu_func_import(self, _context):
    self.layout.operator(ImportW3D.bl_idname, text='Westwood W3D (.w3d/.w3x)')


class MESH_PROPERTIES_PANEL_PT_w3d(Panel):
    bl_label = 'W3D Properties'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'data'

    def draw(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            return

        layout = self.layout
        layout.use_property_split = True
        mesh = obj.data
        settings = getattr(obj, 'w3d_object_settings', None)

        type_box = layout.box()
        type_box.label(text='Object Classification')
        type_box.prop(mesh, 'object_type')
        if mesh.object_type == 'MESH':
            type_box.prop(mesh, 'sort_level')
            type_box.prop(mesh, 'casts_shadow')
            type_box.prop(mesh, 'two_sided')
            type_box.prop(mesh, 'userText')
        elif mesh.object_type == 'DAZZLE':
            type_box.prop(mesh, 'dazzle_type')
        elif mesh.object_type == 'BOX':
            type_box.prop(mesh, 'box_type')
            type_box.prop(mesh, 'box_collision_types')
        elif mesh.object_type == 'GEOMETRY':
            type_box.prop(mesh, 'geometry_type')
            type_box.prop(mesh, 'contact_points_type')
        elif mesh.object_type == 'BONE_VOLUME':
            type_box.prop(mesh, 'mass')
            type_box.prop(mesh, 'spinniness')
            type_box.prop(mesh, 'contact_tag')

        if settings is None:
            layout.label(text='W3D object settings are unavailable on this object', icon='ERROR')
            return

        export_box = layout.box()
        export_box.label(text='Export Options')
        export_box.prop(settings, 'export_transform')
        export_box.prop(settings, 'export_geometry')
        export_box.prop(settings, 'geometry_type')
        export_box.prop(settings, 'static_sort_level')
        export_box.prop(settings, 'screen_size')
        if settings.geometry_type == 'DAZZLE':
            export_box.prop(settings, 'dazzle_name')

        geom_flags = layout.box()
        geom_flags.label(text='Geometry Flags')
        flags = [
            'geom_hide',
            'geom_two_sided',
            'geom_shadow',
            'geom_vertex_alpha',
            'geom_z_normal',
            'geom_shatter',
            'geom_tangents',
            'geom_keep_normals',
            'geom_prelit',
            'geom_always_dyn_light',
        ]
        grid = geom_flags.grid_flow(row_major=True, columns=2, even_columns=True)
        for flag in flags:
            grid.prop(settings, flag)

        collision_box = layout.box()
        collision_box.label(text='Collision Flags')
        collision_row = collision_box.row(align=True)
        collision_row.prop(settings, 'coll_physical', toggle=True)
        collision_row.prop(settings, 'coll_projectile', toggle=True)
        collision_row.prop(settings, 'coll_vis', toggle=True)
        collision_row = collision_box.row(align=True)
        collision_row.prop(settings, 'coll_camera', toggle=True)
        collision_row.prop(settings, 'coll_vehicle', toggle=True)

        warning_icon = 'ERROR'
        if settings.geometry_type == 'DAZZLE' and settings.geom_vertex_alpha:
            layout.label(text='Vertex Alpha is ignored on Dazzle geometry.', icon=warning_icon)
        if mesh.object_type != 'DAZZLE' and settings.geometry_type == 'DAZZLE':
            layout.label(text='Set the mesh Object Type to DAZZLE for Dazzle geometry.', icon=warning_icon)
        if settings.geometry_type == 'BOX' and mesh.object_type != 'BOX':
            layout.label(text='Geometry Type is BOX but the mesh Object Type is not BOX.', icon=warning_icon)


class BONE_PROPERTIES_PANEL_PT_w3d(Panel):
    bl_label = 'W3D Properties'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'bone'

    def draw(self, context):
        layout = self.layout
        if context.active_bone is not None:
            col = layout.column()
            col.prop(context.active_bone, 'visibility')


class SCENE_PROPERTIES_PANEL_PT_w3d_workflow(Panel):
    bl_label = 'W3D Workflow'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'scene'

    def draw(self, context):
        layout = self.layout
        settings = getattr(context.scene, 'w3d_scene_settings', None)
        if settings is None:
            layout.label(text='Scene settings are not available.', icon='ERROR')
            return
        layout.use_property_split = True
        layout.prop(settings, 'use_renegade_workflow')
        info = layout.box()
        info.label(text='Syncs mesh object types with the selected geometry context.', icon='INFO')


class MATERIAL_PROPERTIES_PANEL_PT_w3d(Panel):
    bl_label = 'OpenW3D Material'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'material'

    def draw(self, context):
        layout = self.layout
        obj = context.object
        mat = getattr(obj, 'active_material', None) if obj else None
        if not mat:
            layout.label(text='The active object does not have a material', icon='INFO')
            return
        settings = getattr(mat, 'w3d_material_settings', None)
        if settings is None:
            layout.label(text='Material does not contain W3D settings', icon='ERROR')
            return

        layout.use_property_split = True

        overview = layout.box()
        overview.label(text='Material Surface Type')
        overview.prop(settings, 'material_type', text='Material Type')
        overview.prop(settings, 'surface_type', text='Surface Type')
        overview.prop(settings, 'attributes', text='Attributes')
        obj_settings = getattr(obj, 'w3d_object_settings', None) if obj else None
        if obj_settings:
            overview.prop(obj_settings, 'static_sort_level', text='Static Sort Level')

        pass_box = layout.box()
        pass_box.label(text='Material Pass Count')
        summary = pass_box.row()
        summary.label(text=f'Current Pass Count: {len(settings.passes)}')
        controls = pass_box.row(align=True)
        controls.operator('w3d.material_pass_add', icon='ADD', text='Add Pass')
        remove_row = controls.row(align=True)
        remove_row.enabled = bool(settings.passes)
        remove_row.operator('w3d.material_pass_remove', icon='REMOVE', text='Remove Pass')
        list_row = pass_box.row()
        list_row.template_list('W3D_UL_material_passes', '', settings, 'passes', settings, 'active_pass_index', rows=2)
        col = list_row.column(align=True)
        move_up = col.operator('w3d.material_pass_move', icon='TRIA_UP', text='')
        move_up.direction = 'UP'
        move_down = col.operator('w3d.material_pass_move', icon='TRIA_DOWN', text='')
        move_down.direction = 'DOWN'

        if not settings.passes:
            info = layout.box()
            info.label(text='Add a pass to begin authoring materials.', icon='INFO')
            return

        index = min(settings.active_pass_index, len(settings.passes) - 1)
        active_pass = settings.passes[index]
        details = layout.box()
        details.label(text=f'Pass {index + 1}')

        tab_row = details.row(align=True)
        tab_row.prop(settings, 'ui_pass_section', expand=True)
        details.separator()

        def draw_vertex_tab(container):
            vertex = container.column()
            vertex.prop(active_pass, 'name', text='Pass Name')
            color_box = vertex.box()
            color_box.label(text='Vertex Material')
            color_box.prop(active_pass, 'ambient')
            color_box.prop(active_pass, 'diffuse')
            color_box.prop(active_pass, 'specular')
            color_box.prop(active_pass, 'emissive')
            color_box.prop(active_pass, 'specular_to_diffuse')
            color_box.prop(active_pass, 'opacity')
            color_box.prop(active_pass, 'translucency')
            color_box.prop(active_pass, 'shininess')

            mapping = vertex.box()
            mapping.label(text='Stage UV Channels')
            mapping.prop(active_pass, 'uv_channel_stage0', text='Stage 0')
            mapping.prop(active_pass, 'uv_channel_stage1', text='Stage 1')

        def draw_shader_tab(container):
            shader_box = container.box()
            shader_box.label(text='Shader')
            shader_box.prop(active_pass.shader, 'blend_mode')
            shader_box.prop(active_pass.shader, 'custom_src')
            shader_box.prop(active_pass.shader, 'custom_dest')
            shader_box.prop(active_pass.shader, 'write_z')
            shader_box.prop(active_pass.shader, 'alpha_test')
            shader_box.prop(active_pass.shader, 'pri_gradient')
            shader_box.prop(active_pass.shader, 'sec_gradient')
            shader_box.prop(active_pass.shader, 'depth_compare')
            shader_box.prop(active_pass.shader, 'detail_color')
            shader_box.prop(active_pass.shader, 'detail_alpha')

        def draw_stage(container, stage_settings, label):
            stage_box = container.box()
            header = stage_box.row(align=True)
            header.prop(stage_settings, 'enabled', text='', toggle=True)
            header.label(text=label)
            stage_box.prop(stage_settings, 'texture')
            stage_box.prop(stage_settings, 'alpha_bitmap', text='Alpha Bitmap')
            clamp_row = stage_box.row(align=True)
            clamp_row.prop(stage_settings, 'clamp_u', toggle=True)
            clamp_row.prop(stage_settings, 'clamp_v', toggle=True)
            clamp_row.prop(stage_settings, 'no_lod', toggle=True)
            publish_row = stage_box.row(align=True)
            publish_row.prop(stage_settings, 'publish', toggle=True)
            publish_row.prop(stage_settings, 'display', toggle=True)
            stage_box.prop(stage_settings, 'frames')
            stage_box.prop(stage_settings, 'fps')
            stage_box.prop(stage_settings, 'animation_mode')
            stage_box.prop(stage_settings, 'pass_hint')

        if settings.ui_pass_section == 'VERTEX':
            draw_vertex_tab(details)
        elif settings.ui_pass_section == 'SHADER':
            draw_shader_tab(details)
        else:
            textures = details.column()
            draw_stage(textures, active_pass.stage0, 'Stage 0 Texture')
            draw_stage(textures, active_pass.stage1, 'Stage 1 Texture')
            textures.operator('w3d.apply_stage_display', icon='SHADING_TEXTURE', text='Push Display Texture')

        legacy = layout.box()
        legacy.label(text='Legacy Properties', icon='INFO')
        legacy.label(text='Older scenes may still rely on the historic material fields. These remain available in the data model.', icon='BLANK1')


class TOOLS_PANEL_PT_w3d(bpy.types.Panel):
    bl_label = 'W3D Tools'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    def draw(self, context):
        layout = self.layout

        selection_box = layout.box()
        selection_box.label(text='Selection Helpers')
        selection_box.operator('w3d.select_bones', icon='ARMATURE_DATA')
        selection_box.operator('w3d.select_geometry', icon='MESH_DATA')
        selection_box.operator('w3d.select_alpha_meshes', icon='SHADING_RENDERED')
        collision_row = selection_box.row(align=True)
        for flag, label in (('PHYSICAL', 'Phys'), ('PROJECTILE', 'Proj'), ('VIS', 'Vis'), ('CAMERA', 'Cam'), ('VEHICLE', 'Veh')):
            op = collision_row.operator('w3d.select_collision_objects', text=label)
            op.flag = flag

        naming_box = layout.box()
        naming_box.label(text='Naming Utilities')
        naming_box.operator('w3d.assign_node_names', icon='OUTLINER_OB_GROUP_INSTANCE')
        naming_box.operator('w3d.assign_material_names', icon='MATERIAL')
        naming_box.operator('w3d.assign_extensions', icon='SORTSIZE')

        settings_box = layout.box()
        settings_box.label(text='Settings Utilities')
        scene_settings = getattr(context.scene, 'w3d_scene_settings', None)
        if scene_settings:
            settings_box.prop(scene_settings, 'use_renegade_workflow', icon='MOD_NORMALEDIT')
        settings_box.operator('w3d.copy_settings_to_selected', icon='COPY_ID')
        settings_box.operator('w3d.copy_settings_to_linked', icon='LINKED')
        settings_box.operator('w3d.apply_stage_display', icon='SHADING_TEXTURE')

        preset_box = layout.box()
        preset_box.label(text='Presets')
        preset_box.operator_menu_enum('w3d.apply_preset', 'preset', text='Apply Preset')

        export_box = layout.box()
        export_box.label(text='Data Export')
        export_box.operator('scene.export_geometry_data', icon='CUBE', text='Export Geometry Data')
        export_box.operator('scene.export_bone_volume_data', icon='BONE_DATA', text='Export Bone Volume Data')


class OBJECT_PT_DemoUpdaterPanel(bpy.types.Panel):
    bl_label = 'Updater Demo Panel'
    bl_idname = 'OBJECT_PT_hello'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_context = 'objectmode'
    bl_category = 'Tools'

    def draw(self, context):
        layout = self.layout

        addon_updater_ops.check_for_update_background()

        layout.label(text='Demo Updater Addon')
        layout.label(text='')

        col = layout.column()
        col.scale_y = 0.7
        col.label(text='If an update is ready,')
        col.label(text='popup triggered by opening')
        col.label(text='this panel, plus a box ui')

        if addon_updater_ops.updater.update_ready:
            layout.label(text='An update for the W3D/W3X plugin is available', icon='INFO')
        layout.label(text='')

        addon_updater_ops.update_notice_box_ui(self, context)


@addon_updater_ops.make_annotations
class DemoPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    auto_check_update = bpy.props.BoolProperty(
        name='Auto-check for Update',
        description='If enabled, auto-check for updates using an interval',
        default=False,
    )
    updater_intrval_months = bpy.props.IntProperty(
        name='Months',
        description='Number of months between checking for updates',
        default=0,
        min=0
    )
    updater_intrval_days = bpy.props.IntProperty(
        name='Days',
        description='Number of days between checking for updates',
        default=7,
        min=0,
        max=31
    )
    updater_intrval_hours = bpy.props.IntProperty(
        name='Hours',
        description='Number of hours between checking for updates',
        default=0,
        min=0,
        max=23
    )
    updater_intrval_minutes = bpy.props.IntProperty(
        name='Minutes',
        description='Number of minutes between checking for updates',
        default=0,
        min=0,
        max=59
    )

    dazzle_ini_path: bpy.props.StringProperty(
        name='Dazzle INI Path',
        description='Override the dazzle.ini used for Dazzle Type menus',
        subtype='FILE_PATH',
        default='',
        update=lambda self, context: refresh_dazzle_items(self.dazzle_ini_path))

    def draw(self, context):
        layout = self.layout

        mainrow = layout.row()
        col = mainrow.column()

        addon_updater_ops.update_settings_ui(self, context)
        layout.separator()
        box = layout.box()
        box.label(text='W3D Settings')
        box.prop(self, 'dazzle_ini_path')


CLASSES = (
    ExportW3D,
    ImportW3D,
    W3D_OT_show_export_log,
    W3D_UL_material_passes,
    W3D_OT_material_pass_add,
    W3D_OT_material_pass_remove,
    W3D_OT_material_pass_move,
    W3D_OT_apply_stage_display,
    W3D_OT_select_bones,
    W3D_OT_select_geometry,
    W3D_OT_select_alpha_meshes,
    W3D_OT_select_collision_objects,
    W3D_OT_assign_node_names,
    W3D_OT_assign_material_names,
    W3D_OT_assign_extensions,
    W3D_OT_copy_settings_to_selected,
    W3D_OT_copy_settings_to_linked,
    W3D_OT_apply_preset,
    W3DStageSettings,
    W3DShaderSettings,
    W3DMaterialPass,
    W3DMaterialSettings,
    W3DObjectSettings,
    W3DSceneSettings,
    ShaderProperties,
    MESH_PROPERTIES_PANEL_PT_w3d,
    BONE_PROPERTIES_PANEL_PT_w3d,
    SCENE_PROPERTIES_PANEL_PT_w3d_workflow,
    MATERIAL_PROPERTIES_PANEL_PT_w3d,
    ExportGeometryData,
    ExportBoneVolumeData,
    TOOLS_PANEL_PT_w3d,
    DemoPreferences,
    OBJECT_PT_DemoUpdaterPanel
)


def register():
    global _ADDON_UPDATER_REGISTERED
    addon_updater_ops._package = 'io_mesh_w3d'
    addon_updater_ops.updater.addon = 'io_mesh_w3d'
    addon_updater_ops.updater.user = "OpenSAGE"
    addon_updater_ops.updater.repo = "OpenSAGE.BlenderPlugin"
    addon_updater_ops.updater.website = "https://github.com/OpenSAGE/OpenSAGE.BlenderPlugin"
    addon_updater_ops.updater.subfolder_path = "io_mesh_w3d"
    addon_updater_ops.updater.include_branch_list = ['master']
    addon_updater_ops.updater.verbose = False

    try:
        addon_updater_ops.register(bl_info)
        _ADDON_UPDATER_REGISTERED = True
    except RuntimeError as exc:
        if 'AddonUpdaterInstallPopup' in str(exc):
            print('Addon updater already registered, skipping duplicate registration')
        else:
            raise

    for class_ in CLASSES:
        bpy.utils.register_class(class_)

    Material.shader = PointerProperty(type=ShaderProperties)
    Material.w3d_material_settings = PointerProperty(type=W3DMaterialSettings)
    bpy.types.Object.w3d_object_settings = PointerProperty(type=W3DObjectSettings)
    bpy.types.Scene.w3d_scene_settings = PointerProperty(type=W3DSceneSettings)

    # Refresh dazzle list using persisted preference
    try:
        prefs = bpy.context.preferences.addons.get(__package__)
        if prefs and getattr(prefs, 'preferences', None):
            refresh_dazzle_items(prefs.preferences.dazzle_ini_path)
    except Exception:
        pass

    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)


def unregister():
    global _ADDON_UPDATER_REGISTERED
    if _ADDON_UPDATER_REGISTERED:
        try:
            addon_updater_ops.unregister()
        except RuntimeError as exc:
            if 'AddonUpdaterInstallPopup' in str(exc):
                print('Addon updater was not registered, skipping unregister')
            else:
                raise
        _ADDON_UPDATER_REGISTERED = False

    for class_ in reversed(CLASSES):
        bpy.utils.unregister_class(class_)

    del Material.w3d_material_settings
    del bpy.types.Object.w3d_object_settings
    del bpy.types.Scene.w3d_scene_settings
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)


if __name__ == '__main__':
    register()
