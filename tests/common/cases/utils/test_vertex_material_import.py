# <pep8 compliant>

import copy
import io
import os
from shutil import copyfile
from unittest.mock import patch

import bpy
from mathutils import Vector

from tests.utils import TestCase
from tests.common.helpers.mesh import get_mesh
from io_mesh_w3d.common.structs.mesh import Mesh
from io_mesh_w3d.common.structs.mesh_structs.texture import Texture, TextureInfo
from io_mesh_w3d.common.utils.helpers import get_uv, find_texture
from io_mesh_w3d.common.utils.mesh_import import create_mesh
from io_mesh_w3d.common.utils.mesh_export import retrieve_meshes
from io_mesh_w3d.w3d.io_binary import read_chunk_head
from io_mesh_w3d.w3d.structs.mesh_structs.material_pass import TextureStage


class TestVertexMaterialImport(TestCase):
    def terrain(self):
        source = get_mesh('terrain')
        source.textures = [Texture(id=name, file=name, texture_info=TextureInfo())
                           for name in ('rocks.dds', 'noise.dds', 'dirt.dds')]
        # Duplicate VM names are legal and must not alias different passes.
        source.vert_materials[1].vm_info.opacity = 0.75
        source.vert_materials[1].vm_info.shininess = 25.0
        for index, mat_pass in enumerate(source.material_passes):
            mat_pass.tx_stages = []
            for stage_index, texture_id in enumerate((index * 2, 1)):
                coords = [Vector((v * 0.1 + index, v * 0.2 + stage_index))
                          for v in range(len(source.verts))]
                mat_pass.tx_stages.append(TextureStage(tx_ids=[[texture_id]], tx_coords=[coords]))
            source.shaders[index].detail_color_func = 2
            source.shaders[index].post_detail_color_func = 2 + index
        source.shaders[1].src_blend = 2
        source.shaders[1].dest_blend = 5
        source.shaders[1].depth_mask = 0
        return source

    def import_mesh(self, source):
        name = create_mesh(self, source, bpy.context.scene.collection)
        return bpy.data.objects[name]

    def export_mesh(self):
        meshes, _ = retrieve_meshes(self, None, None, 'test')
        stream = io.BytesIO()
        meshes[0].write(stream)
        stream.seek(0)
        _, _, end = read_chunk_head(stream)
        return Mesh.read(self, stream, end)

    def test_map_two_passes_three_textures_import_and_roundtrip(self):
        source = self.terrain()
        before = copy.deepcopy(source)
        obj = self.import_mesh(source)
        self.assertEqual(1, len(obj.data.materials))
        configs = obj.data.materials[0].w3d_material_settings.passes
        self.assertEqual(2, len(configs))
        self.assertEqual('rocks.dds', configs[0].stage0.texture.name)
        self.assertEqual('dirt.dds', configs[1].stage0.texture.name)
        self.assertEqual(configs[0].stage1.texture, configs[1].stage1.texture)
        self.assertAlmostEqual(0.75, configs[1].opacity)
        self.assertAlmostEqual(25.0, configs[1].shininess)
        self.assertEqual('5', configs[1].shader.blend_mode)
        self.assertEqual([m.vm_name for m in before.vert_materials],
                         [m.vm_name for m in source.vert_materials])
        actual = self.export_mesh()
        self.assertEqual(2, len(actual.material_passes))
        self.assertEqual(['rocks.dds', 'noise.dds', 'dirt.dds'], [t.file for t in actual.textures])
        for index, mat_pass in enumerate(actual.material_passes):
            self.assertEqual([[index * 2], [1]], [stage.tx_ids[0] for stage in mat_pass.tx_stages])
            self.assertEqual(vars(source.shaders[index]), vars(actual.shaders[index]))
            self.assertEqual(source.vert_materials[index].vm_name, actual.vert_materials[index].vm_name)
            self.assertAlmostEqual(source.vert_materials[index].vm_info.opacity,
                                   actual.vert_materials[index].vm_info.opacity)
        self.assertAlmostEqual(25.0, actual.vert_materials[1].vm_info.shininess)

    def test_each_pass_stage_uses_its_own_uv_channel_and_image_node(self):
        source = self.terrain()
        obj = self.import_mesh(source)
        self.assertEqual(4, len(obj.data.uv_layers))
        material = obj.data.materials[0]
        images = [node for node in material.node_tree.nodes if node.type == 'TEX_IMAGE']
        self.assertEqual(4, len(images))
        for pass_index, config in enumerate(material.w3d_material_settings.passes):
            for stage_index in range(2):
                channel = getattr(config, f'uv_channel_stage{stage_index}') - 1
                self.assertEqual(pass_index * 2 + stage_index, channel)
                source_uvs = source.material_passes[pass_index].tx_stages[stage_index].tx_coords[0]
                for loop in obj.data.loops:
                    self.assertLess((get_uv(obj.data.uv_layers[channel], loop.index)
                                     - source_uvs[loop.vertex_index]).length, 1e-6)
        self.assertEqual({layer.name for layer in obj.data.uv_layers},
                         {node.inputs['Vector'].links[0].from_node.uv_map for node in images})

    def test_single_pass_two_stages_is_one_material(self):
        source = self.terrain()
        source.material_passes = source.material_passes[:1]
        source.vert_materials = source.vert_materials[:1]
        source.shaders = source.shaders[:1]
        source.textures = source.textures[:2]
        obj = self.import_mesh(source)
        self.assertEqual(1, len(obj.data.materials))
        self.assertEqual({0}, {face.material_index for face in obj.data.polygons})
        self.assertEqual(2, len(obj.data.uv_layers))
        self.assertEqual(2, len(self.export_mesh().material_passes[0].tx_stages))

    def test_per_face_texture_ids_choose_material_slots_not_texture_indices(self):
        source = self.terrain()
        source.material_passes = source.material_passes[:1]
        stage = source.material_passes[0].tx_stages[0]
        stage.tx_ids = [[2 if i % 2 == 0 else 0 for i in range(len(source.triangles))]]
        obj = self.import_mesh(source)
        self.assertEqual(2, len(obj.data.materials))
        for index, face in enumerate(obj.data.polygons):
            config = obj.data.materials[face.material_index].w3d_material_settings.passes[0]
            self.assertEqual('dirt.dds' if index % 2 == 0 else 'rocks.dds', config.stage0.texture.name)

    def test_absent_and_invalid_texture_ids_do_not_abort_import(self):
        source = self.terrain()
        source.material_passes[0].tx_stages[0].tx_ids = [[0xFFFFFFFF]]
        source.material_passes[1].tx_stages[0].tx_ids = [[900]]
        with patch.object(self, 'warning') as warning:
            obj = self.import_mesh(source)
        warning.assert_any_call("mesh 'terrain' references invalid texture 900; skipping texture")
        for config in obj.data.materials[0].w3d_material_settings.passes:
            self.assertFalse(config.stage0.enabled)
            self.assertTrue(config.stage1.enabled)

    def test_prelit_vertex_passes_use_the_same_stage_mapping(self):
        source = get_mesh('prelit', prelit=True)
        terrain = self.terrain()
        for name in ('vert_materials', 'shaders', 'textures', 'material_passes'):
            setattr(source.prelit_vertex, name, getattr(terrain, name))
        obj = self.import_mesh(source)
        configs = obj.data.materials[0].w3d_material_settings.passes
        self.assertEqual(2, len(configs))
        self.assertEqual('dirt.dds', configs[1].stage0.texture.name)

    def test_texture_animation_and_sampling_flags_survive(self):
        source = self.terrain()
        source.textures[1].texture_info = TextureInfo(
            attributes=0x1D, animation_type=1, frame_count=8, frame_rate=12.5)
        self.import_mesh(source)
        actual = self.export_mesh()
        self.assertEqual(vars(source.textures[1].texture_info), vars(actual.textures[1].texture_info))

    def test_w3x_conversion_keeps_both_pass_textures_and_uvs(self):
        source = self.terrain()
        self.import_mesh(source)
        self.set_format('W3X')
        meshes, used = retrieve_meshes(self, None, None, 'test')
        self.assertEqual(2, len(meshes[0].shader_materials))
        self.assertEqual(2, len(meshes[0].material_passes))
        for index, shader in enumerate(meshes[0].shader_materials):
            properties = {prop.name: prop.value for prop in shader.properties}
            self.assertEqual(('rocks.dds', 'dirt.dds')[index], properties['DiffuseTexture'])
            self.assertEqual('noise.dds', properties['Texture_1'])
            self.assertTrue(meshes[0].material_passes[index].tx_coords)
            self.assertTrue(meshes[0].material_passes[index].tx_coords_2)
        self.assertTrue({'rocks.tga', 'noise.tga', 'dirt.tga'}.issubset(used))

    def test_missing_texture_can_be_recovered_with_blender_find_missing_files(self):
        image = find_texture(self, 'elsewhere.dds')
        self.assertEqual('FILE', image.source)
        self.assertEqual('elsewhere.dds', os.path.basename(image.filepath))
        folder = os.path.join(self.outpath(), 'textures')
        os.makedirs(folder)
        target = os.path.join(folder, 'elsewhere.dds')
        copyfile(os.path.join('tests', 'testfiles', 'texture.dds'), target)
        self.assertEqual({'FINISHED'}, bpy.ops.file.find_missing_files(directory=folder))
        self.assertEqual(os.path.normcase(os.path.abspath(target)),
                         os.path.normcase(os.path.abspath(bpy.path.abspath(image.filepath))))
        image.reload()
        self.assertGreater(image.size[0], 1)

    def test_file_import_keeps_pass_stack_after_property_backfill(self):
        from io_mesh_w3d.w3d.import_w3d import load
        source = self.terrain()
        source.mat_info.texture_count = len(source.textures)
        self.filepath = os.path.join(self.outpath(), 'terrain.w3d')
        with open(self.filepath, 'wb') as stream:
            source.write(stream)
        self.assertEqual({'FINISHED'}, load(self))
        obj = bpy.data.objects['terrain']
        configs = obj.data.materials[0].w3d_material_settings.passes
        self.assertEqual(2, len(configs))
        self.assertEqual('rocks.dds', configs[0].stage0.texture.name)
        self.assertEqual('dirt.dds', configs[1].stage0.texture.name)
        self.assertEqual('noise.dds', configs[1].stage1.texture.name)
        self.assertEqual('5', configs[1].shader.blend_mode)
        self.assertEqual(3, configs[1].uv_channel_stage0)
        self.assertEqual(4, configs[1].uv_channel_stage1)
        actual = self.export_mesh()
        self.assertEqual(2, len(actual.material_passes))
        self.assertEqual(3, len(actual.textures))
        self.assertEqual(3, actual.shaders[1].post_detail_color_func)
