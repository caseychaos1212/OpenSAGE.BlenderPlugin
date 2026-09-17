# <pep8 compliant>

import io
from unittest.mock import patch

import bpy
from mathutils import Vector

from tests.utils import TestCase
from tests.common.helpers.mesh import get_mesh
from tests.common.helpers.hierarchy import get_hierarchy
from tests.w3d.helpers.mesh_structs.vertex_material import get_vertex_material
from io_mesh_w3d.common.structs.mesh import (
    Mesh, PRELIT_MASK, W3D_CHUNK_VERTEX_NORMALS, W3D_CHUNK_NORMALS_2,
)
from io_mesh_w3d.common.utils.material_import import create_material_from_vertex_material
from io_mesh_w3d.common.utils.mesh_export import retrieve_meshes
from io_mesh_w3d.common.utils.mesh_import import create_mesh, rig_mesh
from io_mesh_w3d.common.utils.hierarchy_import import get_or_create_skeleton
from io_mesh_w3d.common.utils.helpers import set_uv
from io_mesh_w3d.w3d.io_binary import read_chunk_head, read_list, read_vector


class TestGeometryFlags(TestCase):
    def new_object(self):
        mesh = bpy.data.meshes.new('geometry')
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)], [], [(0, 1, 2), (1, 3, 2)])
        obj = bpy.data.objects.new('geometry', mesh)
        bpy.context.scene.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        material, _ = create_material_from_vertex_material('geometry', get_vertex_material())
        mesh.materials.append(material)
        config = material.w3d_material_settings.passes[0]
        config.opacity = 1.0
        config.shader.blend_mode = '0'
        return obj

    def export(self, hierarchy=None, rig=None):
        meshes, _ = retrieve_meshes(self, hierarchy, rig, 'flags')
        self.assertEqual(1, len(meshes))
        return meshes[0]

    def serialize(self, source):
        stream = io.BytesIO()
        source.write(stream)
        stream.seek(0)
        _, _, end = read_chunk_head(stream)
        return Mesh.read(self, stream, end)

    def assert_vector(self, expected, actual):
        self.assertLess((Vector(expected) - Vector(actual)).length, 5e-4)

    def add_colors(self, obj, colors, domain='CORNER', name='AlphaPaint'):
        if bpy.app.version < (3, 2, 0):
            layer = obj.data.vertex_colors.new(name=name)
            obj.data.vertex_colors.active = layer
        else:
            layer = obj.data.color_attributes.new(name=name, type='FLOAT_COLOR', domain=domain)
            obj.data.color_attributes.active_color_index = obj.data.color_attributes.find(layer.name)
        for datum, color in zip(layer.data, colors):
            datum.color = color
        return layer

    def test_runtime_flags_write_exact_max_bits_and_restore_on_import(self):
        obj = self.new_object()
        mapping = {'geom_shatter': 0x10000000, 'geom_prelit': 0x40000000,
                   'geom_always_dyn_light': 0x80000000}
        for name, flag in mapping.items():
            with self.subTest(flag=name):
                for prop in mapping:
                    setattr(obj.w3d_object_settings, prop, prop == name)
                actual = self.serialize(self.export())
                self.assertEqual(flag, actual.header.attrs & 0xD0000000)
                self.assertEqual(0, actual.header.attrs & PRELIT_MASK)
                self.assertIsNone(actual.prelit_vertex)
                self.assertIsNone(actual.prelit_unlit)
                imported_name = create_mesh(self, actual, bpy.context.scene.collection)
                imported = bpy.data.objects[imported_name]
                self.assertTrue(getattr(imported.w3d_object_settings, name))
                self.assertTrue(imported.w3d_object_settings.geom_keep_normals)
                self.assertFalse(imported.w3d_object_settings.geom_vertex_alpha)
                self.assertFalse(imported.w3d_object_settings.geom_z_normal)
                bpy.data.objects.remove(imported, do_unlink=True)
        for prop in mapping:
            setattr(obj.w3d_object_settings, prop, True)
        self.assertEqual(0xD0000000, self.serialize(self.export()).header.attrs & 0xD0000000)
        for prop in mapping:
            setattr(obj.w3d_object_settings, prop, False)
        self.assertEqual(0, self.serialize(self.export()).header.attrs & 0xD0000000)

    def test_legacy_prelit_wrapper_does_not_enable_the_tt_prelit_flag(self):
        source = get_mesh('legacy', prelit=True)
        name = create_mesh(self, source, bpy.context.scene.collection)
        self.assertFalse(bpy.data.objects[name].w3d_object_settings.geom_prelit)

    def test_z_normal_overrides_authored_normals_without_editing_mesh(self):
        obj = self.new_object()
        obj.data.normals_split_custom_set([(1, 0, 0)] * len(obj.data.loops))
        before = [loop.normal.copy() for loop in obj.data.loops]
        obj.w3d_object_settings.geom_keep_normals = True
        obj.w3d_object_settings.geom_z_normal = True
        actual = self.serialize(self.export())
        for normal in actual.normals:
            self.assertEqual((0, 0, 1), tuple(normal))
        for expected, loop in zip(before, obj.data.loops):
            self.assert_vector(expected, loop.normal)
        obj.w3d_object_settings.geom_z_normal = False
        for normal in self.export().normals:
            self.assert_vector((1, 0, 0), normal)

    def test_z_normal_sets_both_skinned_normal_channels_after_bone_transforms(self):
        source = get_mesh('skin', skin=True)
        hierarchy = get_hierarchy()
        name = create_mesh(self, source, bpy.context.scene.collection)
        rig = get_or_create_skeleton(hierarchy, bpy.context.scene.collection)
        rig_mesh(source, hierarchy, rig, object_name=name)
        obj = bpy.data.objects[name]
        obj.w3d_object_settings.geom_z_normal = True
        exported = self.export(hierarchy, rig)
        stream = io.BytesIO()
        exported.write(stream)
        stream.seek(0)
        _, _, end = read_chunk_head(stream)
        normals = {}
        while stream.tell() < end:
            chunk, _, chunk_end = read_chunk_head(stream)
            if chunk in (W3D_CHUNK_VERTEX_NORMALS, W3D_CHUNK_NORMALS_2):
                normals[chunk] = read_list(stream, chunk_end, read_vector)
            stream.seek(chunk_end)
        self.assertEqual({W3D_CHUNK_VERTEX_NORMALS, W3D_CHUNK_NORMALS_2}, set(normals))
        for channel in normals.values():
            self.assertEqual(len(exported.verts), len(channel))
            for normal in channel:
                self.assertEqual((0, 0, 1), tuple(normal))

    def test_keep_normals_preserves_corner_seams_and_source_data(self):
        obj = self.new_object()
        obj.data.normals_split_custom_set([(1, 0, 0)] * 3 + [(0, 1, 0)] * 3)
        settings = obj.w3d_object_settings
        settings.geom_keep_normals = True
        before = ([vertex.co.copy() for vertex in obj.data.vertices],
                  [loop.normal.copy() for loop in obj.data.loops],
                  [face.use_smooth for face in obj.data.polygons],
                  [attribute.name for attribute in obj.data.attributes])
        for apply_modifiers in (False, True):
            self._w3d_export_options = {'smooth_vertex_normals': True, 'apply_modifiers': apply_modifiers}
            actual = self.serialize(self.export())
            self.assertEqual(6, len(actual.verts))
            for index, triangle in enumerate(actual.triangles):
                for vertex_id in triangle.vert_ids:
                    self.assert_vector((1, 0, 0) if index == 0 else (0, 1, 0), actual.normals[vertex_id])
        self.assertEqual(before[0], [v.co for v in obj.data.vertices])
        self.assertEqual(before[1], [loop.normal for loop in obj.data.loops])
        self.assertEqual(before[2], [face.use_smooth for face in obj.data.polygons])
        self.assertEqual(before[3], [attribute.name for attribute in obj.data.attributes])
        settings.geom_keep_normals = False
        for normal in self.export().normals:
            self.assert_vector((0, 0, 1), normal)

    def test_keep_normals_survives_uv_splits_and_nonuniform_scale(self):
        obj = self.new_object()
        normal = Vector((1, 1, 1)).normalized()
        obj.data.normals_split_custom_set([normal] * len(obj.data.loops))
        uv = obj.data.uv_layers.new()
        for index in range(len(obj.data.loops)):
            set_uv(uv, index, (index % 3, index // 3))
        obj.scale = (2, 1, 0.5)
        obj.w3d_object_settings.geom_keep_normals = True
        expected = Vector((0.5, 1, 2)).normalized()
        actual = self.export()
        self.assertEqual(6, len(actual.verts))
        for normal in actual.normals:
            self.assert_vector(expected, normal)

    def test_keep_normals_preserves_ngon_corner_values_through_triangulation(self):
        obj = self.new_object()
        obj.data.clear_geometry()
        obj.data.from_pydata([(0,0,0), (1,0,0), (1,1,0), (0,1,0)], [], [(0,1,2,3)])
        obj.data.normals_split_custom_set([(1, 0, 0)] * 4)
        obj.w3d_object_settings.geom_keep_normals = True
        actual = self.export()
        self.assertEqual(2, len(actual.triangles))
        for normal in actual.normals:
            self.assert_vector((1, 0, 0), normal)

    def test_smoothing_does_not_modify_a_shared_source_mesh(self):
        obj = self.new_object()
        other = bpy.data.objects.new('linked', obj.data)
        bpy.context.scene.collection.objects.link(other)
        other.w3d_object_settings.export_object = False
        before = [face.use_smooth for face in obj.data.polygons]
        self._w3d_export_options = {'smooth_vertex_normals': True}
        self.export()
        self.assertEqual(before, [face.use_smooth for face in obj.data.polygons])
        self.assertIs(obj.data, other.data)

    def test_vertex_alpha_converts_rgb_brightness_for_alpha_passes_only(self):
        obj = self.new_object()
        settings = obj.data.materials[0].w3d_material_settings
        overlay = settings.passes.add()
        overlay.shader.blend_mode = '5'
        overlay.opacity = 1
        obj.w3d_object_settings.geom_vertex_alpha = True
        layer = self.add_colors(obj, [(0.3, 0.6, 0.9, 0.05)] * 6)
        before = [tuple(d.color) for d in layer.data]
        actual = self.serialize(self.export())
        self.assertFalse(actual.material_passes[0].dcg)
        self.assertTrue(actual.material_passes[1].dcg)
        for color in actual.material_passes[1].dcg:
            self.assertEqual((255,255,255,153), (color.r,color.g,color.b,color.a))
        self.assertEqual(before, [tuple(d.color) for d in layer.data])
        obj.w3d_object_settings.geom_vertex_alpha = False
        self.assertFalse(self.export().material_passes[1].dcg)

    def test_vertex_alpha_supports_alpha_test_and_corner_discontinuities(self):
        obj = self.new_object()
        obj.data.materials[0].w3d_material_settings.passes[0].shader.blend_mode = '6'
        self.add_colors(obj, [(0,0,0,1)] * 3 + [(1,1,1,0)] * 3)
        obj.w3d_object_settings.geom_vertex_alpha = True
        actual = self.serialize(self.export())
        self.assertEqual(6, len(actual.verts))
        for index, triangle in enumerate(actual.triangles):
            for vertex_id in triangle.vert_ids:
                self.assertEqual(index * 255, actual.material_passes[0].dcg[vertex_id].a)

    def test_vertex_alpha_supports_point_colors(self):
        if bpy.app.version < (3, 2, 0):
            self.skipTest('Point color attributes require Blender 3.2')
        obj = self.new_object()
        obj.data.materials[0].w3d_material_settings.passes[0].shader.blend_mode = '5'
        self.add_colors(obj, [(0,0,0,1), (1,1,1,1), (0.5,0.5,0.5,1), (0.2,0.2,0.2,1)], domain='POINT')
        obj.w3d_object_settings.geom_vertex_alpha = True
        actual = self.serialize(self.export())
        self.assertEqual([0,255,127,51], [c.a for c in actual.material_passes[0].dcg])

    def test_vertex_alpha_warns_for_missing_colors_and_opaque_materials(self):
        obj = self.new_object()
        obj.w3d_object_settings.geom_vertex_alpha = True
        with patch.object(self, 'warning') as warning:
            self.export()
        warning.assert_any_call("mesh 'geometry': Vertex Alpha needs an active color attribute")
        self.add_colors(obj, [(1,1,1,1)] * 6)
        with patch.object(self, 'warning') as warning:
            self.export()
        warning.assert_any_call("mesh 'geometry': Vertex Alpha needs an alpha-blended or alpha-tested material pass")

    def test_imported_alpha_is_not_reinterpreted_as_rgb(self):
        source = get_mesh('imported', mat_count=1)
        source.material_passes[0].dcg[0].a = 37
        name = create_mesh(self, source, bpy.context.scene.collection)
        self.assertFalse(bpy.data.objects[name].w3d_object_settings.geom_vertex_alpha)
        actual = self.serialize(self.export())
        self.assertEqual(37, actual.material_passes[0].dcg[0].a)

    def test_w3x_supports_normal_and_alpha_operations_and_reports_w3d_only_flags(self):
        obj = self.new_object()
        obj.w3d_object_settings.geom_z_normal = True
        obj.w3d_object_settings.geom_vertex_alpha = True
        obj.w3d_object_settings.geom_prelit = True
        obj.data.materials[0].w3d_material_settings.passes[0].shader.blend_mode = '5'
        self.add_colors(obj, [(0.2,0.2,0.2,1)] * 6)
        self.set_format('W3X')
        with patch.object(self, 'warning') as warning:
            actual = self.export()
        warning.assert_any_call("mesh 'geometry': Shatter, Prelit and Always Dynamic Light "
                                'are W3D-only flags and cannot be stored in W3X')
        for normal in actual.normals:
            self.assertEqual((0,0,1), tuple(normal))
        for color in actual.material_passes[0].dcg:
            self.assertEqual(51, color.a)
        self.assertTrue(actual.material_passes[0].dcg)
