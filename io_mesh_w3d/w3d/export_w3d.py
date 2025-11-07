# <pep8 compliant>
# Written by Stephan Vedder and Michael Schnabel


def save(context, export_settings, data_context):
    filepath = context.filepath
    if not filepath.lower().endswith(context.filename_ext):
        filepath += context.filename_ext

    context.info(f'Saving file: {filepath}')

    export_mode = export_settings['mode']
    options = getattr(data_context, 'options', {}) or {}
    terrain_flag = options.get('terrain_mode', False)
    effective_mode = 'HM' if terrain_flag else export_mode
    context.info(f'export mode: {export_mode}')

    file = open(filepath, 'wb')

    if terrain_flag:
        for box in data_context.collision_boxes:
            box.write(file)
        for dazzle in data_context.dazzles:
            dazzle.write(file)
        for mesh in data_context.meshes:
            mesh.header.container_name = data_context.container_name
            mesh.write(file)
        file.close()
        context.info('finished')
        return {'FINISHED'}

    if effective_mode == 'M':
        if len(data_context.meshes) > 1:
            context.warning('Scene does contain multiple meshes, exporting only the first with export mode M!')
        mesh = data_context.meshes[0]
        mesh.header.container_name = ''
        mesh.header.mesh_name = data_context.container_name
        mesh.write(file)

    elif effective_mode == 'HM' or effective_mode == 'HAM':
        if effective_mode == 'HAM' \
                or not export_settings['use_existing_skeleton']:
            data_context.hlod.header.hierarchy_name = data_context.container_name
            data_context.hierarchy.header.name = data_context.container_name
            data_context.hierarchy.write(file)

        for box in data_context.collision_boxes:
            box.write(file)

        for dazzle in data_context.dazzles:
            dazzle.write(file)

        for mesh in data_context.meshes:
            mesh.write(file)

        data_context.hlod.write(file)
        if effective_mode == 'HAM':
            data_context.animation.header.hierarchy_name = data_context.container_name
            data_context.animation.write(file)

    elif effective_mode == 'A':
        data_context.animation.write(file)

    elif effective_mode == 'H':
        data_context.hierarchy.header.name = data_context.container_name.upper()
        data_context.hierarchy.write(file)
    else:
        context.error(f'unsupported export mode \'{export_mode}\', aborting export!')
        return {'CANCELLED'}

    file.close()
    context.info('finished')
    return {'FINISHED'}
