# <pep8 compliant>
# Written by Stephan Vedder and Michael Schnabel

def iter_action_fcurves(action):
    """Return fcurves for both legacy and layered action APIs."""
    if action is None:
        return []

    fcurves = getattr(action, 'fcurves', None)
    if fcurves is not None:
        return fcurves

    curves = []
    layers = getattr(action, 'layers', None)
    if layers is None:
        return curves

    for layer in layers:
        strips = getattr(layer, 'strips', None)
        if strips is None:
            continue
        for strip in strips:
            curves.extend(_collect_strip_fcurves(strip))
    return curves


def _collect_strip_fcurves(strip):
    curves = []
    if strip is None:
        return curves

    channelbag = getattr(strip, 'channelbag', None)
    if channelbag is not None:
        return _collect_container_fcurves(channelbag)

    channelbags = getattr(strip, 'channelbags', None)
    if channelbags is not None:
        try:
            for bag in channelbags:
                curves.extend(_collect_container_fcurves(bag))
        except TypeError:
            curves.extend(_collect_container_fcurves(channelbags))
        return curves

    channels = getattr(strip, 'channels', None)
    if channels is not None:
        curves.extend(_collect_container_fcurves(channels))
    return curves


def _collect_container_fcurves(container):
    curves = []
    if container is None:
        return curves

    fcurves = getattr(container, 'fcurves', None)
    if fcurves is not None:
        try:
            curves.extend(list(fcurves))
        except TypeError:
            pass
        return curves

    channels = getattr(container, 'channels', None)
    if channels is not None:
        _collect_from_channels(curves, channels)
        return curves

    _append_channel(curves, container)
    return curves


def _collect_from_channels(curves, channels):
    try:
        for channel in channels:
            _append_channel(curves, channel)
    except TypeError:
        _append_channel(curves, channels)


def _append_channel(curves, channel):
    if channel is None:
        return

    if hasattr(channel, 'data_path') and hasattr(channel, 'keyframe_points'):
        curves.append(channel)
        return

    fcurves = getattr(channel, 'fcurves', None)
    if fcurves is not None:
        try:
            curves.extend(list(fcurves))
        except TypeError:
            pass
        return

    fcurve = getattr(channel, 'fcurve', None)
    if fcurve is not None:
        curves.append(fcurve)
