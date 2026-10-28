#!/usr/bin/env python3
"""Replay the production native pipeline under a single Valgrind tool (Linux)."""
import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET

# Works as a direct script in the copied tool workspace.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmark.contract import new_report
from benchmark.isolation import assets_identity, git_identity, git_state_digest, hash_file
from benchmark.pipeline import run
from benchmark.full_run import find_valgrind
from benchmark.delivery import read_pair


def compare_semantics(baseline, measured):
    expected, actual = baseline.get('determinism') or {}, measured.get('determinism') or {}
    return {key: expected.get(key) == actual.get(key) if expected.get(key) and actual.get(key) else None
            for key in ('inputDigest', 'outputDigest')}


def valgrind_prefix(tool, directory):
    base = [find_valgrind() or 'valgrind', f'--tool={tool}', '--trace-children=no',
            '--child-silent-after-fork=yes', '--read-inline-info=yes',
            f'--log-file={directory}/{{worker}}.%p.log']
    if tool == 'callgrind':
        return base + ['--cache-sim=yes', '--branch-sim=yes',
                       f'--callgrind-out-file={directory}/{{worker}}.%p.callgrind']
    if tool == 'massif':
        return base + ['--stacks=yes', '--time-unit=i',
                       f'--massif-out-file={directory}/{{worker}}.%p.massif']
    if tool == 'memcheck':
        return base + ['--leak-check=full', '--show-leak-kinds=definite,indirect',
                       '--errors-for-leak-kinds=definite,indirect', '--error-exitcode=97',
                       '--xml=yes', f'--xml-file={directory}/{{worker}}.%p.xml']
    raise ValueError('unsupported Valgrind tool')


def callgrind_summary(path):
    events, values = None, None
    with path.open() as stream:
        for line in stream:
            if line.startswith('events:'):
                events = line.split()[1:]
            elif line.startswith('summary:'):
                values = [int(value) for value in line.split()[1:]]
    if not events or values is None or len(events) != len(values):
        raise ValueError(f'incomplete Callgrind profile: {path.name}')
    return {'file': path.name, 'events': dict(zip(events, values))}


def massif_summary(path):
    snapshots, current = [], None
    with path.open() as stream:
        for line in stream:
            if line.startswith('snapshot='):
                if current is not None:
                    snapshots.append(current)
                current = {'snapshot': int(line.split('=', 1)[1])}
            elif current is not None and line.startswith(('mem_heap_B=', 'mem_heap_extra_B=', 'mem_stacks_B=')):
                key, value = line.strip().split('=', 1)
                current[key] = int(value)
    if current is not None:
        snapshots.append(current)
    keys = ('mem_heap_B', 'mem_heap_extra_B', 'mem_stacks_B')
    if not snapshots or any(any(key not in snapshot for key in keys) for snapshot in snapshots):
        raise ValueError(f'incomplete Massif profile: {path.name}')
    peak = max(snapshots, key=lambda row: sum(row[key] for key in keys))
    return {'file': path.name, 'snapshots': len(snapshots), 'peakSnapshot': peak,
            'peakHeapAndStackBytes': sum(peak[key] for key in keys)}


def memcheck_summary(path):
    root = ET.parse(path).getroot()
    finished = root.find("./status[state='FINISHED']") is not None
    if root.tag != 'valgrindoutput' or not finished:
        raise ValueError(f'incomplete Memcheck profile: {path.name}')
    errors = root.findall('error')
    occurrences = {pair.findtext('unique'): int(pair.findtext('count', '0')) for pair in root.findall('./errorcounts/pair')}
    return {'file': path.name, 'errorRecords': len(errors),
            'errorsByKind': dict(Counter(error.findtext('kind', 'unknown') for error in errors)),
            'reportedOccurrences': sum(occurrences.values()),
            'definitelyOrIndirectlyLostBytes': sum(int(error.findtext('./xwhat/leakedbytes', '0')) for error in errors
                if error.findtext('kind') in ('Leak_DefinitelyLost', 'Leak_IndirectlyLost'))}


def summarize_profiles(tool, directory):
    suffix, reader = {'callgrind': ('callgrind', callgrind_summary),
                      'massif': ('massif', massif_summary), 'memcheck': ('xml', memcheck_summary)}[tool]
    profiles, errors = [], []
    for path in sorted(directory.glob(f'*.{suffix}')):
        try:
            profiles.append(reader(path))
        except (OSError, ValueError, ET.ParseError) as error:
            errors.append(str(error))
    result = {'profiles': profiles, 'profileReadErrors': errors, 'processProfiles': len(profiles)}
    if tool == 'callgrind':
        totals = Counter()
        for profile in profiles:
            totals.update(profile['events'])
        result['summedEvents'] = dict(totals)
    elif tool == 'massif':
        result['largestProcessPeakHeapAndStackBytes'] = max((p['peakHeapAndStackBytes'] for p in profiles), default=None)
    else:
        result['errorRecords'] = sum(p['errorRecords'] for p in profiles)
        result['reportedOccurrences'] = sum(p['reportedOccurrences'] for p in profiles)
        result['definitelyOrIndirectlyLostBytes'] = sum(p['definitelyOrIndirectlyLostBytes'] for p in profiles)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('subject', type=Path)
    parser.add_argument('--binary', type=Path, required=True, help='optimized Rust executable with debug symbols')
    parser.add_argument('--parser-cache-dir', type=Path, required=True)
    parser.add_argument('--tool', choices=('callgrind', 'massif', 'memcheck'), required=True)
    parser.add_argument('--output-dir', type=Path, required=True, help='new directory outside subject')
    parser.add_argument('--baseline-report', type=Path, help='ordinary benchmark JSON/Markdown pair for semantic comparison')
    parser.add_argument('--concurrency', type=int, choices=range(1, 33), default=1)
    parser.add_argument('--worker-timeout', type=float, default=3600)
    args = parser.parse_args(argv)
    stop = threading.Event()
    handlers = {}
    try:
        subject, binary, cache, output = (path.resolve() for path in
            (args.subject, args.binary, args.parser_cache_dir, args.output_dir))
        valgrind = find_valgrind()
        if sys.platform != 'linux' or valgrind is None:
            raise ValueError('Linux and Valgrind are required; run make benchmark-setup')
        if not subject.is_dir() or not binary.is_file() or not os.access(binary, os.X_OK):
            raise ValueError('subject and executable binary must exist')
        if not math.isfinite(args.worker_timeout) or args.worker_timeout <= 0:
            raise ValueError('worker timeout must be finite and positive')
        if output.is_relative_to(subject) or subject.is_relative_to(output) or output.is_relative_to(cache) or cache.is_relative_to(output) or binary.is_relative_to(output):
            raise ValueError('profile output must be disjoint from subject, parser cache and binary')
        if output.exists():
            raise ValueError('profile output directory must not already exist')
        parser_digest = assets_identity(cache)
        baseline = read_pair(args.baseline_report.resolve()) if args.baseline_report else None
        subject_git = git_identity(subject)
        subject_state = git_state_digest(subject)
        output.mkdir(parents=True)
        artifacts = output / 'artifacts'
        profiles = output / 'profiles'
        artifacts.mkdir()
        profiles.mkdir()
        report = new_report()
        report['configuration']['concurrency'] = args.concurrency
        report['configuration']['buildMode'] = 'release'
        def cancel(signum, frame):
            stop.set()
        for sig in (signal.SIGINT, signal.SIGTERM):
            handlers[sig] = signal.signal(sig, cancel)
        started = time.monotonic()
        run(report, subject, artifacts, binary, cache, stop, args.worker_timeout,
            command_prefix=valgrind_prefix(args.tool, profiles))
        if (git_identity(subject) != subject_git or git_state_digest(subject) != subject_state
                or assets_identity(cache) != parser_digest):
            report.update(status='failed', error='inputs-changed-during-profiling')
        summary = summarize_profiles(args.tool, profiles)
        comparison = compare_semantics(baseline, report) if baseline else None
        if report['status'] != 'failed' and comparison and not all(value is True for value in comparison.values()):
            report.update(status='failed', error='baseline-semantic-mismatch')
        expected = 3 + report.get('stages', {}).get('structure', {}).get('workers', 0)
        if report['status'] != 'failed' and (summary['profileReadErrors'] or summary['processProfiles'] != expected):
            report.update(status='failed', error='missing-or-invalid-valgrind-profiles')
        result = {'schemaVersion': '1.0.0', 'reportType': 'valgrind-native-profile',
                  'tool': args.tool, 'valgrindVersion': subprocess.check_output([valgrind, '--version'], text=True).strip(),
                  'binaryDigest': hash_file(binary), 'parserAssetsDigest': parser_digest,
                  'status': report['status'], 'durationSeconds': time.monotonic() - started,
                  'baselineSemanticComparison': comparison,
                  'instrumentedNativeResults': report, 'summary': summary,
                  'limitations': ['Instrumented timings are not ordinary runtime measurements.',
                                  'Callgrind cache/branch events are simulated.',
                                  'Massif heap/stack profiles exclude other mapped memory and are per-process; peaks are not summed.',
                                  'These passes profile the four native stages, not remote model computation or other graph helpers.']}
        (output / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
        text = ['# Valgrind native profile', '', f'Tool: {args.tool}', f"Status: {result['status']}",
                '', '```json', json.dumps({key: value for key, value in summary.items() if key != 'profiles'}, indent=2),
                '```', ''] + ['- ' + note for note in result['limitations']]
        (output / 'summary.md').write_text('\n'.join(text) + '\n')
        print(f"Profile summary: {output / 'summary.md'}")
        return 130 if stop.is_set() else 1 if report['status'] == 'failed' else 0
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f'Native profiling: {error}', file=sys.stderr)
        return 2
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    raise SystemExit(main())
