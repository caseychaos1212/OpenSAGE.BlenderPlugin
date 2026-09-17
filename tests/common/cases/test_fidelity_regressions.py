"""Serialized fidelity checks shared by the Renegade and C&C3 workflows."""
import io

import bpy
from mathutils import Quaternion, Vector

from tests.utils import TestCase
from tests.common.helpers.mesh import get_mesh
from tests.common.helpers.hierarchy import get_hierarchy
from tests.common.helpers.hlod import get_hlod
from tests.w3d.helpers.mesh_structs.material_pass import get_uvs
from io_mesh_w3d.common.structs.data_context import DataContext
from io_mesh_w3d.common.structs.hierarchy import Hierarchy
from io_mesh_w3d.common.structs.mesh import Mesh
from io_mesh_w3d.common.structs.mesh_structs.shader_material import ShaderMaterialProperty
from io_mesh_w3d.common.utils.hierarchy_import import create_bone_hierarchy
from io_mesh_w3d.common.utils.hierarchy_export import retrieve_hierarchy
from io_mesh_w3d.common.utils.mesh_import import create_mesh
from io_mesh_w3d.common.utils.mesh_export import retrieve_meshes
from io_mesh_w3d.common.utils.material_settings_bridge import snapshot_material_state
from io_mesh_w3d.export_utils import save_data
from io_mesh_w3d.import_utils import create_data
from io_mesh_w3d.w3d.io_binary import read_chunk_head
from io_mesh_w3d.w3x.io_xml import create_root, find_root, write_struct
from io_mesh_w3d.w3x.import_w3x import load, load_file


class TestFidelityRegressions(TestCase):
    def serialized_mesh(self, mesh):
        if self.file_format == 'W3X':
            root = create_root()
            mesh.create(root)
            return Mesh.parse(self, root.find('W3DMesh'))
        stream = io.BytesIO()
        mesh.write(stream)
        stream.seek(0)
        _, _, end = read_chunk_head(stream)
        return Mesh.read(self, stream, end)

    def check_shader_roundtrip(self, file_format, dual_texture):
        self.set_format(file_format)
        source = get_mesh('fidelity', shader_mats=True)
        if file_format == 'W3X':
            source.material_passes[0].tx_coords_2 = [Vector((uv.y, uv.x)) for uv in get_uvs()]
        shader = source.shader_materials[0]
        shader.header.type_name = 'ObjectsGeneric.fx'
        shader.header.technique = 7
        diffuse = 'ColorDiffuse' if file_format == 'W3X' else 'DiffuseColor'
        shininess = 'Shininess' if file_format == 'W3X' else 'SpecularExponent'
        shader.properties = [
            ShaderMaterialProperty(type=5, name=diffuse, value=Vector((0.2, 0.4, 0.6, 1))),
            ShaderMaterialProperty(type=2, name=shininess, value=60.0),
            ShaderMaterialProperty(type=7, name='AlphaTestEnable', value=True),
            ShaderMaterialProperty(type=2, name='Opacity', value=1.0),
            ShaderMaterialProperty(type=1, name='Texture_0' if dual_texture else 'DiffuseTexture', value='base.dds')]
        if dual_texture:
            shader.properties.extend([
                ShaderMaterialProperty(type=1, name='Texture_1', value='detail.dds'),
                ShaderMaterialProperty(type=6, name='NumTextures', value=2)])
        create_mesh(self, source, bpy.context.scene.collection)
        material = bpy.data.objects['fidelity'].data.materials[0]
        # Imported materials have Renegade pass settings too. They must not
        # overwrite the shader's independent opacity/alpha-test/texture values.
        material.w3d_material_settings.passes.add().opacity = 0.25
        before = snapshot_material_state(material)
        meshes, _ = retrieve_meshes(self, None, None, 'fidelity')
        self.assertEqual(before, snapshot_material_state(material))
        actual = self.serialized_mesh(meshes[0])
        self.assertEqual(1, len(actual.material_passes))
        self.assertEqual(7, actual.shader_materials[0].header.technique)
        for name in (('tx_coords', 'tx_coords_2') if file_format == 'W3X' else ('tx_coords',)):
            expected_uvs = getattr(source.material_passes[0], name)
            actual_uvs = getattr(actual.material_passes[0], name)
            self.assertEqual(len(expected_uvs), len(actual_uvs))
            for expected, exported in zip(expected_uvs, actual_uvs):
                self.assertLess((expected.xy - exported.xy).length, 0.0001)
        properties = {prop.name: prop.value for prop in actual.shader_materials[0].properties}
        self.assertEqual(tuple(shader.properties[0].value), tuple(properties[diffuse]))
        self.assertAlmostEqual(60.0, properties[shininess], places=4)
        self.assertTrue(properties.get('AlphaTestEnable', True))
        self.assertAlmostEqual(1.0, properties.get('Opacity', 1.0))
        if dual_texture:
            self.assertEqual(2, properties['NumTextures'])
            self.assertEqual('detail.dds', properties['Texture_1'])
        wrong_diffuse = 'DiffuseColor' if file_format == 'W3X' else 'ColorDiffuse'
        self.assertNotIn(wrong_diffuse, properties)

    def test_w3x_single_texture_shader_and_uvs(self):
        self.check_shader_roundtrip('W3X', False)

    def test_w3x_dual_texture_shader_and_uvs(self):
        self.check_shader_roundtrip('W3X', True)

    def test_w3d_shader_keeps_binary_constants_and_uvs(self):
        self.check_shader_roundtrip('W3D', True)

    def test_w3d_vertex_material_keeps_two_passes_and_stages(self):
        source = get_mesh('passes', mat_count=1)
        create_mesh(self, source, bpy.context.scene.collection)
        material = bpy.data.objects['passes'].data.materials[0]
        passes = material.w3d_material_settings.passes
        passes.add()
        for index, mat_pass in enumerate(passes):
            mat_pass.opacity = 0.25 + index * 0.5
            for stage_index, stage in enumerate((mat_pass.stage0, mat_pass.stage1)):
                stage.enabled = True
                stage.texture = bpy.data.images.new('p%d_s%d.dds' % (index, stage_index), 1, 1)
                stage.frames = 4 + index
                stage.fps = 12.0
        before = snapshot_material_state(material)
        meshes, _ = retrieve_meshes(self, None, None, 'passes')
        self.assertEqual(before, snapshot_material_state(material))
        actual = self.serialized_mesh(meshes[0])
        self.assertEqual(2, len(actual.material_passes))
        self.assertEqual(4, len(actual.textures))
        self.assertEqual(0, len(actual.shader_materials))
        for index, mat_pass in enumerate(actual.material_passes):
            self.assertEqual(2, len(mat_pass.tx_stages))
            self.assertAlmostEqual(0.25 + index * 0.5, actual.vert_materials[index].vm_info.opacity)
            for stage in mat_pass.tx_stages:
                self.assertEqual(len(actual.verts), len(stage.tx_coords[0]))
                texture = actual.textures[stage.tx_ids[0][0]]
                self.assertEqual(4 + index, texture.texture_info.frame_count)
                self.assertAlmostEqual(12.0, texture.texture_info.frame_rate)

    def check_hierarchy_generations(self, file_format):
        self.set_format(file_format)
        expected = get_hierarchy('fidelity')
        expected.pivot_fixups = []
        actual = expected
        for generation in range(3):
            bpy.ops.wm.read_homefile(use_empty=True)
            rig = create_bone_hierarchy(actual, bpy.context.scene.collection)
            self.assertIn('ROOTTRANSFORM', rig.data.bones)
            actual, _ = retrieve_hierarchy(self, 'fidelity')
            if file_format == 'W3X':
                root = create_root()
                actual.create(root)
                actual = Hierarchy.parse(self, root.find('W3DHierarchy'))
            else:
                stream = io.BytesIO()
                actual.write(stream)
                stream.seek(0)
                _, _, end = read_chunk_head(stream)
                actual = Hierarchy.read(self, stream, end)
            self.assertEqual(len(expected.pivots), len(actual.pivots))
            self.assertEqual(1, sum(p.name == 'ROOTTRANSFORM' for p in actual.pivots))
            for before, after in zip(expected.pivots, actual.pivots):
                self.assertEqual((before.name, before.parent_id), (after.name, after.parent_id))
                self.assertLess((before.translation - after.translation).length, 0.001)
                self.assertAlmostEqual(
                    1.0, abs(
                        before.rotation.normalized().dot(
                            after.rotation.normalized())), places=5)

    def test_w3x_repeated_hierarchy_roundtrip(self):
        self.check_hierarchy_generations('W3X')

    def test_w3d_repeated_hierarchy_roundtrip(self):
        self.check_hierarchy_generations('W3D')

    def test_w3x_mesh_mode_ignores_renegade_override(self):
        self.set_format('W3X')
        bpy.context.scene.w3d_scene_settings.use_renegade_workflow = True
        bpy.ops.mesh.primitive_cube_add()
        self.filepath = self.outpath('mesh.w3x')
        settings = {'mode': 'M'}
        self.assertEqual({'FINISHED'}, save_data(self, settings))
        self.assertEqual('M', settings['mode'])
        root = find_root(self, self.filepath)
        self.assertIsNotNone(root.find('W3DMesh'))
        self.assertIsNone(root.find('W3DHierarchy'))
        self.assertIsNone(root.find('W3DContainer'))

    def test_duplicate_object_names_keep_rigid_parenting(self):
        hierarchy = get_hierarchy()
        hlod = get_hlod()
        hlod.aggregate_array = hlod.proxy_array = None
        source = get_mesh('sword')
        create_data(self, [source], hlod, hierarchy)
        create_data(self, [source], hlod, hierarchy)
        self.assertEqual('sword', source.name())
        for name in ('sword', 'sword.001'):
            self.assertEqual('BONE', bpy.data.objects[name].parent_type)
            self.assertEqual('sword_bone', bpy.data.objects[name].parent_bone)

    def test_w3x_shared_and_cyclic_includes_load_once(self):
        self.set_format('W3X')
        mesh_path = self.outpath('model.w3x')
        write_struct(get_mesh('included', shader_mats=True), mesh_path)
        self.filepath = self.outpath('entry.w3x')
        with open(self.filepath, 'w') as file:
            file.write('<AssetDeclaration><Includes><Include source="model.w3x"/>'
                       '<Include source="nested.w3x"/></Includes></AssetDeclaration>')
        with open(self.outpath('nested.w3x'), 'w') as file:
            file.write('<AssetDeclaration><Includes><Include source="model.w3x"/>'
                       '<Include source="entry.w3x"/></Includes></AssetDeclaration>')
        data = DataContext(meshes=[], textures=[], collision_boxes=[])
        self.assertTrue(load_file(self, data))
        self.assertEqual(['included'], [mesh.name() for mesh in data.meshes])

    def test_w3x_existing_dependency_is_reused(self):
        self.set_format('W3X')
        self.filepath = self.outpath('model.w3x')
        write_struct(get_mesh('included', shader_mats=True), self.filepath)
        self.assertEqual({'FINISHED'}, load(self))
        original = bpy.data.objects['included']
        self.filepath = self.outpath('entry.w3x')
        with open(self.filepath, 'w') as file:
            file.write('<AssetDeclaration><Includes><Include source="model.w3x"/>'
                       '</Includes></AssetDeclaration>')
        self.assertEqual({'FINISHED'}, load(self))
        self.assertEqual([original], [obj for obj in bpy.context.scene.objects if obj.type == 'MESH'])

    def test_vertex_colors_survive_w3x_and_w3d_serialization(self):
        for format in ('W3X', 'W3D'):
            with self.subTest(format=format):
                bpy.ops.wm.read_homefile(use_empty=True)
                self.set_format(format)
                source = get_mesh('colors', shader_mats=True)
                create_mesh(self, source, bpy.context.scene.collection)
                meshes, _ = retrieve_meshes(self, None, None, 'colors')
                actual = self.serialized_mesh(meshes[0])
                expected_colors = source.material_passes[0].dcg
                actual_colors = actual.material_passes[0].dcg
                self.assertEqual(len(expected_colors), len(actual_colors))
                self.assertGreater(len(actual_colors), 0)
                for before, after in zip(expected_colors, actual_colors):
                    self.assertLess((Vector(before.to_vector_rgba()) - Vector(after.to_vector_rgba())).length, 0.01)

    def check_root_animation(self, file_format):
        from io_mesh_w3d.common.structs.animation import Animation, AnimationChannel, AnimationHeader, CHANNEL_Q
        from io_mesh_w3d.common.utils.animation_import import create_animation
        from io_mesh_w3d.common.utils.animation_export import retrieve_animation
        self.set_format(file_format)
        hierarchy = get_hierarchy('fidelity')
        rig = create_bone_hierarchy(hierarchy, bpy.context.scene.collection)
        rotations = [Quaternion((1, 0, 0, 0)), Quaternion((0.9238795, 0, 0, 0.3826834))]
        source = Animation(header=AnimationHeader(name='move', hierarchy_name='fidelity', num_frames=2), channels=[
            AnimationChannel(first_frame=0, last_frame=1, type=0, pivot=0, data=[3.0, 4.0]),
            AnimationChannel(first_frame=0, last_frame=1, type=CHANNEL_Q, pivot=0, vector_len=4, data=rotations)])
        create_animation(self, rig, source, hierarchy)
        for timecoded in (False, True):
            actual = retrieve_animation(self, 'move', hierarchy, rig, timecoded)
            channels = actual.time_coded_channels if timecoded else actual.channels
            self.assertEqual(2, len(channels))
            for channel in channels:
                values = [key.value for key in channel.time_codes] if timecoded else channel.data
                self.assertEqual(2, len(values))
                if channel.type == 0:
                    for expected, value in zip((3.0, 4.0), values):
                        self.assertAlmostEqual(expected, value, places=5)
                else:
                    for expected, value in zip(rotations, values):
                        self.assertAlmostEqual(1.0, abs(expected.normalized().dot(value)), places=5)
        bpy.context.scene.frame_set(1)
        exported, _ = retrieve_hierarchy(self, 'fidelity')
        self.assertLess((hierarchy.pivots[0].translation - exported.pivots[0].translation).length, 0.0001)

    def test_w3x_root_animation_offsets_roundtrip(self):
        self.check_root_animation('W3X')

    def test_w3d_root_animation_offsets_roundtrip(self):
        self.check_root_animation('W3D')

    def test_w3x_rigid_animation_keeps_first_rotation_and_channel_range(self):
        from tests.common.helpers.animation import get_animation_empty, get_animation_channel
        from io_mesh_w3d.common.utils.animation_import import create_animation
        from io_mesh_w3d.common.utils.animation_export import retrieve_animation
        from io_mesh_w3d.common.structs.animation import CHANNEL_Q
        self.set_format('W3X')
        hierarchy = get_hierarchy('fidelity')
        hlod = get_hlod(hierarchy_name='fidelity', attachments=False)
        create_data(self, [get_mesh('sword')], hlod, hierarchy)
        rig = bpy.data.objects['fidelity']
        animation = get_animation_empty()
        channel = get_animation_channel(type=CHANNEL_Q, pivot=7)
        channel.first_frame, channel.last_frame = 2, 3
        channel.data = [Quaternion((0.9238795, 0, 0, 0.3826834)), Quaternion((0.7071068, 0, 0, 0.7071068))]
        animation.channels = [channel]
        create_animation(self, rig, animation, hierarchy)
        actual = retrieve_animation(self, 'move', hierarchy, rig, False)
        self.assertEqual(1, len(actual.channels))
        self.assertEqual((2, 3), (actual.channels[0].first_frame, actual.channels[0].last_frame))
        for expected, value in zip(channel.data, actual.channels[0].data):
            self.assertAlmostEqual(1.0, abs(expected.normalized().dot(value)), places=5)

    def test_w3d_translation_baseline_preserves_first_key_and_other_axes(self):
        from tests.common.helpers.animation import get_animation_empty, get_animation_channel
        from io_mesh_w3d.common.utils.animation_import import create_animation
        from io_mesh_w3d.common.utils.animation_export import retrieve_animation
        hierarchy = get_hierarchy('fidelity')
        rig = create_bone_hierarchy(hierarchy, bpy.context.scene.collection)
        animation = get_animation_empty()
        channel = get_animation_channel(type=1, pivot=1)
        channel.data = [3.0] * 5
        animation.channels = [channel]
        create_animation(self, rig, animation, hierarchy)
        actual = retrieve_animation(self, 'move', hierarchy, rig, False)
        self.assertEqual(1, len(actual.channels))
        self.assertEqual(1, actual.channels[0].type)
        self.assertEqual([3.0] * 5, actual.channels[0].data)

    def test_w3d_root_weighted_skin_survives_export_and_deforms(self):
        from io_mesh_w3d.common.utils.mesh_import import rig_mesh
        self.set_format('W3D')
        hierarchy = get_hierarchy('fidelity')
        hierarchy.pivots[0].translation = Vector()
        hierarchy.pivots[0].rotation = Quaternion()
        source = get_mesh('root_skin', skin=True)
        for influence in source.vert_infs:
            influence.bone_idx = 0
            influence.bone_inf = 1.0
            influence.xtra_inf = 0.0
        create_mesh(self, source, bpy.context.scene.collection)
        rig = create_bone_hierarchy(hierarchy, bpy.context.scene.collection)
        rig_mesh(source, hierarchy, rig)
        meshes, _ = retrieve_meshes(self, hierarchy, rig, 'fidelity')
        actual = self.serialized_mesh(meshes[0])
        self.assertTrue(actual.is_skin())
        self.assertEqual([0] * len(source.verts), [influence.bone_idx for influence in actual.vert_infs])
        for before, after in zip(source.verts, actual.verts):
            self.assertLess((before - after).length, 0.0001)
        obj = bpy.data.objects['root_skin']
        rig.pose.bones['ROOTTRANSFORM'].location.x = 2.0
        bpy.context.view_layer.update()
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        for before, after in zip(source.verts, evaluated.data.vertices):
            self.assertAlmostEqual(before.x + 2.0, after.co.x, places=4)

    def test_w3d_mesh_mode_retains_renegade_override(self):
        from io_mesh_w3d.export_utils import retrieve_data
        bpy.context.scene.w3d_scene_settings.use_renegade_workflow = True
        bpy.ops.mesh.primitive_cube_add()
        self.filepath = self.outpath('model.w3d')
        settings = {'mode': 'M'}
        actual = retrieve_data(self, settings)
        self.assertIsNotNone(actual)
        self.assertEqual('HM', settings['mode'])
        self.assertIsNotNone(actual.hierarchy)
        self.assertIsNotNone(actual.hlod)
        self.assertTrue(actual.options['renegade_workflow'])

    def test_shader_edge_fade_keeps_integer_and_fractional_values(self):
        for format in ('W3X', 'W3D'):
            for property_type, value in ((6, 3), (2, 1.75)):
                with self.subTest(format=format, property_type=property_type):
                    bpy.ops.wm.read_homefile(use_empty=True)
                    self.set_format(format)
                    source = get_mesh('edge_fade', shader_mats=True)
                    source.shader_materials[0].properties = [
                        ShaderMaterialProperty(type=property_type, name='EdgeFadeOut', value=value)]
                    create_mesh(self, source, bpy.context.scene.collection)
                    meshes, _ = retrieve_meshes(self, None, None, 'fidelity')
                    actual = self.serialized_mesh(meshes[0])
                    constant = next(
                        prop for prop in actual.shader_materials[0].properties if prop.name == 'EdgeFadeOut')
                    self.assertEqual(property_type, constant.type)
                    self.assertEqual(value, constant.value)

    def test_skin_import_with_existing_object_name_uses_new_mesh_data(self):
        existing = bpy.data.objects.new('soldier', None)
        bpy.context.scene.collection.objects.link(existing)
        source = get_mesh('soldier', skin=True)
        hierarchy = get_hierarchy()
        hlod = get_hlod(attachments=False)
        create_data(self, [source], hlod, hierarchy)
        actual = bpy.data.objects['soldier.001']
        self.assertEqual('soldier', actual.data.name)
        self.assertEqual('soldier', source.name())
        self.assertEqual('ARMATURE', actual.modifiers[0].type)
        self.assertGreater(len(actual.vertex_groups), 0)

    def test_color_bytes_do_not_darken_on_repeated_roundtrips(self):
        from io_mesh_w3d.common.structs.rgba import RGBA
        for value in range(256):
            expected = RGBA(r=value, g=255-value, b=value, a=value)
            actual = expected
            for generation in range(3):
                root = create_root()
                actual.create(root)
                actual = RGBA.parse(root.find('C'))
                stream = io.BytesIO()
                actual.write_f(stream)
                stream.seek(0)
                actual = RGBA.read_f(stream)
                self.assertEqual(expected, actual)

    def test_bone_attachments_use_pivot_origin_independent_of_bone_length(self):
        from tests.common.helpers.collision_box import get_collision_box
        from tests.common.helpers.hlod import get_hlod_sub_object
        from io_mesh_w3d.common.utils.box_import import create_box, rig_box
        from io_mesh_w3d.common.utils.helpers import rig_object
        hierarchy = get_hierarchy('fidelity')
        rig = create_bone_hierarchy(hierarchy, bpy.context.scene.collection)
        sub_object = get_hlod_sub_object(bone=1)
        local_position = Vector((2, 3, 4))
        attachment = bpy.data.objects.new('attachment', None)
        bpy.context.scene.collection.objects.link(attachment)
        attachment.location = local_position
        rig_object(attachment, hierarchy, rig, sub_object)
        box = get_collision_box()
        box.center = local_position
        create_box(box, bpy.context.scene.collection)
        rig_box(box, hierarchy, rig, sub_object)
        bpy.context.view_layer.update()
        expected = rig.matrix_world @ rig.data.bones[hierarchy.pivots[1].name].matrix_local @ local_position
        for obj in (attachment, bpy.data.objects[box.name()]):
            self.assertLess((obj.matrix_world.translation - expected).length, 0.0001)
            self.assertLess((obj.location - local_position).length, 0.0001)
