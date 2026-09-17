# <pep8 compliant>

import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

import bpy
from mathutils import Vector

from tests.utils import TestCase
from tests.common.helpers.mesh import get_mesh
from io_mesh_w3d import MESH_PROPERTIES_PANEL_PT_w3d, OBJECT_PROPERTIES_PANEL_PT_w3d
from io_mesh_w3d.common.structs.data_context import DataContext
from io_mesh_w3d.common.structs.hlod import (
    W3D_CHUNK_HLOD, W3D_CHUNK_HLOD_AGGREGATE_ARRAY,
)
from io_mesh_w3d.common.structs.hierarchy import W3D_CHUNK_HIERARCHY
from io_mesh_w3d.common.utils.hierarchy_export import retrieve_hierarchy
from io_mesh_w3d.common.utils.mesh_import import create_mesh
from io_mesh_w3d.common.utils.object_settings_bridge import get_hlod_role
from io_mesh_w3d.export_utils import retrieve_data, save_data
from io_mesh_w3d.w3d.import_w3d import load_file
from io_mesh_w3d.w3d.io_binary import read_chunk_head


class TestExportControls(TestCase):
    def new_object(self, name, object_type='MESH'):
        if object_type == 'EMPTY':
            data = None
        elif object_type == 'ARMATURE':
            data = bpy.data.armatures.new(name)
        else:
            data = bpy.data.meshes.new(name)
            data.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
            data.object_type = object_type
        obj = bpy.data.objects.new(name, data)
        bpy.context.scene.collection.objects.link(obj)
        return obj

    def test_aggregate_only_file_contains_attachment_chunk_without_geometry(self):
        obj = self.new_object('building')
        obj.location = (10, 20, 30)
        settings = obj.w3d_object_settings
        settings.export_geometry = False
        settings.hlod_identifier = 'ar_building'
        self.filepath = self.outpath('aggregates.w3d')
        bpy.context.view_layer.update()

        # An attachment-only scene should not even request evaluated mesh data.
        mesh_context = Mock()
        mesh_context.evaluated_depsgraph_get.side_effect = AssertionError('Unneeded mesh evaluation')
        for legacy in (False, True):
            settings.hlod_role = 'LOD' if legacy else 'AGGREGATE'
            settings.geometry_type = 'AGGREGATE' if legacy else 'NORMAL'
            for mode in ('HM', 'TERRAIN', 'M'):
                with self.subTest(legacy=legacy, mode=mode):
                    bpy.context.scene.w3d_scene_settings.use_renegade_workflow = mode == 'M'
                    options = {'mode': mode, 'use_existing_skeleton': False}
                    with patch('io_mesh_w3d.common.utils.mesh_export.bpy',
                               SimpleNamespace(context=mesh_context)):
                        self.assertEqual({'FINISHED'}, save_data(self, options))

                    root_chunks = []
                    hlod_chunks = []
                    with open(self.filepath, 'rb') as stream:
                        while stream.tell() < os.path.getsize(self.filepath):
                            chunk, _, end = read_chunk_head(stream)
                            root_chunks.append(chunk)
                            if chunk == W3D_CHUNK_HLOD:
                                while stream.tell() < end:
                                    child, _, child_end = read_chunk_head(stream)
                                    hlod_chunks.append(child)
                                    stream.seek(child_end)
                            stream.seek(end)
                    self.assertEqual([W3D_CHUNK_HIERARCHY, W3D_CHUNK_HLOD], root_chunks)
                    self.assertIn(W3D_CHUNK_HLOD_AGGREGATE_ARRAY, hlod_chunks)

                    exported = DataContext()
                    load_file(self, exported)
                    self.assertEqual([], exported.meshes)
                    self.assertEqual(0, exported.hlod.lod_arrays[0].header.model_count)
                    attachment = exported.hlod.aggregate_array.sub_objects[0]
                    self.assertEqual('ar_building', attachment.identifier)
                    pivot = exported.hierarchy.pivots[attachment.bone_index]
                    self.assertEqual('building', pivot.name)
                    self.assertEqual(Vector((10, 20, 30)), pivot.translation)
        mesh_context.evaluated_depsgraph_get.assert_not_called()

    def test_excluded_long_name_helpers_are_omitted_from_all_model_data(self):
        included = self.new_object('building')
        included.w3d_object_settings.hlod_role = 'AGGREGATE'
        for kind in ('MESH', 'BOX', 'DAZZLE', 'ARMATURE', 'EMPTY'):
            obj = self.new_object('cookie_cutter_helper_with_a_long_name_' + kind, kind)
            obj.w3d_object_settings.export_object = False
            if kind == 'EMPTY':
                obj.w3d_object_settings.hlod_role = 'PROXY'
        excluded_aggregate = self.new_object('excluded_aggregate_with_a_long_name')
        excluded_aggregate.w3d_object_settings.hlod_role = 'AGGREGATE'
        excluded_aggregate.w3d_object_settings.export_object = False
        self.filepath = self.outpath('helpers.w3d')

        with patch.object(self, 'error') as error:
            exported = retrieve_data(self, {'mode': 'HM'})
        error.assert_not_called()
        self.assertIsNotNone(exported)
        self.assertIsNone(exported.rig)
        self.assertEqual([], exported.meshes)
        self.assertEqual([], exported.collision_boxes)
        self.assertEqual([], exported.dazzles)
        self.assertEqual(['ROOTTRANSFORM', 'building'], [p.name for p in exported.hierarchy.pivots])
        self.assertEqual(['building'], [o.identifier for o in exported.hlod.aggregate_array.sub_objects])
        self.assertIsNone(exported.hlod.proxy_array)
        self.assertEqual([], exported.hlod.lod_arrays[0].sub_objects)

    def test_exclusion_is_per_object_even_with_shared_mesh_data(self):
        create_mesh(self, get_mesh('visible'), bpy.context.scene.collection)
        included = bpy.data.objects['visible']
        excluded = bpy.data.objects.new('cookie_cutter_with_a_long_name', included.data)
        bpy.context.scene.collection.objects.link(excluded)
        excluded.w3d_object_settings.export_object = False
        self.filepath = self.outpath('shared.w3d')

        for file_format in ('W3D', 'W3X'):
            with self.subTest(file_format=file_format):
                self.set_format(file_format)
                exported = retrieve_data(self, {'mode': 'HM'})
                self.assertIsNotNone(exported)
                self.assertEqual(['visible'], [m.header.mesh_name for m in exported.meshes])
                self.assertEqual(['shared.visible'], [o.identifier for o in exported.hlod.lod_arrays[0].sub_objects])
                self.assertEqual(['ROOTTRANSFORM', 'visible'], [p.name for p in exported.hierarchy.pivots])
        self.assertTrue(included.w3d_object_settings.export_object)
        self.assertIn(excluded.name, bpy.context.scene.objects)

    def test_excluded_child_cannot_reenter_hierarchy_through_parent_recursion(self):
        parent = self.new_object('parent')
        child = self.new_object('child_helper_with_a_long_name')
        child.parent = parent
        child.w3d_object_settings.export_object = False
        hierarchy, _ = retrieve_hierarchy(self, 'test')
        self.assertEqual(['ROOTTRANSFORM', 'parent'], [p.name for p in hierarchy.pivots])

    def test_exported_child_keeps_position_when_helper_parent_is_excluded(self):
        parent = self.new_object('parent_helper_with_a_long_name')
        parent.location = (10, 20, 30)
        parent.w3d_object_settings.export_object = False
        child = self.new_object('building')
        child.parent = parent
        child.location = (1, 2, 3)
        child.w3d_object_settings.hlod_role = 'AGGREGATE'
        bpy.context.view_layer.update()
        hierarchy, _ = retrieve_hierarchy(self, 'test')
        self.assertEqual(['ROOTTRANSFORM', 'building'], [p.name for p in hierarchy.pivots])
        self.assertEqual(0, hierarchy.pivots[1].parent_id)
        self.assertEqual(Vector((11, 22, 33)), hierarchy.pivots[1].translation)

    def test_geometry_toggle_keeps_transform_and_attachment_controls_independent(self):
        helper = self.new_object('pivot_only')
        helper.w3d_object_settings.export_geometry = False
        proxy = self.new_object('proxy~instance', 'EMPTY')
        proxy.w3d_object_settings.hlod_role = 'PROXY'
        proxy.w3d_object_settings.export_geometry = False
        self.filepath = self.outpath('controls.w3d')
        exported = retrieve_data(self, {'mode': 'HM'})
        self.assertIsNotNone(exported)
        self.assertEqual([], exported.meshes)
        self.assertEqual(['ROOTTRANSFORM', 'pivot_only'], [p.name for p in exported.hierarchy.pivots])
        self.assertEqual('proxy', exported.hlod.proxy_array.sub_objects[0].identifier)
        self.assertEqual([], exported.hlod.lod_arrays[0].sub_objects)

        helper.w3d_object_settings.export_transform = False
        exported = retrieve_data(self, {'mode': 'HM'})
        self.assertEqual(['ROOTTRANSFORM'], [p.name for p in exported.hierarchy.pivots])

    def test_viewport_hidden_and_w3d_hidden_objects_keep_exporting(self):
        obj = self.new_object('building')
        obj.w3d_object_settings.hlod_role = 'AGGREGATE'
        obj.w3d_object_settings.geom_hide = True
        obj.hide_set(True)
        self.filepath = self.outpath('hidden.w3d')
        exported = retrieve_data(self, {'mode': 'HM'})
        self.assertIsNotNone(exported)
        self.assertEqual('building', exported.hlod.aggregate_array.sub_objects[0].identifier)

    def test_aggregate_geometry_dropdown_remains_available(self):
        obj = self.new_object('building')
        settings = obj.w3d_object_settings
        context = SimpleNamespace(active_object=obj)
        for geometry_type in ('NORMAL', 'AGGREGATE', 'NORMAL'):
            with self.subTest(geometry_type=geometry_type):
                settings.geometry_type = geometry_type
                layout = Mock()
                layout.box.return_value = layout
                layout.grid_flow.return_value = layout
                layout.row.return_value = layout
                panel = SimpleNamespace(layout=layout)
                MESH_PROPERTIES_PANEL_PT_w3d.draw(panel, context)
                layout.prop.assert_any_call(settings, 'geometry_type')
                layout.prop.assert_any_call(settings, 'export_object')
        self.assertEqual('LOD', get_hlod_role(obj))

        layout = Mock()
        OBJECT_PROPERTIES_PANEL_PT_w3d.draw(SimpleNamespace(layout=layout), context)
        layout.prop.assert_any_call(settings, 'export_object')
