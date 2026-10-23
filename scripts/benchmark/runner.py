"""Isolated production commands. Build and asset preparation are never timed."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from .contract import digest

ROOT = Path(__file__).resolve().parents[2]
RUST = ROOT / 'understand-anything-plugin/packages/rust'


class StageError(Exception):
    def __init__(self, code, metric=None, count=1):
        super().__init__(code)
        self.code = code
        self.metric = metric
        self.count = count


def build(mode):
    command = ['cargo', '+stable', 'build', '--locked', '--offline']
    if mode == 'release':
        command.append('--release')
    subprocess.run(command, cwd=RUST, check=True)
    return RUST / 'target' / mode / 'understand-anything-rs'


def worker(command, directory, name, stop, timeout=300):
    """wait4 measures this PID only, including when structure workers overlap."""
    start = time.monotonic()
    usage = None
    reason = None
    with (directory / (name + '.stdout')).open('wb') as stdout, (directory / (name + '.stderr')).open('wb') as stderr:
        process = subprocess.Popen(command, cwd=directory, stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            while True:
                pid, status, usage = os.wait4(process.pid, os.WNOHANG)
                if pid:
                    process.returncode = os.waitstatus_to_exitcode(status)
                    break
                if stop.is_set() or time.monotonic() - start > timeout:
                    reason = 'cancelled' if stop.is_set() else 'worker-timeout'
                    os.killpg(process.pid, signal.SIGKILL)
                    _, status, usage = os.wait4(process.pid, 0)
                    process.returncode = os.waitstatus_to_exitcode(status)
                    break
                time.sleep(.01)
        finally:
            if process.returncode is None:
                os.killpg(process.pid, signal.SIGKILL)
                _, status, usage = os.wait4(process.pid, 0)
                process.returncode = os.waitstatus_to_exitcode(status)
    metric = {'status': 'ok' if process.returncode == 0 else 'failed',
              'durationMs': (time.monotonic() - start) * 1000,
              'userCpuTimeMicros': usage.ru_utime * 1e6 if usage else None,
              'systemCpuTimeMicros': usage.ru_stime * 1e6 if usage else None,
              'maxWorkerPeakRssBytes': usage.ru_maxrss * (1 if sys.platform == 'darwin' else 1024) if usage and sys.platform in ('linux', 'darwin') else None,
              'aggregatePeakRssBytes': None, 'workers': 1, 'outputBytes': 0,
              'outputDigest': None, 'error': reason or ('worker-exit' if process.returncode else None)}
    if metric['error']:
        raise StageError(metric['error'], metric)
    return metric
