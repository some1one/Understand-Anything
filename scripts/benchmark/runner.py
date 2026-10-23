"""Isolated production commands. Build and asset preparation are never timed."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import threading

ROOT = Path(__file__).resolve().parents[2]
RUST = ROOT / 'understand-anything-plugin/packages/rust'


class StageError(Exception):
    def __init__(self, code, metric=None, count=1):
        super().__init__(code)
        self.code = code
        self.metric = metric
        self.count = count


def build(mode):
    command = ['cargo', '+stable', 'build', '--locked', '--offline', '--target-dir', str(RUST / 'target')]
    if mode == 'release':
        command.append('--release')
    subprocess.run(command, cwd=RUST, check=True)
    return RUST / 'target' / mode / 'understand-anything-rs'


def unstarted_metric(code):
    return dict(status='failed', durationMs=0, userCpuTimeMicros=None,
                systemCpuTimeMicros=None, maxWorkerPeakRssBytes=None,
                aggregatePeakRssBytes=None, workers=0, outputBytes=0,
                outputDigest=None, counts={}, error=code)


def worker(command, directory, name, stop, timeout=300):
    """wait4 measures this PID only, including when structure workers overlap."""
    if stop.is_set():
        raise StageError('cancelled', unstarted_metric('cancelled'))
    start = time.monotonic()
    usage = None
    reason = None
    with (directory / (name + '.stdout')).open('wb') as stdout, (directory / (name + '.stderr')).open('wb') as stderr:
        try:
            process = subprocess.Popen(command, cwd=directory, stdout=stdout, stderr=stderr,
                                       start_new_session=True, env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})
        except OSError as error:
            metric = unstarted_metric('worker-start-failed')
            metric['durationMs'] = (time.monotonic() - start) * 1000
            raise StageError('worker-start-failed', metric) from error
        finished = threading.Event()
        def kill():
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        def watchdog():
            nonlocal reason
            while not finished.wait(min(.02, max(0, timeout - (time.monotonic() - start)))):
                if stop.is_set() or time.monotonic() - start >= timeout:
                    reason = 'cancelled' if stop.is_set() else 'worker-timeout'
                    kill()
                    return
        monitor = threading.Thread(target=watchdog, daemon=True)
        monitor.start()
        try:
            # Blocking wait avoids adding polling intervals to short stage times.
            _, status, usage = os.wait4(process.pid, 0)
            elapsed = (time.monotonic() - start) * 1000
            process.returncode = os.waitstatus_to_exitcode(status)
        finally:
            finished.set()
            monitor.join()
            if process.returncode is None:
                kill()
                _, status, usage = os.wait4(process.pid, 0)
                process.returncode = os.waitstatus_to_exitcode(status)
    metric = {'status': 'ok' if process.returncode == 0 else 'failed',
              'durationMs': elapsed,
              'userCpuTimeMicros': usage.ru_utime * 1e6 if usage else None,
              'systemCpuTimeMicros': usage.ru_stime * 1e6 if usage else None,
              'maxWorkerPeakRssBytes': usage.ru_maxrss * (1 if sys.platform == 'darwin' else 1024) if usage and sys.platform in ('linux', 'darwin') else None,
              'aggregatePeakRssBytes': None, 'workers': 1, 'outputBytes': 0,
              'outputDigest': None, 'counts': {}, 'error': reason or ('worker-exit' if process.returncode else None)}
    if metric['error']:
        raise StageError(metric['error'], metric)
    return metric
