# <pep8 compliant>

from math import radians

import bpy
from mathutils import Quaternion, Vector

from tests.utils import TestCase
from io_mesh_w3d.common.structs.hierarchy import Hierarchy, HierarchyHeader, HierarchyPivot
from io_mesh_w3d.common.utils.bone_display import SHAPE_TAG, apply_game_bone_shapes
from io_mesh_w3d.common.utils.hierarchy_import import create_bone_hierarchy, pivot_world_matrix
from io_mesh_w3d.common.utils.hierarchy_export import retrieve_hierarchy
from io_mesh_w3d.common.utils.mesh_export import retrieve_meshes


class TestGameBoneDisplay(TestCase):
    def hierarchy(self, rotated=False):
        names = ['ROOTTRANSFORM', 'TURRET', 'BARREL', 'MUZZLEA0',
                 'WheelP00', 'WheelC00', 'WheelF00', 'WheelT00', 'ordinary']
        pivots = []
        for index, name in enumerate(names):
            pivot = HierarchyPivot(name=name, parent_id=-1 if index == 0 else index - 1)
            if rotated:
                pivot.translation = Vector((index * 0.1, 0.4, -0.2))
                pivot.rotation = Quaternion(Vector((1, 2, 3)).normalized(), radians(17 + index))
            pivots.append(pivot)
        return Hierarchy(header=HierarchyHeader(name='vehicle', num_pivots=len(pivots)), pivots=pivots)

    def create_rig(self, rotated=False):
        hierarchy = self.hierarchy(rotated)
        rig = create_bone_hierarchy(hierarchy, bpy.context.collection)
        bpy.context.view_layer.update()
        return hierarchy, rig

    def assert_matrix(self, expected, actual):
        for first, second in zip(expected, actual):
            for a, b in zip(first, second):
                self.assertAlmostEqual(a, b, places=5)

    def test_display_arrows_follow_engine_axes_even_on_rotated_parents(self):
        hierarchy, rig = self.create_rig(rotated=True)
        expected_directions = {
            'TURRET': (1, 0, 0), 'BARREL': (1, 0, 0), 'MUZZLEA0': (1, 0, 0),
            'WheelP00': (0, 0, -1), 'WheelC00': (0, 0, 1),
            'WheelF00': (0, 1, 0), 'WheelT00': (0, 0, 1),
        }
        for index, pivot in enumerate(hierarchy.pivots):
            bone = rig.pose.bones[pivot.name]
            world = rig.matrix_world @ bone.matrix
            expected = pivot_world_matrix(hierarchy, index)
            self.assert_matrix(expected, world)
            if pivot.name not in expected_directions:
                self.assertIsNone(bone.custom_shape)
                continue
            # Vertex 1 is the arrow tip and vertex 0 marks the pivot.
            shape = bone.custom_shape.data
            displayed = world.to_3x3() @ (shape.vertices[1].co - shape.vertices[0].co)
            direction = expected.to_3x3() @ Vector(expected_directions[pivot.name])
            self.assertLess((displayed.normalized() - direction.normalized()).length, 1e-5)

    def test_shapes_do_not_add_scene_geometry_or_change_exported_pivots(self):
        source, rig = self.create_rig(rotated=True)
        self.assertEqual([rig], list(bpy.context.scene.objects))
        for obj in bpy.data.objects:
            if SHAPE_TAG in obj:
                self.assertEqual(0, len(obj.users_collection))
        meshes, textures = retrieve_meshes(self, source, rig, 'vehicle')
        self.assertEqual([], meshes)
        actual, _ = retrieve_hierarchy(self, 'vehicle')
        self.assertEqual(len(source.pivots), len(actual.pivots))
        for index in range(len(source.pivots)):
            self.assert_matrix(pivot_world_matrix(source, index), pivot_world_matrix(actual, index))

    def test_toggle_preserves_animation_and_pose_transforms(self):
        _, rig = self.create_rig()
        bone = rig.pose.bones['MUZZLEA0']
        bone.rotation_mode = 'QUATERNION'
        for frame, angle in ((1, 0), (10, radians(35))):
            bone.rotation_quaternion = Quaternion((0, 1, 0), angle)
            bone.location = (-frame * 0.1, 0, 0)
            bone.keyframe_insert('rotation_quaternion', frame=frame)
            bone.keyframe_insert('location', frame=frame)
        expected = {}
        for frame in (1, 5, 10):
            bpy.context.scene.frame_set(frame)
            expected[frame] = bone.matrix.copy()
        for enabled in (False, True):
            rig.w3d_object_settings.show_game_bone_directions = enabled
            self.assertEqual(enabled, bone.custom_shape is not None)
            for frame in (1, 5, 10):
                bpy.context.scene.frame_set(frame)
                self.assert_matrix(expected[frame], bone.matrix)

    def test_shapes_survive_saving_and_reopening_blend(self):
        _, rig = self.create_rig()
        filepath = self.outpath('directions.blend')
        bpy.ops.wm.save_as_mainfile(filepath=filepath)
        bpy.ops.wm.open_mainfile(filepath=filepath)
        rig = bpy.data.objects['vehicle']
        self.assertTrue(rig.w3d_object_settings.show_game_bone_directions)
        bone = rig.pose.bones['MUZZLEA0']
        self.assertEqual('MUZZLE', bone.custom_shape[SHAPE_TAG])
        self.assertEqual((1.0, 0.0, 0.0), tuple(bone.custom_shape.data.vertices[1].co))
        self.assertEqual([rig], list(bpy.context.scene.objects))

    def test_existing_custom_shapes_are_preserved(self):
        _, rig = self.create_rig()
        artist_shape = bpy.data.objects.new('Artist control', bpy.data.meshes.new('Artist control'))
        bone = rig.pose.bones['MUZZLEA0']
        bone.custom_shape = artist_shape
        for enabled in (False, True):
            rig.w3d_object_settings.show_game_bone_directions = enabled
            self.assertEqual(artist_shape, bone.custom_shape)

    def test_enabling_on_existing_rig_and_refreshing_after_rename(self):
        _, rig = self.create_rig()
        rig.w3d_object_settings.show_game_bone_directions = False
        self.assertTrue(all(bone.custom_shape is None for bone in rig.pose.bones))
        rig.pose.bones['MUZZLEA0'].name = 'muzzlea1'
        rig.w3d_object_settings.show_game_bone_directions = True
        self.assertEqual('MUZZLE', rig.pose.bones['muzzlea1'].custom_shape[SHAPE_TAG])
        old_shapes = {obj.as_pointer() for obj in bpy.data.objects if SHAPE_TAG in obj}
        apply_game_bone_shapes(rig)
        self.assertEqual(old_shapes, {obj.as_pointer() for obj in bpy.data.objects if SHAPE_TAG in obj})
        rig.pose.bones['muzzlea1'].name = 'ordinary2'
        apply_game_bone_shapes(rig)
        self.assertIsNone(rig.pose.bones['ordinary2'].custom_shape)
