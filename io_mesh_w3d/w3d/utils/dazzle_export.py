# <pep8 compliant>
# Written by Stephan Vedder and Michael Schnabel

from io_mesh_w3d.common.utils.helpers import *
from io_mesh_w3d.w3d.structs.dazzle import *
from io_mesh_w3d.common.utils.object_settings_bridge import get_object_settings


def retrieve_dazzles(container_name):
    dazzles = []

    for mesh_object in get_objects('MESH'):
        if mesh_object.data.object_type != 'DAZZLE':
            continue
        name = container_name + '.' + mesh_object.name
        settings = get_object_settings(mesh_object)
        type_name = mesh_object.data.dazzle_type
        if settings is not None:
            type_name = settings.dazzle_name
        dazzle = Dazzle(
            name_=name,
            type_name=type_name)

        dazzles.append(dazzle)
    return dazzles
