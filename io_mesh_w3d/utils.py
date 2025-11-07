# <pep8 compliant>
# Written by Stephan Vedder and Michael Schnabel


class ReportHelper():
    def _append_log(self, level, msg):
        log = getattr(self, '_w3d_log_buffer', None)
        if log is not None:
            log.append(f'{level}: {msg}')

    def info(self, msg):
        self._append_log('INFO', msg)
        print(f'INFO: {msg}')
        self.report({'INFO'}, str(msg))

    def warning(self, msg):
        self._append_log('WARNING', msg)
        print(f'WARNING: {msg}')
        self.report({'WARNING'}, str(msg))

    def error(self, msg):
        self._append_log('ERROR', msg)
        print(f'ERROR: {msg}')
        self.report({'ERROR'}, str(msg))
