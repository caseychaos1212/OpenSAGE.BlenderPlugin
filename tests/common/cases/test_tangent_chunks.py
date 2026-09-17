# <pep8 compliant>

import io
import struct
from unittest.mock import patch

import bpy
from mathutils import Vector

from tests.utils import TestCase
from tests.common.helpers.mesh import get_mesh
from io_mesh_w3d.common.structs.mesh import (
    Mesh, GEOMETRY_TYPE_NPATCHABLE, VERTEX_CHANNEL_TANGENT, VERTEX_CHANNEL_BITANGENT,
)
from io_mesh_w3d.common.utils.mesh_import import create_mesh
from io_mesh_w3d.common.utils.mesh_export import retrieve_meshes
from io_mesh_w3d.w3d.io_binary import read_chunk_head
from io_mesh_w3d.w3d.structs.mesh_structs.material_pass import MaterialPass


class TestTangentChunks(TestCase):
    tangent_flags = VERTEX_CHANNEL_TANGENT | VERTEX_CHANNEL_BITANGENT

    def assert_vectors(self, expected, actual):
        self.assertEqual(len(expected), len(actual))
        for first, second in zip(expected, actual):
            for a, b in zip(first, second):
                self.assertAlmostEqual(a, b, places=6)

    def serialized_mesh(self, mesh):
        stream = io.BytesIO()
        mesh.write(stream)
        self.assertEqual(mesh.size(), stream.tell())
        stream.seek(0)
        _, _, end = read_chunk_head(stream)
        with patch.object(self, 'warning') as warning:
            result = Mesh.read(self, stream, end)
        warning.assert_not_called()
        self.assertEqual(end, stream.tell())
        return result

    def test_max_material_pass_chunks_read_and_write_exact_vectors(self):
        # Construct the Max layout independently of the plugin's serializer:
        # two arrays of float32 XYZ vectors, followed by an ordinary pass chunk.
        tangents = [(1.0, 0.25, -0.5), (0.0, 1.0, 0.0)]
        binormals = [(0.0, 0.0, 1.0), (-1.0, 0.0, 0.5)]
        payload = b''
        for chunk_id, vectors in ((0x60, tangents), (0x61, binormals)):
            data = b''.join(struct.pack('<3f', *vector) for vector in vectors)
            payload += struct.pack('<II', chunk_id, len(data)) + data
        payload += struct.pack('<III', 0x3A, 4, 7)
        stream = io.BytesIO(payload)
        with patch.object(self, 'warning') as warning:
            mat_pass = MaterialPass.read(self, stream, len(payload))
        warning.assert_not_called()
        self.assert_vectors(tangents, mat_pass.tangents)
        self.assert_vectors(binormals, mat_pass.bitangents)
        self.assertEqual([7], mat_pass.shader_ids)
        self.assertEqual(len(payload), stream.tell())

        output = io.BytesIO()
        mat_pass.write(output)
        self.assertEqual(mat_pass.size(), output.tell())
        output.seek(0)
        chunk, _, end = read_chunk_head(output)
        self.assertEqual(0x38, chunk)
        actual = MaterialPass.read(self, output, end)
        self.assert_vectors(tangents, actual.tangents)
        self.assert_vectors(binormals, actual.bitangents)
        self.assertEqual([7], actual.shader_ids)

    def test_empty_and_independent_tangent_channels_have_correct_sizes(self):
        for tangents, bitangents in (([], []), ([Vector((1, 0, 0))], []), ([], [Vector((0, 1, 0))])):
            with self.subTest(tangents=bool(tangents), bitangents=bool(bitangents)):
                mat_pass = MaterialPass(tangents=tangents, bitangents=bitangents)
                stream = io.BytesIO()
                mat_pass.write(stream)
                self.assertEqual(8 + (20 if tangents or bitangents else 0), stream.tell())
                self.assertEqual(mat_pass.size(), stream.tell())
                stream.seek(0)
                _, _, end = read_chunk_head(stream)
                actual = MaterialPass.read(self, stream, end)
                self.assert_vectors(tangents, actual.tangents)
                self.assert_vectors(bitangents, actual.bitangents)

    def test_mesh_level_vectors_are_read_instead_of_discarded(self):
        source = get_mesh(shader_mats=True)
        actual = self.serialized_mesh(source)
        self.assert_vectors(source.tangents, actual.tangents)
        self.assert_vectors(source.bitangents, actual.bitangents)

    def test_mesh_and_pass_vectors_remain_separate(self):
        source = get_mesh(shader_mats=True)
        source.material_passes[0].tangents = [Vector((1, 0, 0)) for _ in source.verts]
        source.material_passes[0].bitangents = [Vector((0, 1, 0)) for _ in source.verts]
        actual = self.serialized_mesh(source)
        self.assert_vectors(source.tangents, actual.tangents)
        self.assert_vectors(source.bitangents, actual.bitangents)
        self.assert_vectors(source.material_passes[0].tangents, actual.material_passes[0].tangents)
        self.assert_vectors(source.material_passes[0].bitangents, actual.material_passes[0].bitangents)

    def test_prelit_pass_tangents_import_without_unknown_chunk_warnings(self):
        source = get_mesh('prelit', prelit=True)
        for prelit in (source.prelit_unlit, source.prelit_vertex,
                       source.prelit_lightmap_multi_pass, source.prelit_lightmap_multi_texture):
            prelit.material_passes[0].tangents = [Vector((1, 0, 0)) for _ in source.verts]
            prelit.material_passes[0].bitangents = [Vector((0, 1, 0)) for _ in source.verts]
        actual = self.serialized_mesh(source)
        for name in ('prelit_unlit', 'prelit_vertex', 'prelit_lightmap_multi_pass', 'prelit_lightmap_multi_texture'):
            self.assert_vectors(getattr(source, name).material_passes[0].tangents,
                                getattr(actual, name).material_passes[0].tangents)
            self.assert_vectors(getattr(source, name).material_passes[0].bitangents,
                                getattr(actual, name).material_passes[0].bitangents)
        obj_name = create_mesh(self, actual, bpy.context.scene.collection)
        self.assertTrue(bpy.data.objects[obj_name].w3d_object_settings.geom_tangents)

    def test_import_recognizes_pass_vectors_even_without_npatchable_flag(self):
        source = get_mesh('nested', mat_count=1)
        source.material_passes[0].tangents = [Vector((1, 0, 0)) for _ in source.verts]
        source.material_passes[0].bitangents = [Vector((0, 1, 0)) for _ in source.verts]
        obj_name = create_mesh(self, self.serialized_mesh(source), bpy.context.scene.collection)
        obj = bpy.data.objects[obj_name]
        self.assertTrue(obj.w3d_object_settings.geom_tangents)
        # Exercise more than one exported pass; Max puts the basis in pass zero only.
        obj.data.materials[0].w3d_material_settings.passes.add()
        exported, _ = retrieve_meshes(self, None, None, 'tangent')
        actual = self.serialized_mesh(exported[0])
        self.assertTrue(actual.header.attrs & GEOMETRY_TYPE_NPATCHABLE)
        self.assertEqual(self.tangent_flags, actual.header.vert_channel_flags & self.tangent_flags)
        self.assertEqual([], actual.tangents)
        self.assertEqual([], actual.bitangents)
        self.assertEqual(2, len(actual.material_passes))
        self.assertEqual(actual.header.vert_count, len(actual.material_passes[0].tangents))
        self.assertEqual(actual.header.vert_count, len(actual.material_passes[0].bitangents))
        self.assertEqual([], actual.material_passes[1].tangents)
        self.assertEqual([], actual.material_passes[1].bitangents)
        # Import the exported file again and keep the setting active.
        again = create_mesh(self, actual, bpy.context.scene.collection)
        self.assertTrue(bpy.data.objects[again].w3d_object_settings.geom_tangents)

    def test_npatchable_flag_restores_tangents_checkbox(self):
        source = get_mesh('flagged', mat_count=1)
        source.header.attrs |= GEOMETRY_TYPE_NPATCHABLE
        obj_name = create_mesh(self, source, bpy.context.scene.collection)
        self.assertTrue(bpy.data.objects[obj_name].w3d_object_settings.geom_tangents)

    def test_turning_off_tangents_removes_pass_vectors_and_flags(self):
        source = get_mesh('disabled', mat_count=1)
        source.header.attrs |= GEOMETRY_TYPE_NPATCHABLE
        obj_name = create_mesh(self, source, bpy.context.scene.collection)
        bpy.data.objects[obj_name].w3d_object_settings.geom_tangents = False
        exported, _ = retrieve_meshes(self, None, None, 'tangent')
        actual = self.serialized_mesh(exported[0])
        self.assertFalse(actual.header.attrs & GEOMETRY_TYPE_NPATCHABLE)
        self.assertFalse(actual.header.vert_channel_flags & self.tangent_flags)
        self.assertEqual([], actual.material_passes[0].tangents)
        self.assertEqual([], actual.material_passes[0].bitangents)

    def test_shader_mesh_tangents_work_with_and_without_geometry_checkbox(self):
        source = get_mesh('shader', shader_mats=True)
        obj_name = create_mesh(self, source, bpy.context.scene.collection)
        settings = bpy.data.objects[obj_name].w3d_object_settings
        self.assertFalse(settings.geom_tangents)
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                settings.geom_tangents = enabled
                exported, _ = retrieve_meshes(self, None, None, 'tangent')
                actual = self.serialized_mesh(exported[0])
                self.assertEqual(actual.header.vert_count, len(actual.tangents))
                self.assertEqual(actual.header.vert_count, len(actual.bitangents))
                self.assertEqual(self.tangent_flags, actual.header.vert_channel_flags & self.tangent_flags)
                self.assertEqual(enabled, bool(actual.header.attrs & GEOMETRY_TYPE_NPATCHABLE))
                self.assertEqual(enabled, bool(actual.material_passes[0].tangents))

    def test_missing_uvs_warn_without_claiming_tangent_channels(self):
        source = get_mesh('no_uv', mat_count=1)
        obj_name = create_mesh(self, source, bpy.context.scene.collection)
        obj = bpy.data.objects[obj_name]
        obj.w3d_object_settings.geom_tangents = True
        while obj.data.uv_layers:
            obj.data.uv_layers.remove(obj.data.uv_layers[0])
        with patch.object(self, 'warning') as warning:
            exported, _ = retrieve_meshes(self, None, None, 'tangent')
        warning.assert_any_call("mesh 'no_uv' cannot export Tangents without UV coordinates and a material pass")
        actual = self.serialized_mesh(exported[0])
        self.assertFalse(actual.header.attrs & GEOMETRY_TYPE_NPATCHABLE)
        self.assertFalse(actual.header.vert_channel_flags & self.tangent_flags)
        self.assertEqual([], actual.material_passes[0].tangents)
        self.assertEqual([], actual.material_passes[0].bitangents)
        self.assertTrue(obj.w3d_object_settings.geom_tangents)
