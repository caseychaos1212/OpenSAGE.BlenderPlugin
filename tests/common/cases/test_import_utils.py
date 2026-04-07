# <pep8 compliant>
# Written by Stephan Vedder and Michael Schnabel

import bpy
import io
from types import SimpleNamespace
from mathutils import Vector
from io_mesh_w3d.common.utils.animation_compat import iter_id_action_fcurves
from io_mesh_w3d.import_logging import build_import_log_lines
from io_mesh_w3d.import_utils import create_data
from tests.common.helpers.hierarchy import *
from tests.common.helpers.hlod import *
from tests.common.helpers.mesh import *
from tests.utils import *


class TestImportUtils(TestCase):
    def test_read_chunk_array(self):
        output = io.BytesIO()

        mat_pass = get_material_pass()
        mat_pass.write(output)
        mat_pass.write(output)
        mat_pass.write(output)

        write_chunk_head(0x00, output, 9, has_sub_chunks=False)
        write_ubyte(0x00, output)

        io_stream = io.BytesIO(output.getvalue())
        read_chunk_array(self, io_stream, mat_pass.size()
                         * 3 + 9, W3D_CHUNK_MATERIAL_PASS, MaterialPass.read)

    def test_bone_visibility_channel_creation(self):
        armature = bpy.data.armatures.new('armature')
        rig = bpy.data.objects.new('rig', armature)
        bpy.context.scene.collection.objects.link(rig)
        bpy.context.view_layer.objects.active = rig
        rig.select_set(True)

        if rig.mode != 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')

        bone = armature.edit_bones.new('bone')
        bone.head = Vector((0.0, 0.0, 0.0))
        bone.tail = Vector((0.0, 1.0, 0.0))

        if rig.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        self.assertTrue('bone' in armature.bones)
        self.assertTrue('bone' in rig.data.bones)

        bone = rig.data.bones['bone']
        bone.hide = True
        bone.keyframe_insert(data_path='hide', frame=0)

        results = [fcu for fcu in armature.animation_data.action.fcurves if 'hide' in fcu.data_path]
        self.assertEqual(1, len(results))

    def test_create_data_returns_import_summary(self):
        hierarchy = get_hierarchy()
        hlod = get_hlod()
        hlod.lod_arrays[0].sub_objects = [get_hlod_sub_object(bone=0, name='containerName.meshName')]
        hlod.lod_arrays[0].header.model_count = 1

        summary = create_data(self, [get_mesh(name='meshName')], hlod, hierarchy)

        self.assertEqual('containerName', summary['collection_name'])
        self.assertEqual(hierarchy.name(), summary['hierarchy_name'])
        self.assertEqual(hierarchy.name(), summary['rig_name'])
        self.assertIn('meshName', summary['object_names'])

    def test_create_data_imports_aggregate_and_proxy_placeholders(self):
        hierarchy = get_hierarchy()
        aggregate_sub_object = HLodSubObject(bone_index=7, identifier='tree_a', name='tree_a')
        proxy_sub_object = HLodSubObject(bone_index=1, identifier='proxy_pad$1.5', name='proxy_pad$1.5')
        hlod = HLod(
            header=get_hlod_header('containerName', hierarchy.name()),
            lod_arrays=[HLodLodArray(header=get_hlod_array_header(), sub_objects=[])],
            aggregate_array=HLodAggregateArray(
                header=get_hlod_array_header(count=1, size=0.0),
                sub_objects=[aggregate_sub_object]),
            proxy_array=HLodProxyArray(
                header=get_hlod_array_header(count=1, size=0.0),
                sub_objects=[proxy_sub_object]))

        summary = create_data(self, [], hlod, hierarchy)

        aggregate = bpy.data.objects['tree_a']
        proxy = bpy.data.objects['proxy_pad$1.5']

        self.assertEqual('EMPTY', aggregate.type)
        self.assertEqual('EMPTY', proxy.type)
        self.assertEqual('AGGREGATE', aggregate.w3d_object_settings.hlod_role)
        self.assertEqual('tree_a', aggregate.w3d_object_settings.hlod_identifier)
        self.assertEqual('PROXY', proxy.w3d_object_settings.hlod_role)
        self.assertEqual('proxy_pad$1.5', proxy.w3d_object_settings.hlod_identifier)
        self.assertEqual('sword_bone', aggregate.parent_bone)
        self.assertEqual('b_waist', proxy.parent_bone)
        self.assertIn('tree_a', summary['object_names'])
        self.assertIn('proxy_pad$1.5', summary['object_names'])

    def test_import_log_infers_objects_from_messages(self):
        operator = SimpleNamespace(
            filepath='C:\\tmp\\asset.w3d',
            file_format='W3D',
            _w3d_import_state={'rig_name': 'rig'},
            _w3d_loaded_files=['C:\\tmp\\asset.w3d'],
            _w3d_log_buffer=["INFO: creating mesh 'meshName'"])

        lines = build_import_log_lines(operator, bpy.context)

        self.assertIn('CaptureSource: -', lines)
        self.assertIn('Objects: 2', lines)
        self.assertTrue(any(line == 'ObjectNames: meshName, rig' for line in lines))

    def test_iter_id_action_fcurves_falls_back_to_all_layered_curves(self):
        curve = SimpleNamespace(data_path='pose.bones["F_CM_PIST"].location', array_index=0, keyframe_points=[])
        missing_slot = SimpleNamespace(identifier='missing-slot', handle=1)
        actual_slot = SimpleNamespace(identifier='actual-slot', handle=2)
        channelbag = SimpleNamespace(slot=actual_slot, slot_handle=2, fcurves=[curve])
        strip = SimpleNamespace(channelbags=[channelbag])
        layer = SimpleNamespace(strips=[strip])
        action = SimpleNamespace(fcurves=[], layers=[layer])
        id_block = SimpleNamespace(animation_data=SimpleNamespace(action=action, action_slot=missing_slot))

        curves = iter_id_action_fcurves(id_block)

        self.assertEqual([curve], curves)
