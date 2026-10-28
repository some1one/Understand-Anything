#!/usr/bin/env python3
"""Measure a fresh plugin rebuild and native analysis in an external workspace (Linux)."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = Path(__file__).with_name('full-run.json')
TIME_FORMAT = '{"elapsedSeconds":%e,"userCpuSeconds":%U,"systemCpuSeconds":%S,"maxProcessRssKiB":%M,"inputBlocks":%I,"outputBlocks":%O,"majorPageFaults":%F,"minorPageFaults":%R,"voluntaryContextSwitches":%w,"involuntaryContextSwitches":%c,"exitCode":%x}'


def find_valgrind():
    local = ROOT / '.private/benchmark-tools/bin/valgrind'
    return str(local) if local.is_file() and os.access(local, os.X_OK) else shutil.which('valgrind')


def load_config(path):
    config = json.loads(path.read_text())
    defaults = json.loads(DEFAULT_CONFIG.read_text())
    if not isinstance(config, dict) or set(config) - set(defaults):
        raise ValueError('configuration must be an object containing only documented options')
    defaults.update(config)
    for key in ('concurrency', 'buildJobs'):
        if type(defaults[key]) is not int or not 1 <= defaults[key] <= 32:
            raise ValueError(f'{key} must be an integer from 1 through 32')
    if type(defaults['valgrindConcurrency']) is not int or not 1 <= defaults['valgrindConcurrency'] <= 32:
        raise ValueError('valgrindConcurrency must be an integer from 1 through 32')
    tools = defaults['valgrindTools']
    if not isinstance(tools, list) or any(tool not in ('callgrind', 'massif', 'memcheck') for tool in tools) or len(set(tools)) != len(tools):
        raise ValueError('valgrindTools must contain unique callgrind, massif or memcheck names')
    for key in ('phaseTimeoutSeconds', 'workerTimeoutSeconds', 'sampleIntervalSeconds', 'valgrindWorkerTimeoutSeconds'):
        value = defaults[key]
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'{key} must be finite and positive')
    if defaults['sampleIntervalSeconds'] < .02:
        raise ValueError('sampleIntervalSeconds must be at least 0.02')
    for key in ('parserLanguages', 'analysisCommand'):
        value = defaults[key]
        if key == 'analysisCommand' and value is None:
            continue
        if not isinstance(value, list) or any(not isinstance(arg, str) or not arg or '\x00' in arg for arg in value):
            raise ValueError(f'{key} must be an argv array of nonempty strings')
        if key == 'analysisCommand' and not value:
            raise ValueError('analysisCommand must be null or a nonempty argv array')
    return defaults


def source_ignore(directory, names):
    excluded = {'.git', '.ua', '.understand-anything', '.agents', 'target', 'target-valgrind',
                'node_modules', 'dist', 'build', '__pycache__', '.pytest_cache', '.venv', 'venv', '.private'}
    # The plugin owns a distributable .agents marketplace catalog. It is source,
    # unlike a checkout's locally installed .agents skills and runtime payload.
    if Path(directory).name == 'understand-anything-plugin':
        excluded.discard('.agents')
    return [name for name in names if name in excluded or name.startswith('.env')]


def snapshot_digest(snapshot):
    digest = hashlib.sha256()
    for path in sorted(snapshot.rglob('*')):
        if path.is_symlink():
            if not path.resolve().is_relative_to(snapshot):
                raise ValueError('source snapshot contains an external symlink')
            digest.update(b'link\0' + str(path.relative_to(snapshot)).encode() + b'\0' + os.readlink(path).encode() + b'\0')
        elif path.is_file():
            digest.update(b'file\0' + str(path.relative_to(snapshot)).encode() + b'\0')
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def phases(workspace, run_dir, subject, config):
    rust = workspace / 'understand-anything-plugin/packages/rust'
    dash = workspace / 'understand-anything-plugin/packages/dashboard'
    binary = rust / 'target/release/understand-anything-rs'
    runtime = run_dir / 'runtime'
    python = sys.executable
    cargo_config = workspace / 'scripts/benchmark/cargo-config.toml'
    result = [
        ('rust_dependencies', ['cargo', '+stable', '--config', str(cargo_config), 'fetch', '--locked'], rust),
        ('dashboard_dependencies', ['corepack', 'pnpm', 'install', '--frozen-lockfile', '--store-dir', str(run_dir / 'cache/pnpm')], dash),
        ('rust_rebuild', ['cargo', '+stable', '--config', str(cargo_config), 'build', '--release', '--locked', '--offline', '--timings', '-j', str(config['buildJobs']), '--target-dir', str(rust / 'target')], rust),
        ('parser_language_update', [str(binary), '--parser-cache-dir', str(runtime / 'parsers'), 'parsers', 'fetch', *config['parserLanguages']], workspace),
        ('dictionary_language_update', [python, str(workspace / 'understand-anything-plugin/scripts/update_dictionaries.py'), '--output', str(runtime / 'dictionaries')], workspace),
        ('dictionary_configuration', [python, str(workspace / 'understand-anything-plugin/scripts/configure_dictionaries.py'), '--plugin-root', str(workspace / 'understand-anything-plugin'), '--config', str(runtime / 'dictionary-config.json'), '--local-dir', str(runtime / 'dictionaries'), '--prefer-local', '--offline'], workspace),
        ('dashboard_rebuild', ['corepack', 'pnpm', 'build'], dash),
        ('plugin_package_rebuild', [python, str(workspace / 'scripts/build_dist.py'), '--prebuilt-rust', str(binary), '--prebuilt-dashboard'], workspace),
        ('native_analysis', [python, str(workspace / 'scripts/benchmark_large_repo.py'), str(subject), '--output', str(run_dir / 'native.benchmark.json'), '--parser-cache-dir', str(runtime / 'parsers'), '--no-build', '--concurrency', str(config['concurrency']), '--worker-timeout', str(config['workerTimeoutSeconds'])], workspace),
    ]
    if config['valgrindTools']:
        profiling_target = rust / 'target-valgrind'
        result.append(('rust_profiling_rebuild', [
            'cargo', '+stable', '--config', str(cargo_config),
            '--config', 'profile.release.debug=2', '--config', 'profile.release.strip="none"',
            '--config', 'build.rustflags=["-C", "dwarf-version=4"]',
            'build', '--release', '--locked', '--offline', '--timings',
            '-j', str(config['buildJobs']), '--target-dir', str(profiling_target)], rust))
        for tool in config['valgrindTools']:
            result.append((f'valgrind_{tool}', [
                python, str(workspace / 'scripts/benchmark/profile_native.py'), str(subject),
                '--binary', str(profiling_target / 'release/understand-anything-rs'),
                '--parser-cache-dir', str(runtime / 'parsers'), '--tool', tool,
                '--output-dir', str(run_dir / 'valgrind' / tool),
                '--baseline-report', str(run_dir / 'native.benchmark.json'),
                '--concurrency', str(config['valgrindConcurrency']),
                '--worker-timeout', str(config['valgrindWorkerTimeoutSeconds'])], workspace))
    if config['analysisCommand']:
        # No shell expansion: placeholders replace whole or partial argv values.
        replacements = {'{subject}': str(run_dir / 'analysis-subject'), '{plugin}': str(workspace / 'build/payload'),
                        '{workspace}': str(workspace), '{run_dir}': str(run_dir)}
        command = []
        for argument in config['analysisCommand']:
            for key, value in replacements.items():
                argument = argument.replace(key, value)
            command.append(argument)
        result.append(('host_model_analysis', command, workspace))
    return result


def process_tree_sample(group):
    """Sum instantaneous RSS for members of the command's process group."""
    rss, count = 0, 0
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            # comm may contain spaces and parentheses; parse after its last ')'.
            fields = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
            if int(fields[2]) != group:
                continue
            rss += int((proc / 'statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')
            count += 1
        except (OSError, ValueError, IndexError):
            continue
    return {'processes': count, 'rssSumBytes': rss}


def measure(name, command, cwd, directory, env, timeout, interval):
    metrics_path = directory / f'{name}.resources.json'
    samples_path = directory / f'{name}.samples.jsonl'
    started = time.monotonic()
    peak, peak_processes, status = 0, 0, 'ok'
    with (directory / f'{name}.log').open('wb') as log, samples_path.open('w') as samples:
        process = subprocess.Popen(['/usr/bin/time', '-f', TIME_FORMAT, '-o', str(metrics_path), '--', *command],
                                   cwd=cwd, env=env, stdout=log, stderr=log, start_new_session=True)
        try:
            while process.poll() is None:
                sample = process_tree_sample(process.pid)
                sample['elapsedSeconds'] = time.monotonic() - started
                samples.write(json.dumps(sample) + '\n')
                peak = max(peak, sample['rssSumBytes'])
                peak_processes = max(peak_processes, sample['processes'])
                if sample['elapsedSeconds'] >= timeout:
                    status = 'timeout'
                    break
                time.sleep(interval)
        except KeyboardInterrupt:
            status = 'cancelled'
        finally:
            # Also stop descendants left running after their parent exited.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
    result = {'name': name, 'status': status, 'exitCode': process.returncode,
              'durationSeconds': time.monotonic() - started,
              'sampledPeakProcessGroupRssSumBytes': peak or None,
              'sampledPeakProcesses': peak_processes or None,
              'log': f'logs/{name}.log', 'samples': f'logs/{name}.samples.jsonl'}
    if metrics_path.is_file():
        try:
            result['resources'] = json.loads(metrics_path.read_text().splitlines()[-1])
        except (ValueError, IndexError):
            result['resources'] = None
    else:
        result['resources'] = None
    if status == 'ok' and process.returncode:
        result['status'] = 'failed'
    return result


def identity(command, cwd):
    try:
        return subprocess.check_output(command, cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def write_report(run_dir, report):
    # Reports are checkpoints; logs/workspaces remain available on failure.
    temporary = run_dir / 'report.json.tmp'
    temporary.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    temporary.replace(run_dir / 'report.json')
    lines = ['# Full-run benchmark', '', f"Status: {report['status']}", '',
             '| Phase | Status | Wall seconds | User CPU seconds | System CPU seconds | Max process RSS KiB | Sampled process-group RSS sum bytes |',
             '| --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for phase in report['phases']:
        resource = phase.get('resources') or {}
        lines.append(f"| {phase['name']} | {phase['status']} | {phase['durationSeconds']:.3f} | {resource.get('userCpuSeconds', 'unavailable')} | {resource.get('systemCpuSeconds', 'unavailable')} | {resource.get('maxProcessRssKiB', 'unavailable')} | {phase['sampledPeakProcessGroupRssSumBytes'] or 'unavailable'} |")
    lines += ['', f"Total elapsed seconds: {report['totalSeconds']:.3f}", '',
              'RSS samples sum shared pages across processes and can miss short peaks. Process-group accounting excludes descendants that detach into a new session. GNU time maximum RSS is not aggregate concurrent memory.',
              '', 'Native pipeline measurements are in native.benchmark.json and native.benchmark.md. Host/model analysis runs only when analysisCommand is configured. Logs and optional host commands may contain private paths or source.']
    (run_dir / 'report.md').write_text('\n'.join(lines) + '\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('subject', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True, help='new directory outside tool checkout and subject; retained in full')
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--plan', action='store_true', help='print phase commands without creating files or running tools')
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        subject, run_dir = args.subject.resolve(), args.output_dir.resolve()
        if not subject.is_dir():
            raise ValueError('subject must be an existing directory')
        if run_dir.is_relative_to(subject) or run_dir.is_relative_to(ROOT) or subject.is_relative_to(run_dir) or ROOT.is_relative_to(run_dir):
            raise ValueError('output directory must be disjoint from subject and tool checkout')
        if run_dir.exists():
            raise ValueError('output directory must not already exist; use a new path for each run')
        workspace = run_dir / 'workspace'
        plan = phases(workspace, run_dir, subject, config)
        if args.plan:
            print(json.dumps([{'name': name, 'argv': command, 'cwd': str(cwd)} for name, command, cwd in plan], indent=2))
            return 0
        if sys.platform != 'linux' or not Path('/usr/bin/time').is_file():
            raise ValueError('full-run measurements require Linux and GNU /usr/bin/time')
        for executable in ('cargo', 'rustc', 'corepack', 'git'):
            if shutil.which(executable) is None:
                raise ValueError(f'missing prerequisite: {executable}')
        valgrind = find_valgrind()
        if config['valgrindTools'] and valgrind is None:
            raise ValueError('Valgrind is required for profiling; run make benchmark-setup or set valgrindTools to []')
        if config['analysisCommand'] and any('codex_analysis.py' in arg for arg in config['analysisCommand']):
            if shutil.which('codex') is None or subprocess.run(['codex', 'login', 'status'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
                raise ValueError('Codex full analysis requires an installed, authenticated CLI; run codex login first')
        run_dir.mkdir(parents=True)
        (run_dir / 'logs').mkdir()
        report = {'schemaVersion': '1.0.0', 'reportType': 'full-run-benchmark', 'status': 'running',
                  'startedAt': datetime.now(timezone.utc).isoformat(), 'configuration': config,
                  'toolCommit': identity(['git', 'rev-parse', 'HEAD'], ROOT),
                  'toolDirtyState': identity(['git', 'status', '--porcelain'], ROOT),
                  'subjectCommit': identity(['git', 'rev-parse', 'HEAD'], subject),
                  'subjectDirtyState': identity(['git', 'status', '--porcelain'], subject),
                  'environment': {'platform': platform.platform(), 'logicalCores': os.cpu_count(),
                                  'rustc': identity(['rustc', '+stable', '-Vv'], ROOT),
                                  'cargo': identity(['cargo', '+stable', '--version'], ROOT),
                                  'node': identity(['node', '--version'], ROOT),
                                  'codex': identity(['codex', '--version'], ROOT),
                                  'gnuTime': identity(['/usr/bin/time', '--version'], ROOT),
                                  'valgrind': identity([valgrind, '--version'], ROOT) if valgrind else None,
                                  'memoryInfo': Path('/proc/meminfo').read_text(),
                                  'cpuInfo': Path('/proc/cpuinfo').read_text()},
                  'phases': [], 'totalSeconds': 0, 'cacheMode': 'fresh-run-local-cargo-pnpm-parser-dictionary-caches; OS cache uncontrolled'}
        started = time.monotonic()
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('CARGO_', 'UA_', 'PNPM_', 'COREPACK_'))
               and key not in {'RUSTFLAGS', 'RUSTDOCFLAGS', 'RUSTC', 'RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'RUSTUP_TOOLCHAIN'}}
        env.update(CARGO_HOME=str(run_dir / 'cache/cargo'), UA_PARSER_CACHE_DIR=str(run_dir / 'runtime/parsers'),
                   UA_DICTIONARY_CONFIG=str(run_dir / 'runtime/dictionary-config.json'), CARGO_BUILD_JOBS=str(config['buildJobs']),
                   COREPACK_HOME=str(run_dir / 'cache/corepack'), CARGO_INCREMENTAL='0')
        if valgrind:
            env['PATH'] = str(Path(valgrind).parent) + os.pathsep + env.get('PATH', os.defpath)
        write_report(run_dir, report)
        try:
            copying = time.monotonic()
            shutil.copytree(ROOT, workspace, ignore=source_ignore, symlinks=True)
            report['workspaceCopySeconds'] = time.monotonic() - copying
            if config['analysisCommand']:
                copying = time.monotonic()
                shutil.copytree(subject, run_dir / 'analysis-subject', ignore=source_ignore, symlinks=True)
                report['subjectCopySeconds'] = time.monotonic() - copying
            # Hash exactly the staged source; the source checkout may be dirty.
            report['toolSourceDigest'] = snapshot_digest(workspace)
            if config['analysisCommand']:
                report['subjectSourceDigest'] = snapshot_digest(run_dir / 'analysis-subject')
            for name, command, cwd in plan:
                print(f'Measuring {name}…', flush=True)
                phase = measure(name, command, cwd, run_dir / 'logs', env,
                                config['phaseTimeoutSeconds'], config['sampleIntervalSeconds'])
                report['phases'].append(phase)
                report['totalSeconds'] = time.monotonic() - started
                if phase['status'] != 'ok':
                    report['status'] = phase['status']
                write_report(run_dir, report)
                if phase['status'] != 'ok':
                    break
                if name == 'host_model_analysis':
                    sys.path.insert(0, str(workspace / 'scripts'))
                    from benchmark_static import summarize
                    statistics = summarize(run_dir / 'analysis-subject/.ua', phase['durationSeconds'], 'full')
                    (run_dir / 'analysis-statistics.json').write_text(json.dumps(statistics, indent=2) + '\n')
            else:
                report['status'] = 'ok'
        except (OSError, ValueError) as error:
            report.update(status='failed', error=str(error))
        except KeyboardInterrupt:
            report.update(status='cancelled')
        report['totalSeconds'] = time.monotonic() - started
        write_report(run_dir, report)
        print(f"Report: {run_dir / 'report.md'}")
        return 0 if report['status'] == 'ok' else 130 if report['status'] == 'cancelled' else 1
    except (OSError, ValueError) as error:
        print(f'Full-run benchmark: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    def terminate(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    raise SystemExit(main())
