# <pep8 compliant>
# Written by Stephan Vedder and Michael Schnabel


def iter_animation_data_fcurves(animation_data):
    if animation_data is None:
        return []
    return iter_action_fcurves(
        getattr(animation_data, 'action', None),
        getattr(animation_data, 'action_slot', None))


def iter_id_action_fcurves(id_block):
    if id_block is None:
        return []
    animation_data = getattr(id_block, 'animation_data', None)
    curves = iter_animation_data_fcurves(animation_data)
    if curves:
        return curves
    if animation_data is None:
        return []
    return iter_any_action_fcurves(getattr(animation_data, 'action', None))


def iter_any_action_fcurves(action):
    return iter_action_fcurves(action)


def iter_action_fcurves(action, slot=None):
    """Return fcurves for both legacy and layered action APIs."""
    if action is None:
        return []

    if slot is not None:
        curves = _collect_layered_action_fcurves(action, slot)
        if curves:
            return curves

    curves = _collect_legacy_action_fcurves(action)
    if curves:
        return curves

    return _collect_layered_action_fcurves(action, slot)


def _collect_legacy_action_fcurves(action):
    fcurves = getattr(action, 'fcurves', None)
    if fcurves is None:
        return []
    try:
        return list(fcurves)
    except TypeError:
        return []


def _collect_layered_action_fcurves(action, slot=None):
    curves = []
    layers = getattr(action, 'layers', None)
    if layers is None:
        return curves

    for layer in layers:
        strips = getattr(layer, 'strips', None)
        if strips is None:
            continue
        for strip in strips:
            curves.extend(_collect_strip_fcurves(strip, slot))
    return curves


def _collect_strip_fcurves(strip, slot=None):
    curves = []
    if strip is None:
        return curves

    channelbag = getattr(strip, 'channelbag', None)
    if callable(channelbag):
        try:
            bag = channelbag(slot) if slot is not None else None
        except Exception:
            bag = None
        if bag is not None:
            return _collect_container_fcurves(bag)

    channelbags = getattr(strip, 'channelbags', None)
    if channelbags is not None:
        try:
            for bag in channelbags:
                if _channelbag_matches_slot(bag, slot):
                    curves.extend(_collect_container_fcurves(bag))
        except TypeError:
            if _channelbag_matches_slot(channelbags, slot):
                curves.extend(_collect_container_fcurves(channelbags))
        if curves:
            return curves

    channels = getattr(strip, 'channels', None)
    if channels is not None:
        curves.extend(_collect_container_fcurves(channels))
    return curves


def _channelbag_matches_slot(channelbag, slot):
    if slot is None or channelbag is None:
        return True

    bag_slot = getattr(channelbag, 'slot', None)
    if bag_slot is not None:
        if bag_slot == slot:
            return True
        if getattr(bag_slot, 'handle', None) == getattr(slot, 'handle', None):
            return True
        if getattr(bag_slot, 'identifier', None) == getattr(slot, 'identifier', None):
            return True

    bag_handle = getattr(channelbag, 'slot_handle', None)
    slot_handle = getattr(slot, 'handle', None)
    if bag_handle is not None and slot_handle is not None and bag_handle == slot_handle:
        return True

    return False


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
