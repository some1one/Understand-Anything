"""Serialized report pairs with caught-failure rollback (not crash atomic)."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile

from .isolation import output_path


class DeliveryError(Exception):
    def __init__(self, rollback_failures=0, cleanup_failures=0):
        super().__init__('delivery-failed')
        self.rollback_failures = rollback_failures
        self.cleanup_failures = cleanup_failures


def markdown(report):
    lines = ['# Native deterministic benchmark', '', f'pairId: {report["pairId"]}', '',
             f'Status: **{report["status"]}**; schema: {report["schemaVersion"]}.', '',
             'This measures scanning, imports, batch planning, and structure extraction.',
             'No LLM execution, token counts, cost, or end-to-end analysis is measured.', '',
             f'Tool commit: `{report["tool"]["commit"]}`; subject commit: `{report["subject"]["commit"]}`.',
             f'Build: {report["configuration"]["buildMode"]}; concurrency: {report["configuration"]["concurrency"]}.',
             f'Parser cache: {report["configuration"]["parserCache"]}.',
             f'Filesystem cache: {report["configuration"]["filesystemCache"]}.', '']
    if report['tool']['dirty'] or report['subject']['dirty']:
        lines += ['**Dirty worktree: tool or subject has uncommitted changes.**', '']
    lines += ['| Stage | Status | Wall ms | User CPU us | System CPU us | Max worker RSS bytes |',
              '| --- | --- | ---: | ---: | ---: | ---: |']
    for name, stage in report['stages'].items():
        values = [name, stage['status']] + [str(round(stage[key], 2)) if stage[key] is not None else 'unsupported' for key in ('durationMs', 'userCpuTimeMicros', 'systemCpuTimeMicros', 'maxWorkerPeakRssBytes')]
        lines.append('| ' + ' | '.join(values) + ' |')
    lines += ['', 'Structure CPU sums all workers. RSS is the maximum individual worker;',
              'aggregate concurrent memory is unsupported.', '']
    if report['coverage']:
        lines += ['Coverage: ' + ', '.join(f'{k}={v}' for k, v in report['coverage'].items()), '']
    if report['determinism']:
        lines += [f'Input SHA-256: `{report["determinism"]["inputDigest"]}`',
                  f'Semantic output SHA-256: `{report["determinism"]["outputDigest"]}`', '']
    if report['error']:
        lines += [f'Error code: `{report["error"]}`.', '']
    lines += [f'Warnings: {report["warningCount"]}; bounded summaries: {len(report["warnings"])}.', '',
              'Pair delivery is not crash atomic. Readers must reject missing or mismatched pair IDs.', '']
    return '\n'.join(lines)


@contextmanager
def lock(output, exclusive):
    # Keep the lock inode: unlinking it could let another writer lock a new inode.
    with output.with_suffix('.lock').open('a+b') as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield


def staged(path, data):
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return temp
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def publish(report, output, subject):
    output = output_path(subject, output)
    output.parent.mkdir(parents=True, exist_ok=True)
    paths = (output, output.with_suffix('.md'))
    pending = []
    backups = {}
    replaced = []
    try:
        with lock(output, True):
            output_path(subject, output)
            failure = None
            try:
                for path in paths:
                    backups[path] = path.read_bytes() if path.exists() else None
                for path, data in zip(paths, (json.dumps(report, indent=2).encode() + b'\n', markdown(report).encode())):
                    pending.append(staged(path, data))
                for path, temp in zip(paths, pending):
                    os.replace(temp, path)
                    replaced.append(path)
            except BaseException as error:
                failures = 0
                for path in reversed(replaced):
                    try:
                        backup = backups[path]
                        if backup is None:
                            path.unlink(missing_ok=True)
                        else:
                            restored = staged(path, backup)
                            pending.append(restored)
                            os.replace(restored, path)
                    except OSError:
                        failures += 1
                failure = DeliveryError(failures)
            finally:
                for path in pending:
                    try:
                        if path.exists():
                            path.unlink()
                    except OSError:
                        failure = failure or DeliveryError()
                        failure.cleanup_failures += 1
            if failure:
                raise failure
    except (OSError, ValueError) as error:
        raise DeliveryError() from error


def read_pair(output):
    output = Path(output).resolve()
    with lock(output, False):
        report = json.loads(output.read_text())
        match = re.search(r'^pairId: ([0-9a-f-]+)$', output.with_suffix('.md').read_text(), re.MULTILINE)
        if not match or match[1] != report.get('pairId'):
            raise ValueError('report-pair-mismatch')
        return report
