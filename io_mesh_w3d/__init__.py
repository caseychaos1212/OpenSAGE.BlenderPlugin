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
from bpy.types import AddonPreferences, Panel
from bpy_extras import node_shader_utils
from bpy_extras.io_utils import ImportHelper, ExportHelper
from .utils import ReportHelper
from .export_utils import save_data
from .export_status import start_export_status, unregister_export_status
from .import_logging import write_import_log
from .custom_properties import *
from .geometry_export import *
from .bone_volume_export import *
from .common.utils.material_settings_bridge import apply_pass_to_material
from .common.utils.object_settings_bridge import get_hlod_role
from .common.utils.bone_display import game_bone_description
from .texture_blending import (
    W3D_OT_create_texture_blend, W3D_OT_refresh_blend_preview, W3D_OT_paint_blend_mask,
)
from .common.utils.helpers import enable_nodes

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
    'doc_url': 'https://github.com/caseychaos1212/OpenSAGE.BlenderPlugin',
    'tracker_url': 'https://github.com/caseychaos1212/OpenSAGE.BlenderPlugin/issues',
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
        if bpy.app.version < (4, 2, 0) and mat.blend_method != 'OPAQUE':
            return True
        if bpy.app.version >= (4, 2, 0) and mat.surface_render_method == 'BLENDED':
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

    enable_nodes(material)
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
        if identifier in {'rna_type', 'export_type'}:
            continue
        setattr(dst_settings, identifier, getattr(src_settings, identifier))
    dst_settings.export_type = src_settings.export_type
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

    apply_modifiers: BoolProperty(
        name='Apply Blender modifiers',
        description='Apply Blender modifier stack changes to meshes before exporting',
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

    show_export_status: BoolProperty(
        name='Show export status',
        description='Open a live window showing export stages, objects, elapsed time, and warnings',
        default=True)

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
        'apply_modifiers',
        'optimize_collision',
        'deduplicate_reference_meshes',
        'build_new_aabtree',
        'animation_frame_start',
        'animation_frame_end',
        'export_review_log',
        'show_export_status',
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
            'apply_modifiers': self.apply_modifiers,
            'optimize_collision': self.optimize_collision,
            'deduplicate_reference_meshes': self.deduplicate_reference_meshes,
            'build_new_aabtree': self.build_new_aabtree,
            'existing_skeleton_path': self.existing_skeleton_path if self.use_existing_skeleton else '',
            'force_vertex_materials': self.force_vertex_materials,
            'frame_range': (self.animation_frame_start, self.animation_frame_end),
        }

        status = start_export_status(context, self.filepath, self.show_export_status)
        self._w3d_export_status = status
        try:
            result = save_data(self, export_settings)
        except Exception as exc:
            status.record('ERROR', str(exc))
            status.finish('FAILED', str(exc))
            raise
        else:
            status.finish('FINISHED' if result and 'FINISHED' in result else 'FAILED')
        finally:
            self._w3d_export_status = None

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
        col.prop(self, 'show_export_status')
        col.prop(self, 'export_review_log')

    def draw_processing_settings(self):
        col = self.layout.box().column()
        col.label(text='Geometry Processing')
        col.prop(self, 'apply_modifiers')
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
    write_import_log: BoolProperty(
        name='Write import log',
        description='Write a sidecar log file with import messages and imported object state for version comparisons',
        default=False)

    def _finalize_import_state(self, pre_import_objects, pre_import_collections):
        state = getattr(self, '_w3d_import_state', None) or {}
        state.setdefault('source_path', self.filepath)

        loaded_files = state.get('loaded_files') or list(getattr(self, '_w3d_loaded_files', []) or [])
        if loaded_files:
            state['loaded_files'] = loaded_files

        created_objects = sorted(set(bpy.data.objects.keys()) - pre_import_objects)
        created_collections = sorted(set(bpy.data.collections.keys()) - pre_import_collections)

        if not state.get('object_names') and created_objects:
            state['object_names'] = created_objects
            state['capture_source'] = 'scene-diff'

        if not state.get('collection_name') and created_collections:
            state['collection_name'] = created_collections[0]

        if not state.get('rig_name'):
            for name in created_objects:
                obj = bpy.data.objects.get(name)
                if obj is not None and obj.type == 'ARMATURE':
                    state['rig_name'] = name
                    break

        if not state.get('hierarchy_name') and state.get('rig_name'):
            state['hierarchy_name'] = state['rig_name']

        if not state.get('object_names') and state.get('collection_name'):
            collection = bpy.data.collections.get(state['collection_name'])
            if collection is not None:
                collection_objects = getattr(collection, 'all_objects', collection.objects)
                state['object_names'] = sorted({obj.name for obj in collection_objects})

        if not state.get('capture_source'):
            state['capture_source'] = 'loader'

        self._w3d_import_state = state

    def execute(self, context):
        print_version(self.info)
        self._w3d_log_buffer = [] if self.write_import_log else None
        self._w3d_loaded_files = [] if self.write_import_log else None
        self._w3d_import_state = None
        pre_import_objects = set(bpy.data.objects.keys()) if self.write_import_log else set()
        pre_import_collections = set(bpy.data.collections.keys()) if self.write_import_log else set()
        if self.filepath.lower().endswith('.w3d'):
            from .w3d.import_w3d import load
            result = load(self)
        else:
            from .w3x.import_w3x import load
            result = load(self)

        if result is None:
            result = {'CANCELLED'}

        log_path = None
        if self.write_import_log:
            self._finalize_import_state(pre_import_objects, pre_import_collections)
            try:
                log_path = write_import_log(self, context)
            except Exception as exc:
                self.warning(f'failed to write import log: {exc}')

        self._w3d_import_state = None
        self._w3d_loaded_files = None
        self._w3d_log_buffer = None

        if 'FINISHED' in result:
            self.info('finished')
        if log_path:
            self.info(f'import log written: {log_path}')
        return result

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'keep_rigid_meshes_static')
        layout.prop(self, 'write_import_log')


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


class W3D_OT_open_object_settings(bpy.types.Operator):
    bl_idname = 'w3d.open_object_settings'
    bl_label = 'Open W3D Object Settings'
    bl_description = 'Open the Object Properties tab containing the W3D export controls'

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'PROPERTIES'

    def execute(self, context):
        context.space_data.context = 'OBJECT'
        return {'FINISHED'}


class MESH_PROPERTIES_PANEL_PT_w3d(Panel):
    bl_label = 'W3D Settings'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'data'

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == 'MESH'

    def draw(self, context):
        self.layout.label(text='W3D controls are in Object Properties.', icon='INFO')
        self.layout.operator('w3d.open_object_settings', icon='OBJECT_DATA')


class OBJECT_PROPERTIES_PANEL_PT_w3d(Panel):
    bl_label = 'W3D Object'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'object'

    def draw(self, context):
        obj = context.active_object
        settings = getattr(obj, 'w3d_object_settings', None)
        if settings is None:
            return
        layout = self.layout
        layout.use_property_split = True
        layout.prop(settings, 'export_object')
        if obj.type == 'ARMATURE':
            layout.prop(settings, 'show_game_bone_directions')
            if settings.show_game_bone_directions:
                layout.label(text='Arrows show game axes in Object and Pose Mode.')
            return

        content = layout.column()
        content.enabled = settings.export_object
        content.prop(settings, 'hlod_role')
        if obj.type == 'MESH':
            content.prop(settings, 'export_transform')
        role = get_hlod_role(obj)
        if role != 'LOD':
            content.prop(settings, 'hlod_identifier')
            content.label(text='Exports an HLOD reference without mesh geometry.', icon='INFO')
            if role == 'PROXY':
                content.label(text='Blank identifier uses the name before "~".')
                content.label(text='Long W3D pivot names are shortened on export.')
            return
        if obj.type != 'MESH':
            content.label(text='Choose an attachment role to export this object.', icon='INFO')
            return

        mesh = obj.data
        content.prop(settings, 'export_type')
        if mesh.users > 1:
            content.label(text='Mesh classification is shared by linked objects.', icon='LINKED')
        if mesh.object_type in ('GEOMETRY', 'BONE_VOLUME'):
            if mesh.object_type == 'GEOMETRY':
                content.prop(mesh, 'geometry_type')
                content.prop(mesh, 'contact_points_type')
                content.label(text='Used by Export Geometry Data.')
            else:
                content.prop(mesh, 'mass')
                content.prop(mesh, 'spinniness')
                content.prop(mesh, 'contact_tag')
                content.label(text='Used by Export Bone Volume Data.')
            return

        content.prop(settings, 'export_geometry')
        geometry = content.column()
        geometry.enabled = settings.export_geometry
        geometry.prop(settings, 'screen_size')
        if mesh.object_type == 'DAZZLE':
            if not settings.is_property_set('dazzle_name') and mesh.is_property_set('dazzle_type'):
                geometry.prop(mesh, 'dazzle_type')
                if mesh.dazzle_type == 'CUSTOM':
                    geometry.prop(mesh, 'dazzle_type_custom')
            else:
                geometry.prop(settings, 'dazzle_name')
                if settings.dazzle_name == 'CUSTOM':
                    geometry.prop(settings, 'dazzle_name_custom')
            return
        if mesh.object_type == 'BOX':
            geometry.prop(mesh, 'box_type', text='Box Type')
            geometry.prop(mesh, 'box_collision_types')
            return

        geometry.prop(settings, 'static_sort_level')
        geometry.prop(mesh, 'userText')
        flags = geometry.box()
        flags.label(text='Geometry Flags')
        grid = flags.grid_flow(row_major=True, columns=2, even_columns=True)
        for prop in ('geom_hide', 'geom_two_sided', 'geom_shadow', 'geom_vertex_alpha',
                     'geom_z_normal', 'geom_shatter', 'geom_tangents', 'geom_keep_normals',
                     'geom_prelit', 'geom_always_dyn_light'):
            grid.prop(settings, prop)
        collisions = geometry.box()
        collisions.label(text='Collision Flags')
        grid = collisions.grid_flow(row_major=True, columns=2, even_columns=True)
        for prop in ('coll_physical', 'coll_projectile', 'coll_vis', 'coll_camera', 'coll_vehicle'):
            grid.prop(settings, prop)


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
            description = game_bone_description(context.active_bone.name)
            if description:
                col.label(text=description)
                if context.object and context.object.type == 'ARMATURE':
                    col.prop(context.object.w3d_object_settings, 'show_game_bone_directions')


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
            layout.operator('w3d.create_texture_blend', icon='TEXTURE')
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

        blending = layout.box()
        blending.label(text='Texture Blending')
        blending.operator('w3d.create_texture_blend', icon='TEXTURE')
        blending.operator('w3d.refresh_blend_preview', icon='FILE_REFRESH')
        if len(settings.passes) == 2:
            for config, label in zip(settings.passes, ('Base Texture', 'Blend Texture')):
                blending.label(text=label)
                blending.template_ID(config.stage0, 'texture', open='image.open')

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
        if obj.type == 'MESH':
            details.prop_search(active_pass, 'blend_mask', obj.data,
                                'vertex_colors' if bpy.app.version < (3, 2, 0) else 'color_attributes')
            details.operator('w3d.paint_blend_mask', icon='VPAINT_HLT')
            if active_pass.blend_mask:
                details.label(text='Black = base; white = this pass. Gray blends both.')

        tab_row = details.row(align=True)
        tab_row.prop(settings, 'ui_pass_section', expand=True)
        details.separator()

        def draw_vertex_tab(container):
            vertex = container.column()
            vertex.prop(active_pass, 'name', text='Pass Name')

            notes_box = vertex.box()
            notes_box.label(text='Interaction Notes', icon='INFO')
            notes_box.label(text='If Emissive is non-black, keep Ambient and Diffuse black.')
            notes_box.label(text='If Emissive is black, Ambient and Diffuse should usually match.')
            notes_box.label(text='Opacity only shows through when the shader blend mode is not Opaque.')

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
            mapping.label(text='Stage Mapping')
            mapping.label(text='Mapper arguments are case-sensitive and comma-separated.', icon='INFO')

            stage0_box = mapping.box()
            stage0_box.label(text='Stage 0')
            stage0_box.prop(active_pass, 'stage0_mapping', text='Mapping')
            stage0_box.prop(active_pass, 'uv_channel_stage0', text='UV Channel')
            stage0_box.prop(active_pass, 'stage0_args', text='Args')

            stage1_box = mapping.box()
            stage1_box.label(text='Stage 1')
            stage1_box.prop(active_pass, 'stage1_mapping', text='Mapping')
            stage1_box.prop(active_pass, 'uv_channel_stage1', text='UV Channel')
            stage1_box.prop(active_pass, 'stage1_args', text='Args')

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

        def draw_image_slot(container, owner, prop_name, label):
            split = container.split(factor=0.4, align=True)
            label_col = split.column()
            label_col.alignment = 'RIGHT'
            label_col.label(text=label)
            field_col = split.column()
            field_col.template_ID(owner, prop_name, open='image.open')

        def draw_stage(container, stage_settings, label):
            stage_box = container.box()
            header = stage_box.row(align=True)
            header.prop(stage_settings, 'enabled', text='', toggle=True)
            header.label(text=label)
            draw_image_slot(stage_box, stage_settings, 'texture', 'Texture')
            draw_image_slot(stage_box, stage_settings, 'alpha_bitmap', 'Alpha Bitmap')
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


def _update_dazzle_ini(self, context):
    refresh_dazzle_items(bpy.path.abspath(self.dazzle_ini_path))


class W3DAddonPreferences(AddonPreferences):
    bl_idname = __package__

    dazzle_ini_path: StringProperty(
        name='Dazzle INI',
        description='Game dazzle.ini file used to populate the Dazzle Type list',
        subtype='FILE_PATH',
        default='',
        update=_update_dazzle_ini)

    def draw(self, context):
        self.layout.prop(self, 'dazzle_ini_path')
        self.layout.label(text="Choose your game's dazzle.ini to list its dazzle types.")
        self.layout.label(text='Imported custom types are preserved even without this file.')


CLASSES = (
    W3DAddonPreferences,
    ExportW3D,
    ImportW3D,
    W3D_OT_show_export_log,
    W3D_UL_material_passes,
    W3D_OT_material_pass_add,
    W3D_OT_material_pass_remove,
    W3D_OT_material_pass_move,
    W3D_OT_apply_stage_display,
    W3D_OT_create_texture_blend,
    W3D_OT_refresh_blend_preview,
    W3D_OT_paint_blend_mask,
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
    OBJECT_PROPERTIES_PANEL_PT_w3d,
    W3D_OT_open_object_settings,
    MESH_PROPERTIES_PANEL_PT_w3d,
    BONE_PROPERTIES_PANEL_PT_w3d,
    SCENE_PROPERTIES_PANEL_PT_w3d_workflow,
    MATERIAL_PROPERTIES_PANEL_PT_w3d,
    ExportGeometryData,
    ExportBoneVolumeData,
    TOOLS_PANEL_PT_w3d
)


def register():
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
    unregister_export_status()
    for class_ in reversed(CLASSES):
        bpy.utils.unregister_class(class_)

    del Material.w3d_material_settings
    del bpy.types.Object.w3d_object_settings
    del bpy.types.Scene.w3d_scene_settings
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)


if __name__ == '__main__':
    register()
