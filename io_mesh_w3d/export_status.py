# <pep8 compliant>
"""Live export status; all Blender work and UI drawing stay on the main thread."""

import os
import time
from collections import deque

import bpy

_last_status = None


def report_export_progress(context, phase=None, **values):
    status = getattr(context, '_w3d_export_status', None)
    if status is not None:
        status.update(phase, **values)


class ExportStatus:
    def __init__(self, filepath, clock=time.monotonic):
        self.filepath = filepath
        self.clock = clock
        self.started = clock()
        self.ended = None
        self.phase_started = self.started
        self.phase = 'Preparing export'
        self.detail = ''
        self.object_name = ''
        self.mesh_index = self.mesh_total = 0
        self.current = self.total = 0
        self.unit = ''
        self.result = None
        self.warnings = self.errors = 0
        self.messages = deque(maxlen=5)
        self.window = self.area = self.handler = None
        self._last_draw = -float('inf')
        self._drawing = False

    @property
    def elapsed(self):
        return (self.ended if self.ended is not None else self.clock()) - self.started

    def update(self, phase=None, force=False, **values):
        if self.result is not None:
            return
        if phase is not None and phase != self.phase:
            self.phase = phase
            self.phase_started = self.clock()
            self.current = self.total = 0
            self.unit = self.detail = ''
        for name, value in values.items():
            setattr(self, name, value)
        self.redraw(force)

    def record(self, level, message):
        if level == 'WARNING':
            self.warnings += 1
        elif level == 'ERROR':
            self.errors += 1
        if level in ('WARNING', 'ERROR'):
            self.messages.append((level, str(message)))
            self.redraw()

    def finish(self, result, message=''):
        self.ended = self.clock()
        self.result = result
        self.phase = 'Export complete' if result == 'FINISHED' else 'Export stopped'
        self.detail = message or ('File written successfully' if result == 'FINISHED' else 'See the export messages below')
        self.redraw(force=True)

    def open_window(self, context, previous=None):
        if bpy.app.background:
            return
        # Duplicate one area into a separate native Blender window. The
        # original workspace stays intact, and no extra UI library is needed.
        windows = context.window_manager.windows
        candidates = [(w, a) for w in windows for a in w.screen.areas if a.type == 'VIEW_3D']
        window, area = candidates[0] if candidates else (context.window, context.area)
        if previous is not None:
            self.window, self.area = previous
        else:
            before = {w.as_pointer() for w in windows}
            if hasattr(context, 'temp_override'):
                with context.temp_override(window=window, area=area):
                    bpy.ops.screen.area_dupli('INVOKE_DEFAULT')
            else:
                override = context.copy()
                override.update(window=window, screen=window.screen, area=area)
                bpy.ops.screen.area_dupli(override, 'INVOKE_DEFAULT')
            self.window = next((w for w in windows if w.as_pointer() not in before), None)
            if self.window is None:
                return
            self.area = self.window.screen.areas[0]
            self.area.type = 'IMAGE_EDITOR'
        space = self.area.spaces.active
        space.show_region_ui = False
        space.show_region_toolbar = False
        self.handler = bpy.types.SpaceImageEditor.draw_handler_add(self.draw, (), 'WINDOW', 'POST_PIXEL')
        self.redraw(force=True)

    def redraw(self, force=False):
        now = self.clock()
        if self.area is None or self._drawing or (not force and now - self._last_draw < 0.25):
            return
        self._last_draw = now
        self._drawing = True
        try:
            if self.window not in bpy.context.window_manager.windows[:]:
                self.dispose()
                return
            self.area.tag_redraw()
            if hasattr(bpy.context, 'temp_override'):
                with bpy.context.temp_override(window=self.window, area=self.area):
                    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
            else:
                override = bpy.context.copy()
                override.update(window=self.window, screen=self.window.screen, area=self.area)
                bpy.ops.wm.redraw_timer(override, type='DRAW_WIN_SWAP', iterations=1)
        except (ReferenceError, RuntimeError):
            # Closing the status window or losing a drawing context must never
            # interrupt export or alter its result.
            pass
        finally:
            self._drawing = False

    def dispose(self):
        if self.handler is not None:
            bpy.types.SpaceImageEditor.draw_handler_remove(self.handler, 'WINDOW')
            self.handler = None
        self.area = self.window = None

    def draw(self):
        try:
            if bpy.context.area != self.area:
                return
        except ReferenceError:
            return
        import blf
        import gpu
        from gpu_extras.batch import batch_for_shader

        region = bpy.context.region
        scale = bpy.context.preferences.system.ui_scale
        width, height = region.width, region.height
        margin = 24 * scale
        line_height = 27 * scale
        shader = gpu.shader.from_builtin('UNIFORM_COLOR' if bpy.app.version >= (4, 0, 0)
                                         else '2D_UNIFORM_COLOR')

        def rect(x, y, w, h, color):
            batch = batch_for_shader(shader, 'TRI_FAN', {'pos': [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]})
            shader.bind()
            shader.uniform_float('color', color)
            batch.draw(shader)

        def text(value, y, size=15, color=(0.85, 0.85, 0.85, 1)):
            value = str(value)
            if bpy.app.version < (4, 0, 0):
                blf.size(0, int(size * scale), 72)
            else:
                blf.size(0, size * scale)
            while value and blf.dimensions(0, value)[0] > width - margin * 2:
                value = value[:-4] + '...' if len(value) > 4 else ''
            blf.color(0, *color)
            blf.position(0, margin, y, 0)
            blf.draw(0, value)

        rect(0, 0, width, height, (0.055, 0.06, 0.07, 1))
        y = height - margin - 22 * scale
        title = self.phase if self.result else 'W3D / W3X Export Status'
        text(title, y, 22, (0.55, 0.85, 0.62, 1) if self.result == 'FINISHED' else (0.9, 0.9, 0.95, 1))
        y -= line_height * 1.5
        text(os.path.basename(self.filepath), y, 17)
        y -= line_height
        minutes, seconds = divmod(int(self.elapsed), 60)
        text(f'Elapsed: {minutes:02d}:{seconds:02d}    Warnings: {self.warnings}    Errors: {self.errors}', y)
        y -= line_height * 1.5
        if self.mesh_total:
            text(f'Mesh {self.mesh_index:,} of {self.mesh_total:,}: {self.object_name}', y, 17)
        elif self.object_name:
            text(self.object_name, y, 17)
        y -= line_height
        text(self.phase, y, 17)
        y -= line_height
        text(self.detail, y)
        y -= line_height * 1.4
        bar_width = max(1, width - margin * 2)
        rect(margin, y, bar_width, 10 * scale, (0.17, 0.18, 0.21, 1))
        if self.result == 'FINISHED':
            fraction = 1.0
        elif self.total:
            fraction = min(1.0, max(0.0, self.current / self.total))
        else:
            fraction = 0.0
        rect(margin, y, bar_width * fraction, 10 * scale, (0.25, 0.6, 0.85, 1))
        y -= line_height
        if self.total and not self.result:
            text(f'{self.unit}: {self.current:,} / {self.total:,}  (current step)', y)
        elif not self.result:
            text('Working...', y)
        y -= line_height * 1.5
        for level, message in self.messages:
            text(f'{level}: {message}', y, 13, (1, 0.72, 0.35, 1))
            y -= line_height
        text(self.filepath, margin + line_height, 12, (0.55, 0.57, 0.62, 1))
        text('Close this window when finished.' if self.result else 'Blender is busy exporting the scene.',
             margin, 12, (0.55, 0.57, 0.62, 1))


def start_export_status(context, filepath, show_window=True):
    global _last_status
    previous = None
    if _last_status is not None:
        try:
            if (_last_status.window in context.window_manager.windows[:]
                    and _last_status.area.type == 'IMAGE_EDITOR'):
                previous = (_last_status.window, _last_status.area)
        except (ReferenceError, AttributeError):
            pass
        _last_status.dispose()
    status = ExportStatus(filepath)
    _last_status = status
    if show_window:
        try:
            status.open_window(context, previous)
        except Exception as exc:
            status.dispose()
            print(f'W3D export status window unavailable: {exc}')
    return status


def unregister_export_status():
    global _last_status
    if _last_status is not None:
        _last_status.dispose()
        _last_status = None
