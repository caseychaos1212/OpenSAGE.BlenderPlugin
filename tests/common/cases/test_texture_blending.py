# <pep8 compliant>

import io
import os
from unittest.mock import patch

import bpy
from tests.utils import TestCase
from tests.common.helpers.mesh import get_mesh
from io_mesh_w3d.common.structs.mesh import Mesh
from io_mesh_w3d.common.structs.rgba import RGBA
from io_mesh_w3d.common.utils.mesh_import import create_mesh
from io_mesh_w3d.common.utils.mesh_export import retrieve_meshes
from io_mesh_w3d.common.utils.material_preview import create_pass_preview
from io_mesh_w3d.texture_blending import color_layers, ensure_blend_mask, refresh_preview
from io_mesh_w3d.w3d.io_binary import read_chunk_head


class TestTextureBlending(TestCase):
    def setup_blend(self):
        mesh = bpy.data.meshes.new('Terrain')
        mesh.from_pydata([(-1, -1, 0), (0, -1, 0), (1, -1, 0),
                          (-1, 1, 0), (0, 1, 0), (1, 1, 0)], [],
                         [(0, 1, 4, 3), (1, 2, 5, 4)])
        mesh.uv_layers.new()
        for loop in mesh.loops:
            mesh.uv_layers[0].data[loop.index].uv = mesh.vertices[loop.vertex_index].co.xy
        obj = bpy.data.objects.new('Terrain', mesh)
        bpy.context.scene.collection.objects.link(obj)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        self.assertEqual({'FINISHED'}, bpy.ops.w3d.create_texture_blend())
        return obj

    def export(self):
        meshes, _ = retrieve_meshes(self, None, None, 'terrain')
        self.assertEqual(1, len(meshes))
        stream = io.BytesIO()
        meshes[0].write(stream)
        stream.seek(0)
        _, _, end = read_chunk_head(stream)
        return Mesh.read(self, stream, end)

    def image(self, name, color):
        image = bpy.data.images.new(name + '.tga', width=2, height=2, alpha=True, float_buffer=True)
        image.colorspace_settings.name = 'Non-Color'
        image.pixels[:] = list(color) * 4
        image.filepath_raw = os.path.join(self.outpath(), name + '.tga')
        image.update()
        return image

    def test_create_paint_export_reimport_preserves_mask_seams_and_source(self):
        obj = self.setup_blend()
        settings = obj.active_material.w3d_material_settings
        settings.passes[0].stage0.texture = self.image('base', (1, 0, 0, 1))
        settings.passes[1].stage0.texture = self.image('blend', (0, 1, 0, 1))
        self.assertEqual({'FINISHED'}, bpy.ops.w3d.paint_blend_mask())
        self.assertEqual('VERTEX_PAINT', obj.mode)
        bpy.ops.object.mode_set(mode='OBJECT')
        layer = color_layers(obj.data)[settings.passes[1].blend_mask]
        for face in obj.data.polygons:
            for index in face.loop_indices:
                value = float(face.index)
                layer.data[index].color = (value, value, value, 1)
        before = [tuple(value.color) for value in layer.data]
        actual = self.export()
        self.assertEqual(2, len(actual.material_passes))
        self.assertFalse(actual.material_passes[0].dcg)
        self.assertEqual((2, 5), (actual.shaders[1].src_blend, actual.shaders[1].dest_blend))
        for triangle in actual.triangles:
            x = sum(actual.verts[i].x for i in triangle.vert_ids) / 3
            self.assertEqual({0 if x < 0 else 255},
                             {actual.material_passes[1].dcg[i].a for i in triangle.vert_ids})
        self.assertEqual(6, len(obj.data.vertices))
        self.assertEqual(before, [tuple(value.color) for value in layer.data])
        imported = bpy.data.objects[create_mesh(self, actual, bpy.context.scene.collection)]
        dcg = color_layers(imported.data)['DCG_1']
        for loop in imported.data.loops:
            self.assertAlmostEqual(actual.material_passes[1].dcg[loop.vertex_index].a / 255,
                                   dcg.data[loop.index].color[3])

    def test_each_pass_exports_its_own_mask_without_active_color_dependency(self):
        obj = self.setup_blend()
        settings = obj.active_material.w3d_material_settings
        for index, value in ((1, 0.25), (2, 0.75)):
            config = settings.passes[index] if index == 1 else settings.passes.add()
            config.shader.blend_mode = '5'
            mask = ensure_blend_mask(obj, config, index)
            for datum in mask.data:
                datum.color = (value, value, value, 1)
        actual = self.export()
        for index, value in ((1, 0.25), (2, 0.75)):
            self.assertTrue(all(abs(color.a - int(value * 255)) <= 1
                                for color in actual.material_passes[index].dcg))

    def test_painting_imported_blend_starts_from_existing_alpha(self):
        source = get_mesh('ImportedTerrain')
        source.shaders[1].src_blend = 2
        source.shaders[1].dest_blend = 5
        source.material_passes[1].dcg = [RGBA(r=255, g=255, b=255, a=i * 30) for i in range(8)]
        obj = bpy.data.objects[create_mesh(self, source, bpy.context.scene.collection)]
        settings = obj.active_material.w3d_material_settings
        mask = ensure_blend_mask(obj, settings.passes[1], 1)
        for loop in obj.data.loops:
            expected = source.material_passes[1].dcg[loop.vertex_index].a / 255
            self.assertAlmostEqual(expected, mask.data[loop.index].color[0], delta=0.005)

    def test_missing_named_mask_reports_export_error(self):
        obj = self.setup_blend()
        obj.active_material.w3d_material_settings.passes[1].blend_mask = 'Deleted mask'
        with patch.object(self, 'error') as report:
            meshes, _ = retrieve_meshes(self, None, None, 'terrain')
        self.assertEqual([], meshes)
        self.assertTrue(any('Deleted mask' in call.args[0] for call in report.call_args_list))

    def test_preview_rebuild_does_not_accumulate_nodes_or_change_settings(self):
        obj = self.setup_blend()
        material = obj.active_material
        config = material.w3d_material_settings.passes[1]
        mask_name = config.blend_mask
        count = len(material.node_tree.nodes)
        refresh_preview(obj)
        refresh_preview(obj)
        self.assertEqual(count, len(material.node_tree.nodes))
        self.assertEqual(mask_name, config.blend_mask)
        self.assertEqual('5', config.shader.blend_mode)
        self.assertEqual(1.0, material.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value)

    def test_editing_imported_detail_controls_updates_exported_runtime_modes(self):
        obj = self.setup_blend()
        config = obj.active_material.w3d_material_settings.passes[1]
        config['_w3d_shader_extra'] = {'post_detail_color_func': 2, 'post_detail_alpha_func': 0,
                                      'color_mask': 1}
        config.shader.detail_color = '7'
        config.shader.detail_alpha = '3'
        refresh_preview(obj)
        actual = self.export().shaders[1]
        self.assertEqual(7, actual.detail_color_func)
        self.assertEqual(7, actual.post_detail_color_func)
        self.assertEqual(3, actual.post_detail_alpha_func)
        self.assertEqual(1, actual.color_mask)

    def render_values(self, obj, channel='Base Color'):
        # Render the actual generated shader calculation as emission, so
        # lighting/color management cannot hide an incorrect blend factor.
        scene = bpy.context.scene
        scene.render.engine = 'CYCLES'
        scene.cycles.device = 'CPU'
        scene.cycles.samples = 16
        scene.cycles.use_denoising = False
        scene.cycles.pixel_filter_type = 'BOX'
        scene.render.filter_size = 0.01
        scene.render.resolution_x = scene.render.resolution_y = 8
        scene.render.resolution_percentage = 100
        if scene.camera is None:
            camera = bpy.data.cameras.new('TestCamera')
            camera.type = 'ORTHO'
            camera.ortho_scale = 1.5
            scene.camera = bpy.data.objects.new('TestCamera', camera)
            scene.collection.objects.link(scene.camera)
            scene.camera.location = (0, 0, 3)
        material = obj.active_material
        tree = material.node_tree
        output = tree.nodes.get('Material Output')
        emitter = tree.nodes.get('TestEmission') or tree.nodes.new('ShaderNodeEmission')
        emitter.name = 'TestEmission'
        source = tree.nodes['Principled BSDF'].inputs[channel]
        for link in list(emitter.inputs['Color'].links):
            tree.links.remove(link)
        if source.is_linked:
            tree.links.new(source.links[0].from_socket, emitter.inputs['Color'])
        else:
            value = source.default_value
            emitter.inputs['Color'].default_value = ((value, value, value, 1)
                                                     if channel == 'Alpha' else value)
        tree.links.new(emitter.outputs[0], output.inputs['Surface'])
        scene.render.image_settings.file_format = 'OPEN_EXR'
        scene.render.image_settings.color_depth = '32'
        scene.render.filepath = os.path.join(self.outpath(), 'blend.exr')
        obj.data.update()
        bpy.context.view_layer.update()
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(scene.render.filepath, check_existing=False)
        rgb = tuple(image.pixels[(4 * 8 + 4) * 4:(4 * 8 + 4) * 4 + 3])
        bpy.data.images.remove(image)
        return rgb

    def assertRGB(self, expected, actual):
        for a, b in zip(expected, actual):
            self.assertAlmostEqual(a, b, delta=0.008)

    def test_rendered_painted_transition_combines_vertex_texture_and_opacity_alpha(self):
        obj = self.setup_blend()
        settings = obj.active_material.w3d_material_settings
        settings.passes[0].stage0.texture = self.image('base', (1, 0, 0, 1))
        overlay = settings.passes[1]
        overlay.stage0.texture = self.image('overlay', (0, 1, 0, 0.5))
        overlay.opacity = 0.5
        mask = color_layers(obj.data)[overlay.blend_mask]
        refresh_preview(obj)
        for value, expected in ((0, (1, 0, 0)), (0.5, (0.875, 0.125, 0)), (1, (0.75, 0.25, 0))):
            with self.subTest(mask=value):
                for datum in mask.data:
                    datum.color = (value, value, value, 1)
                self.assertRGB(expected, self.render_values(obj))
        self.assertRGB((1, 1, 1), self.render_values(obj, 'Alpha'))

    def test_rendered_detail_blend_modes_follow_engine_stage_order(self):
        obj = self.setup_blend()
        settings = obj.active_material.w3d_material_settings
        settings.passes.remove(1)
        config = settings.passes[0]
        config.stage0.texture = self.image('base', (0.2, 0.4, 0.6, 0.25))
        config.stage1.enabled = True
        config.stage1.texture = self.image('detail', (0.7, 0.3, 0.1, 0.75))
        expected = [(0.2, 0.4, 0.6), (0.7, 0.3, 0.1), (0.14, 0.12, 0.06),
                    (0.76, 0.58, 0.64), (0.9, 0.7, 0.7), (0.5, 0, 0),
                    (0, 0.1, 0.5), (0.575, 0.325, 0.225), (0.325, 0.375, 0.475)]
        for mode, color in enumerate(expected):
            with self.subTest(mode=mode):
                config.shader.detail_color = str(mode)
                create_pass_preview(obj.active_material, obj.data)
                self.assertRGB(color, self.render_values(obj))
        config.shader.blend_mode = '5'
        for mode, alpha in enumerate((0.25, 0.75, 0.1875, 0.8125)):
            with self.subTest(alpha_mode=mode):
                config.shader.detail_alpha = str(mode)
                create_pass_preview(obj.active_material, obj.data)
                self.assertRGB((alpha,) * 3, self.render_values(obj, 'Alpha'))
