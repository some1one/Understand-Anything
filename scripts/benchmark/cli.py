"""Opt-in benchmark orchestration; all analysis runs in the Rust engine."""
import argparse
from datetime import datetime, timezone
import os
import math
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import threading
import time
import tomllib

from .contract import new_report
from .delivery import DeliveryError, publish, read_pair
from .isolation import assets_identity, git_identity, git_state_digest, hash_file, ignore_identity, output_path, workspace
from .pipeline import run
from .runner import build, ROOT, RUST

EXCLUSIONS = ['.ua/', '.understand-anything/', '*.benchmark.json', '*.benchmark.md', '*.benchmark.lock']


def now():
    return datetime.now(timezone.utc).isoformat()


def environment(cache):
    cpu = platform.processor() or None
    try:
        for line in Path('/proc/cpuinfo').read_text().splitlines():
            if line.startswith('model name'):
                cpu = line.split(':', 1)[1].strip()
                break
    except OSError:
        pass
    try:
        memory = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')
    except (ValueError, OSError):
        memory = None
    try:
        rustc = subprocess.check_output(['rustc', '+stable', '--version'], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        rustc = None
    return dict(os=platform.system(), release=platform.release(), arch=platform.machine(),
                cpuModel=cpu, logicalCores=os.cpu_count(), totalMemoryBytes=memory, rustc=rustc,
                parserVersion='1.20.0', parserAssetsDigest=assets_identity(cache), dictionary='unused')


def cleanup(directory):
    shutil.rmtree(directory)


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('subject', nargs='?', type=Path)
    cli.add_argument('--output', type=Path, help='required external JSON path; Markdown and persistent lock are adjacent')
    cli.add_argument('--parser-cache-dir', type=Path, help='required preconfigured language-pack BASE cache directory')
    cli.add_argument('--concurrency', type=int, choices=range(1, 33), default=1, metavar='1..32')
    cli.add_argument('--build-mode', choices=('release', 'debug'), default='release')
    cli.add_argument('--no-build', action='store_true', help='use a fresh existing source binary of the selected mode')
    cli.add_argument('--warm-filesystem-cache', action='store_true', help='label a later run warm-requested; does not flush or warm OS caches')
    cli.add_argument('--keep-artifacts', action='store_true', help='retain private artifacts and print their location to stderr')
    cli.add_argument('--worker-timeout', type=float, default=300, help='positive per-worker timeout seconds (default 300)')
    cli.add_argument('--check-pair', type=Path, help='check an existing pair ID and exit; no benchmark')
    return cli


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    if args.check_pair:
        try:
            read_pair(args.check_pair)
            print('report-pair-ok')
            return 0
        except (OSError, ValueError):
            print('report-pair-invalid', file=sys.stderr)
            return 2
    if args.subject is None or args.output is None or args.parser_cache_dir is None:
        cli.error('subject, --output and --parser-cache-dir are required')
    if args.worker_timeout <= 0 or not math.isfinite(args.worker_timeout):
        cli.error('--worker-timeout must be finite and positive')
    if not hasattr(os, 'wait4'):
        cli.error('this benchmark requires POSIX wait4 and flock (Linux or macOS)')
    subject = args.subject.resolve()
    try:
        if not subject.is_dir():
            raise ValueError('subject-must-be-directory')
        output = output_path(subject, args.output)
        if not args.no_build and RUST.is_relative_to(subject):
            raise ValueError('prebuild-tool-and-use-no-build-when-tool-is-inside-subject')
        cache = args.parser_cache_dir.resolve()
        assets_identity(cache)
    except (OSError, ValueError) as error:
        # These are fixed validation codes, never raw OS diagnostics.
        print(str(error) if isinstance(error, ValueError) else 'preflight-failed', file=sys.stderr)
        return 2
    report = new_report()
    report['configuration'].update(concurrency=args.concurrency, buildMode=args.build_mode,
                                  filesystemCache='warm-requested' if args.warm_filesystem_cache else 'potentially-cold')
    stop = threading.Event()
    handlers = {}
    def cancel(signum, frame):
        stop.set()
    for sig in (signal.SIGINT, signal.SIGTERM):
        handlers[sig] = signal.signal(sig, cancel)
    directory = None
    started = time.monotonic()
    report['run']['startedAt'] = now()
    try:
        # No compilation or setup is included in any per-stage metric.
        binary = RUST / 'target' / args.build_mode / 'understand-anything-rs'
        if args.no_build:
            sources = list((RUST / 'src').rglob('*')) + list((RUST / 'schemas').glob('*')) + list((RUST / 'reference').glob('*.json')) + [RUST / 'Cargo.toml', RUST / 'Cargo.lock']
            if not binary.is_file() or any(p.is_file() and p.stat().st_mtime_ns > binary.stat().st_mtime_ns for p in sources):
                raise ValueError('source-binary-missing-or-stale')
        else:
            binary = build(args.build_mode)
        directory = workspace(subject)
        report['tool'].update(git_identity(ROOT), packageVersion=tomllib.loads((RUST / 'Cargo.toml').read_text())['package']['version'], binaryDigest=hash_file(binary))
        report['subject'] = git_identity(subject)
        initial_git = report['subject'].copy()
        initial_git_status = git_state_digest(subject)
        report['environment'] = environment(cache)
        report['configuration']['ignoreRules'] = ignore_identity(subject, EXCLUSIONS)
        if stop.is_set():
            raise ValueError('cancelled')
        run(report, subject, directory, binary, cache, stop, args.worker_timeout)
        if git_identity(subject) != initial_git or git_state_digest(subject) != initial_git_status:
            # Preserve a stage's primary failure if one has already occurred.
            if report['error'] is None:
                report.update(status='failed', error='subject-git-state-changed')
        if assets_identity(cache) != report['environment']['parserAssetsDigest'] and report['error'] is None:
            report.update(status='failed', error='parser-assets-changed')
    except ValueError as error:
        code = str(error)
        allowed = ('cancelled', 'source-binary-missing-or-stale', 'temporary-directory-inside-subject',
                   'parser-assets-not-preconfigured', 'parser-assets-empty')
        report.update(status='failed', error=code if code in allowed else 'setup-invalid')
    except (OSError, subprocess.CalledProcessError):
        report.update(status='failed', error='setup-failed')
    finally:
        if directory:
            if args.keep_artifacts:
                print(f'Private artifacts (may contain source, paths, and diagnostics): {directory}', file=sys.stderr)
            else:
                try:
                    cleanup(directory)
                except OSError:
                    if report['error']:
                        report['secondaryErrors'].append('cleanup-failed')
                    else:
                        report.update(status='failed', error='cleanup-failed')
        report['run'].update(finishedAt=now(), durationMs=(time.monotonic() - started) * 1000)
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
    try:
        publish(report, output, subject)
    except DeliveryError as error:
        print('delivery-failed' + ('; rollback-failed' if error.rollback_failures else '') + ('; cleanup-failed' if error.cleanup_failures else ''), file=sys.stderr)
        return 3
    print(f'benchmark-{report["status"]}', file=sys.stderr)
    return 130 if stop.is_set() else (1 if report['status'] == 'failed' else 0)
