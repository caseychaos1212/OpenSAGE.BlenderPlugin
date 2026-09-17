# <pep8 compliant>
# Written by Stephan Vedder and Michael Schnabel

from ...common.utils.helpers import *
from ...w3d.structs.dazzle import *
from ...common.utils.object_settings_bridge import (
    get_dazzle_type,
    is_hlod_attachment,
    should_export_geometry,
)


def retrieve_dazzles(container_name):
    dazzles = []

    for mesh_object in get_objects('MESH'):
        if mesh_object.data.object_type != 'DAZZLE':
            continue
        if is_hlod_attachment(mesh_object) or not should_export_geometry(mesh_object):
            continue
        name = container_name + '.' + mesh_object.name
        type_name = get_dazzle_type(mesh_object)
        dazzle = Dazzle(
            name_=name,
            type_name=type_name)

        dazzles.append(dazzle)
    return dazzles
