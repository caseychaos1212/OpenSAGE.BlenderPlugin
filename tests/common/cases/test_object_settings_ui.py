# <pep8 compliant>

from types import SimpleNamespace
from unittest.mock import Mock

import bpy

from tests.utils import TestCase
from io_mesh_w3d import OBJECT_PROPERTIES_PANEL_PT_w3d, copy_object_settings
from io_mesh_w3d.common.utils.mesh_export import retrieve_meshes
from io_mesh_w3d.common.utils.box_export import retrieve_boxes
from io_mesh_w3d.w3d.utils.dazzle_export import retrieve_dazzles
from io_mesh_w3d.common.utils.object_settings_bridge import get_hlod_role


class TestObjectSettingsUI(TestCase):
    def new_object(self, name='mesh'):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(obj)
        return obj

    def drawn_properties(self, obj):
        layout = Mock()
        for method in ('column', 'box', 'row', 'grid_flow'):
            getattr(layout, method).return_value = layout
        OBJECT_PROPERTIES_PANEL_PT_w3d.draw(SimpleNamespace(layout=layout), SimpleNamespace(active_object=obj))
        return [call.args[1] for call in layout.prop.call_args_list]

    def test_mesh_controls_have_one_effective_setting_for_each_geometry_flag(self):
        obj = self.new_object()
        props = self.drawn_properties(obj)
        for name in ('export_object', 'export_type', 'hlod_role', 'export_transform', 'export_geometry',
                     'static_sort_level', 'geom_shadow', 'geom_two_sided', 'geom_tangents',
                     'geom_vertex_alpha', 'geom_z_normal', 'geom_shatter', 'geom_keep_normals',
                     'geom_prelit', 'geom_always_dyn_light'):
            self.assertEqual(1, props.count(name), name)
        for name in ('geometry_type', 'object_type', 'sort_level', 'casts_shadow', 'two_sided'):
            self.assertNotIn(name, props)

    def test_attachment_controls_omit_mesh_and_collision_settings(self):
        obj = self.new_object()
        for role in ('AGGREGATE', 'PROXY', 'LIGHT'):
            obj.w3d_object_settings.hlod_role = role
            props = self.drawn_properties(obj)
            self.assertIn('hlod_role', props)
            self.assertIn('hlod_identifier', props)
            for name in ('export_geometry', 'export_type', 'static_sort_level', 'geom_shadow', 'coll_physical'):
                self.assertNotIn(name, props)

    def test_legacy_aggregate_role_is_visible_and_can_be_cleared(self):
        obj = self.new_object()
        settings = obj.w3d_object_settings
        settings.geometry_type = 'AGGREGATE'
        settings['hlod_role'] = 0  # Saved by a previous plugin version.
        self.assertEqual('AGGREGATE', settings.hlod_role)
        settings.hlod_role = 'LOD'
        self.assertEqual('LOD', get_hlod_role(obj))
        self.assertEqual(1, len(retrieve_meshes(self, None, None, 'test')[0]))
        settings.geometry_type = 'AGGREGATE'
        settings.hlod_role = 'PROXY'
        self.assertEqual('PROXY', get_hlod_role(obj))
        self.assertEqual('NORMAL', settings.geometry_type)

    def test_legacy_flags_are_visible_and_explicit_zero_or_false_overrides_them(self):
        obj = self.new_object()
        obj.data.sort_level = 7
        obj.data.casts_shadow = True
        obj.data.two_sided = True
        settings = obj.w3d_object_settings
        self.assertEqual(7, settings.static_sort_level)
        self.assertTrue(settings.geom_shadow)
        self.assertTrue(settings.geom_two_sided)
        before = retrieve_meshes(self, None, None, 'test')[0][0]
        self.assertEqual(7, before.header.sort_level)
        self.assertTrue(before.casts_shadow())
        self.assertTrue(before.two_sided())
        settings.static_sort_level = 0
        settings.geom_shadow = False
        settings.geom_two_sided = False
        after = retrieve_meshes(self, None, None, 'test')[0][0]
        self.assertEqual(0, after.header.sort_level)
        self.assertFalse(after.casts_shadow())
        self.assertFalse(after.two_sided())

    def test_export_type_selector_changes_actual_output_in_both_workflows(self):
        obj = self.new_object()
        settings = obj.w3d_object_settings
        for renegade in (False, True):
            bpy.context.scene.w3d_scene_settings.use_renegade_workflow = renegade
            for kind in ('MESH', 'CAM_PARAL', 'CAM_ORIENT', 'BOX', 'DAZZLE'):
                settings.export_type = kind
                self.assertEqual(kind, settings.export_type)
                meshes = retrieve_meshes(self, None, None, 'test')[0]
                self.assertEqual(int(kind not in ('BOX', 'DAZZLE')), len(meshes))
                self.assertEqual(int(kind == 'BOX'), len(retrieve_boxes('test')))
                self.assertEqual(int(kind == 'DAZZLE'), len(retrieve_dazzles('test')))
                if meshes:
                    self.assertEqual(kind == 'CAM_PARAL', meshes[0].is_camera_aligned())
                    self.assertEqual(kind == 'CAM_ORIENT', meshes[0].is_camera_oriented())

    def test_linked_classification_stays_consistent_when_workflow_changes(self):
        obj = self.new_object()
        other = bpy.data.objects.new('linked', obj.data)
        bpy.context.scene.collection.objects.link(other)
        obj.w3d_object_settings.export_type = 'BOX'
        bpy.context.scene.w3d_scene_settings.use_renegade_workflow = True
        self.assertEqual('BOX', obj.w3d_object_settings.export_type)
        self.assertEqual('BOX', other.w3d_object_settings.export_type)
        obj.w3d_object_settings.export_type = 'MESH'
        obj.w3d_object_settings.export_type = 'CAM_PARAL'
        self.assertEqual('MESH', other.w3d_object_settings.export_type)
        self.assertEqual('CAM_PARAL', obj.w3d_object_settings.export_type)

    def test_box_and_dazzle_panels_show_only_their_consumed_settings(self):
        obj = self.new_object()
        obj.w3d_object_settings.export_type = 'BOX'
        props = self.drawn_properties(obj)
        self.assertIn('box_collision_types', props)
        self.assertNotIn('coll_physical', props)
        obj.w3d_object_settings.export_type = 'DAZZLE'
        self.assertIn('dazzle_name', self.drawn_properties(obj))
        self.assertNotIn('geom_shadow', self.drawn_properties(obj))

    def test_copy_settings_preserves_effective_type_role_and_zero_sort(self):
        source = self.new_object('source')
        target = self.new_object('target')
        source.w3d_object_settings.export_type = 'DAZZLE'
        source.w3d_object_settings.static_sort_level = 0
        target.data.sort_level = 8
        copy_object_settings(source, target)
        self.assertEqual('DAZZLE', target.w3d_object_settings.export_type)
        self.assertEqual(0, target.w3d_object_settings.static_sort_level)
        source.w3d_object_settings.geometry_type = 'AGGREGATE'
        copy_object_settings(source, target)
        self.assertEqual('AGGREGATE', get_hlod_role(target))
