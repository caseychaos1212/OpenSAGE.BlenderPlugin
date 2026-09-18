# <pep8 compliant>

import os
from unittest.mock import patch

import bpy
from tests.utils import TestCase
from io_mesh_w3d.common.structs.mesh import Mesh
from io_mesh_w3d.export_utils import save_data
from io_mesh_w3d.export_status import ExportStatus
from io_mesh_w3d.utils import ReportHelper
import io_mesh_w3d.export_status as status_module


class TestExportStatus(TestCase):
    def scene(self):
        bpy.ops.mesh.primitive_cube_add()
        obj = bpy.context.object
        obj.name = 'Terrain'
        obj.data.uv_layers.new() if not obj.data.uv_layers else None
        material = bpy.data.materials.new('Terrain material')
        material.w3d_material_settings.passes.add()
        obj.data.materials.append(material)
        self.filepath = os.path.join(self.outpath(), 'progress.w3d')
        return obj

    def test_elapsed_and_completion_freeze_without_claiming_success_on_failure(self):
        now = [10.0]
        status = ExportStatus('map.w3d', clock=lambda: now[0])
        now[0] = 14.0
        status.update('Building collision tree', object_name='Terrain', current=20, total=100)
        self.assertEqual(4.0, status.elapsed)
        status.record('WARNING', 'Missing UVs')
        status.record('ERROR', 'Could not write file')
        status.finish('FAILED', 'Disk full')
        now[0] = 30.0
        status.update('Writing files', current=100)
        self.assertEqual(4.0, status.elapsed)
        self.assertEqual('Export stopped', status.phase)
        self.assertEqual('Disk full', status.detail)
        self.assertEqual(20, status.current)
        self.assertEqual((1, 1), (status.warnings, status.errors))

    def test_warning_history_is_bounded_but_counts_all_reports(self):
        status = ExportStatus('map.w3d')
        helper = ReportHelper()
        helper._w3d_export_status = status
        helper._w3d_log_buffer = []
        for index in range(20):
            helper._append_log('WARNING', f'Warning {index}')
        self.assertEqual(20, status.warnings)
        self.assertEqual(5, len(status.messages))
        self.assertEqual('Warning 19', status.messages[-1][1])
        self.assertEqual(20, len(helper._w3d_log_buffer))

    def test_mesh_export_reports_real_work_stages_without_changing_output(self):
        self.scene()
        stages = []
        status = ExportStatus(self.filepath)
        original = status.update
        def capture(phase=None, **values):
            original(phase, **values)
            stages.append((status.phase, status.object_name, status.current, status.total))
        status.update = capture
        self._w3d_export_status = status
        options = {'mode': 'M', 'compression': 'TC', 'use_existing_skeleton': False}
        self.assertEqual({'FINISHED'}, save_data(self, options))
        self._w3d_export_status = None
        with open(self.filepath, 'rb') as stream:
            with_status = stream.read()
        self.assertEqual({'FINISHED'}, save_data(self, options))
        with open(self.filepath, 'rb') as stream:
            self.assertEqual(with_status, stream.read())
        names = {phase for phase, _, _, _ in stages}
        self.assertTrue({'Evaluating mesh and modifiers', 'Triangulating mesh',
                         'Transforming vertices and normals', 'Building triangles',
                         'Exporting materials and textures', 'Building collision tree',
                         'Writing mesh data'}.issubset(names))
        self.assertTrue(any(name == 'Terrain' and total > 0 for _, name, _, total in stages))

    def test_background_operator_finishes_without_opening_a_window(self):
        self.scene()
        with patch.object(bpy.ops.screen, 'area_dupli') as duplicate:
            result = bpy.ops.export_mesh.westwood_w3d(filepath=self.filepath, export_mode='M',
                                                       show_export_status=True)
        self.assertEqual({'FINISHED'}, result)
        duplicate.assert_not_called()
        self.assertEqual('FINISHED', status_module._last_status.result)
        self.assertIsNone(status_module._last_status.handler)

    def test_write_exception_stops_status_and_closes_output(self):
        self.scene()
        with patch.object(Mesh, 'write', side_effect=OSError('Test disk error')):
            with self.assertRaises(RuntimeError):
                bpy.ops.export_mesh.westwood_w3d(filepath=self.filepath, export_mode='M',
                                                show_export_status=False)
        status = status_module._last_status
        self.assertEqual('FAILED', status.result)
        self.assertIn('Test disk error', status.detail)
        self.assertEqual(1, status.errors)
        os.rename(self.filepath, self.filepath + '.closed')

    def test_validation_failure_does_not_show_export_complete(self):
        self.scene()
        with patch('io_mesh_w3d.save_data', return_value={'CANCELLED'}):
            result = bpy.ops.export_mesh.westwood_w3d(filepath=self.filepath, export_mode='M',
                                                    show_export_status=False)
        self.assertEqual({'CANCELLED'}, result)
        self.assertEqual('FAILED', status_module._last_status.result)
        self.assertFalse(os.path.exists(self.filepath))
