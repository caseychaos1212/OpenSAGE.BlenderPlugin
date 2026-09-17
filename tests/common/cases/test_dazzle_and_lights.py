# <pep8 compliant>

import io
import struct
from unittest.mock import patch

import bpy

from tests.utils import TestCase
from tests.common.helpers.hierarchy import get_hierarchy
from io_mesh_w3d.custom_properties import get_dazzle_enum_items
from io_mesh_w3d.common.structs.hlod import (
    HLod, HLodHeader, HLodLodArray, HLodLightArray, HLodArrayHeader, HLodSubObject,
)
from io_mesh_w3d.common.utils.hlod_export import create_hlod
from io_mesh_w3d.common.utils.object_settings_bridge import get_dazzle_type
from io_mesh_w3d.export_utils import retrieve_data
from io_mesh_w3d.import_utils import create_data
from io_mesh_w3d.w3d.io_binary import read_chunk_head
from io_mesh_w3d.w3d.structs.dazzle import Dazzle
from io_mesh_w3d.w3d.utils.dazzle_import import create_dazzle
from io_mesh_w3d.w3d.utils.dazzle_export import retrieve_dazzles


class TestDazzleAndLights(TestCase):
    def setUp(self):
        super().setUp()
        self.preferences = bpy.context.preferences.addons['io_mesh_w3d'].preferences
        self.old_ini = self.preferences.dazzle_ini_path
        self.preferences.dazzle_ini_path = ''

    def tearDown(self):
        self.preferences.dazzle_ini_path = self.old_ini
        super().tearDown()

    def import_dazzle(self, type_name='REN_HEADLIGHT_SMALL'):
        with patch('io_mesh_w3d.w3d.utils.dazzle_import.find_texture', return_value=None):
            create_dazzle(self, Dazzle(name_='tank.Headlight', type_name=type_name), bpy.context.collection)
        return bpy.data.objects['Headlight']

    def test_unknown_dazzle_import_and_export_preserves_exact_name(self):
        obj = self.import_dazzle()
        self.assertEqual('DAZZLE', obj.data.object_type)
        self.assertEqual('DAZZLE', obj.w3d_object_settings.geometry_type)
        self.assertEqual('CUSTOM', obj.data.dazzle_type)
        self.assertEqual('CUSTOM', obj.w3d_object_settings.dazzle_name)
        self.assertEqual('REN_HEADLIGHT_SMALL', obj.w3d_object_settings.dazzle_name_custom)
        self.assertEqual('REN_HEADLIGHT_SMALL', retrieve_dazzles('tank')[0].type_name)

    def test_custom_dazzle_survives_blend_save_and_reload(self):
        self.import_dazzle()
        filepath = self.outpath('dazzle.blend')
        bpy.ops.wm.save_as_mainfile(filepath=filepath)
        bpy.ops.wm.open_mainfile(filepath=filepath)
        self.assertEqual('REN_HEADLIGHT_SMALL', retrieve_dazzles('tank')[0].type_name)

    def test_known_and_legacy_dazzle_types_remain_exportable(self):
        obj = self.import_dazzle('REN_BRAKELIGHT')
        self.assertEqual('REN_BRAKELIGHT', obj.data.dazzle_type)
        self.assertEqual('REN_BRAKELIGHT', obj.w3d_object_settings.dazzle_name)
        self.assertEqual('REN_BRAKELIGHT', get_dazzle_type(obj))
        obj.w3d_object_settings.property_unset('dazzle_name')
        obj.data.dazzle_type = 'REN_HEADLIGHT'
        self.assertEqual('REN_HEADLIGHT', retrieve_dazzles('tank')[0].type_name)

    def test_dazzle_ini_preference_loads_game_names_and_preserves_selections(self):
        ini = self.outpath('dazzle.ini')
        with open(ini, 'w') as stream:
            stream.write('[Dazzles_List]\n0=REN_HEADLIGHT_SMALL\n1=APB_BEACON\n')
        obj = self.import_dazzle('REN_BRAKELIGHT')
        settings = obj.w3d_object_settings
        self.preferences.dazzle_ini_path = ini
        items = {item[0]: item for item in get_dazzle_enum_items(settings, bpy.context)}
        self.assertIn('REN_HEADLIGHT_SMALL', items)
        self.assertIn('APB_BEACON', items)
        self.assertEqual('REN_BRAKELIGHT', get_dazzle_type(obj))
        settings.dazzle_name = 'APB_BEACON'
        self.assertEqual('APB_BEACON', settings.dazzle_name_custom)
        self.preferences.dazzle_ini_path = ''
        self.assertEqual('APB_BEACON', get_dazzle_type(obj))
        filepath = self.outpath('configured.blend')
        bpy.ops.wm.save_as_mainfile(filepath=filepath)
        bpy.ops.wm.open_mainfile(filepath=filepath)
        self.assertEqual('APB_BEACON', retrieve_dazzles('tank')[0].type_name)

    def test_custom_name_and_enum_survive_loading_an_ini(self):
        obj = self.import_dazzle()
        ini = self.outpath('dazzle.ini')
        with open(ini, 'w') as stream:
            stream.write('[Dazzles_List]\n0=REN_HEADLIGHT_SMALL\n')
        self.preferences.dazzle_ini_path = ini
        self.assertEqual('CUSTOM', obj.w3d_object_settings.dazzle_name)
        self.assertEqual('REN_HEADLIGHT_SMALL', get_dazzle_type(obj))
        obj.w3d_object_settings.dazzle_name_custom = 'MOD_CUSTOM_DAZZLE'
        self.assertEqual('MOD_CUSTOM_DAZZLE', retrieve_dazzles('tank')[0].type_name)

    def test_light_array_reads_max_layout_without_unknown_chunk_warnings(self):
        # Independently encode the documented Max 0x707 container.
        payload = struct.pack('<IIIf', 0x703, 8, 1, 0.0)
        payload += struct.pack('<III32s', 0x704, 36, 3, b'tank.Headlight')
        stream = io.BytesIO(struct.pack('<II', 0x707, len(payload) | 0x80000000) + payload)
        with patch.object(self, 'warning') as warning:
            hlod = HLod.read(self, stream, len(stream.getvalue()))
        warning.assert_not_called()
        self.assertEqual(1, hlod.light_array.header.model_count)
        light = hlod.light_array.sub_objects[0]
        self.assertEqual(3, light.bone_index)
        self.assertEqual('tank.Headlight', light.identifier)
        output = io.BytesIO()
        hlod.light_array.write(output)
        self.assertEqual(stream.getvalue(), output.getvalue())
        self.assertEqual(hlod.light_array.size(), len(output.getvalue()))

    def light_hlod(self, hierarchy):
        return HLod(
            header=HLodHeader(model_name='tank', hierarchy_name=hierarchy.name()),
            lod_arrays=[HLodLodArray(header=HLodArrayHeader())],
            light_array=HLodLightArray(header=HLodArrayHeader(model_count=1, max_screen_size=0.0),
                                      sub_objects=[HLodSubObject(bone_index=1, identifier='tank.Headlight')]))

    def test_light_reference_import_export_keeps_identifier_and_parent_bone(self):
        hierarchy = get_hierarchy()
        source = self.light_hlod(hierarchy)
        create_data(self, [], source, hierarchy)
        obj = bpy.data.objects['tank.Headlight']
        self.assertEqual('EMPTY', obj.type)
        self.assertEqual('LIGHT', obj.w3d_object_settings.hlod_role)
        self.assertEqual(hierarchy.pivots[1].name, obj.parent_bone)
        obj.w3d_object_settings.export_geometry = False
        actual = create_hlod(hierarchy, 'tank')
        self.assertEqual(0, actual.lod_arrays[0].header.model_count)
        self.assertEqual(1, actual.light_array.header.model_count)
        self.assertEqual(1, actual.light_array.sub_objects[0].bone_index)
        self.assertEqual('tank.Headlight', actual.light_array.sub_objects[0].identifier)
        stream = io.BytesIO()
        actual.write(stream)
        self.assertEqual(actual.size(), stream.tell())
        stream.seek(0)
        _, _, end = read_chunk_head(stream)
        result = HLod.read(self, stream, end)
        self.assertEqual('tank.Headlight', result.light_array.sub_objects[0].identifier)
        obj.w3d_object_settings.export_object = False
        self.assertIsNone(create_hlod(hierarchy, 'tank').light_array)

    def test_light_only_scene_exports_without_meshes(self):
        hierarchy = get_hierarchy()
        create_data(self, [], self.light_hlod(hierarchy), hierarchy)
        self.filepath = self.outpath('tank.w3d')
        result = retrieve_data(self, {'mode': 'HM'})
        self.assertIsNotNone(result)
        self.assertEqual([], result.meshes)
        self.assertEqual('tank.Headlight', result.hlod.light_array.sub_objects[0].identifier)
