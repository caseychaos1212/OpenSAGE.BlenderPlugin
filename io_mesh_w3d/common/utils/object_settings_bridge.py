# <pep8 compliant>
# Helper utilities to translate between Blender W3D object settings
# and the legacy exporter/importer data structures.

from io_mesh_w3d.common.structs.mesh import (
    GEOMETRY_TYPE_HIDDEN,
    GEOMETRY_TYPE_TWO_SIDED,
    GEOMETRY_TYPE_CAST_SHADOW,
    GEOMETRY_TYPE_CAMERA_ORIENTED,
    GEOMETRY_TYPE_CAMERA_ALIGNED,
    GEOMETRY_COLLISION_TYPE_MASK,
    GEOMETRY_COLLISION_TYPE_PHYSICAL,
    GEOMETRY_COLLISION_TYPE_PROJECTILE,
    GEOMETRY_COLLISION_TYPE_VIS,
    GEOMETRY_COLLISION_TYPE_CAMERA,
    GEOMETRY_COLLISION_TYPE_VEHICLE,
)


GEOMETRY_ATTR_MAP = {
    'CAM_ORIENT': GEOMETRY_TYPE_CAMERA_ORIENTED,
    'CAM_PARAL': GEOMETRY_TYPE_CAMERA_ALIGNED,
    'CAM_Z_ORIENT': GEOMETRY_TYPE_CAMERA_ORIENTED,
}


def get_object_settings(obj):
    return getattr(obj, 'w3d_object_settings', None)


def should_export_geometry(obj):
    settings = get_object_settings(obj)
    if settings is None:
        return True
    return settings.export_geometry


def should_export_transform(obj):
    settings = get_object_settings(obj)
    if settings is None:
        return True
    return settings.export_transform


def is_normal_geometry(obj):
    settings = get_object_settings(obj)
    if settings is None:
        return False
    return settings.geometry_type == 'NORMAL'


def apply_object_settings_to_header(obj, header):
    """Apply geometry flags stored on the object to the mesh header."""
    settings = get_object_settings(obj)
    result = {'handled_orientation': False}
    if settings is None:
        if obj.hide_get():
            header.attrs |= GEOMETRY_TYPE_HIDDEN
        if getattr(obj.data, 'casts_shadow', False):
            header.attrs |= GEOMETRY_TYPE_CAST_SHADOW
        if getattr(obj.data, 'two_sided', False):
            header.attrs |= GEOMETRY_TYPE_TWO_SIDED
        header.sort_level = getattr(obj.data, 'sort_level', header.sort_level)
        return result

    header.sort_level = settings.static_sort_level

    if settings.geom_hide:
        header.attrs |= GEOMETRY_TYPE_HIDDEN
    if settings.geom_shadow:
        header.attrs |= GEOMETRY_TYPE_CAST_SHADOW
    if settings.geom_two_sided:
        header.attrs |= GEOMETRY_TYPE_TWO_SIDED

    geo_attr = GEOMETRY_ATTR_MAP.get(settings.geometry_type)
    if geo_attr is not None:
        header.attrs |= geo_attr
        result['handled_orientation'] = True

    collision_bits = 0
    if settings.coll_physical:
        collision_bits |= GEOMETRY_COLLISION_TYPE_PHYSICAL
    if settings.coll_projectile:
        collision_bits |= GEOMETRY_COLLISION_TYPE_PROJECTILE
    if settings.coll_vis:
        collision_bits |= GEOMETRY_COLLISION_TYPE_VIS
    if settings.coll_camera:
        collision_bits |= GEOMETRY_COLLISION_TYPE_CAMERA
    if settings.coll_vehicle:
        collision_bits |= GEOMETRY_COLLISION_TYPE_VEHICLE

    header.attrs &= ~GEOMETRY_COLLISION_TYPE_MASK
    header.attrs |= collision_bits

    return result


def get_screen_size(obj, default_value):
    settings = get_object_settings(obj)
    if settings is None or settings.screen_size <= 0.0:
        return default_value
    return settings.screen_size


def populate_object_settings_from_mesh(obj, mesh_struct):
    settings = get_object_settings(obj)
    if settings is None:
        return

    settings.export_geometry = True
    settings.export_transform = True
    settings.static_sort_level = mesh_struct.header.sort_level
    settings.geom_two_sided = mesh_struct.two_sided()
    settings.geom_shadow = mesh_struct.casts_shadow()
    settings.geom_hide = mesh_struct.is_hidden()

    if mesh_struct.is_camera_oriented():
        settings.geometry_type = 'CAM_ORIENT'
    elif mesh_struct.is_camera_aligned():
        settings.geometry_type = 'CAM_PARAL'
    else:
        settings.geometry_type = 'NORMAL'

    attrs = mesh_struct.header.attrs
    settings.coll_physical = bool(attrs & GEOMETRY_COLLISION_TYPE_PHYSICAL)
    settings.coll_projectile = bool(attrs & GEOMETRY_COLLISION_TYPE_PROJECTILE)
    settings.coll_vis = bool(attrs & GEOMETRY_COLLISION_TYPE_VIS)
    settings.coll_camera = bool(attrs & GEOMETRY_COLLISION_TYPE_CAMERA)
    settings.coll_vehicle = bool(attrs & GEOMETRY_COLLISION_TYPE_VEHICLE)


def populate_object_settings_for_dazzle(obj, dazzle_type):
    settings = get_object_settings(obj)
    if settings is None:
        return
    settings.dazzle_name = dazzle_type
