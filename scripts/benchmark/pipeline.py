"""Run four production stages and independently check their integrity."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time

from .contract import digest, SAMPLE_LIMIT
from .isolation import input_identity
from .runner import StageError, worker


def write(path, value):
    path.write_text(json.dumps(value))
    return path


def read(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise StageError('invalid-output') from error


def warn(report, stage, code, count):
    if not count:
        return
    report['warningCount'] += count
    for entry in report['warnings']:
        if entry['stage'] == stage and entry['code'] == code:
            entry['count'] += count
            return
    if len(report['warnings']) < SAMPLE_LIMIT:
        report['warnings'].append(dict(stage=stage, code=code, count=count))
    else:
        report['warningsTruncated'] = True


def check(condition):
    if not condition:
        raise StageError('invalid-output')


def combined_metrics(metrics, elapsed):
    def total(key):
        return sum(m[key] for m in metrics) if all(m[key] is not None for m in metrics) else None
    rss = [m['maxWorkerPeakRssBytes'] for m in metrics]
    return dict(status='failed' if any(m['status'] == 'failed' for m in metrics) else 'ok',
                durationMs=elapsed, userCpuTimeMicros=total('userCpuTimeMicros'),
                systemCpuTimeMicros=total('systemCpuTimeMicros'),
                maxWorkerPeakRssBytes=max(rss) if rss and all(v is not None for v in rss) else None,
                aggregatePeakRssBytes=None, workers=len(metrics),
                outputBytes=sum(m['outputBytes'] for m in metrics), outputDigest=None,
                error=next((m['error'] for m in metrics if m['error']), None))


def run(report, subject, directory, binary, cache, stop, timeout=300):
    command = [str(binary), '--offline-parsers', '--parser-cache-dir', str(cache)]
    coverage = {key: 0 for key in ('files', 'structureSucceeded', 'structureUnsupported', 'parseFailed',
                                 'unreadable', 'invalidOutputs', 'callGraphSupported', 'callGraphUnsupported')}
    report['coverage'] = coverage
    current = 'scan'

    def invoke(stage, arguments, output, name=None):
        try:
            metric = worker(command + list(map(str, arguments)), directory, name or stage, stop, timeout)
        except StageError as error:
            if error.metric:
                report['stages'][stage] = error.metric
            raise
        report['stages'][stage] = metric
        value = read(output)
        check(isinstance(value, dict) and value.get('scriptCompleted', stage == 'batching') is True)
        metric['outputBytes'] = output.stat().st_size
        metric['outputDigest'] = digest(value)
        # Raw diagnostics stay private; publish only bounded fixed codes.
        log = directory / ((name or stage) + '.stderr')
        with log.open('rb') as stream:
            warnings = sum(line.count(b'Warning:') for line in iter(lambda: stream.readline(8192), b''))
        warn(report, stage, 'worker-warning', warnings)
        return value

    try:
        scan_path = directory / 'scan.json'
        scan = invoke('scan', ['scan_project', subject, scan_path, '--exclude=.ua/,.understand-anything/,*.benchmark.json,*.benchmark.md,*.benchmark.lock'], scan_path)
        check(isinstance(scan.get('files'), list) and scan.get('totalFiles') == len(scan['files']))
        files = scan['files']
        paths = [f['path'] for f in files]
        check(len(set(paths)) == len(paths))
        coverage['files'] = len(files)
        failures = scan.get('failures', [])
        coverage['unreadable'] = len(failures)
        warn(report, 'scan', 'scan-unreadable', len(failures))
        if failures:
            raise StageError('scan-unreadable')
        # Includes containment checking before any parser can follow a symlink.
        initial = input_identity(subject, files)
        report['determinism'] = dict(inputDigest=initial, outputDigest=None)
        report['scale'] = dict(files=len(files), bytes=sum((subject / p).stat().st_size for p in paths),
                               lines=sum(f['sizeLines'] for f in files), filteredByIgnore=scan['filteredByIgnore'],
                               byLanguage=scan['stats']['byLanguage'], byCategory=scan['stats']['byCategory'])

        current = 'imports'
        import_path = directory / 'imports.json'
        imports = invoke('imports', ['extract_import_map', write(directory / 'import-input.json', dict(projectRoot=str(subject), files=files)), import_path], import_path)
        check(isinstance(imports.get('importMap'), dict) and imports.get('stats', {}).get('filesScanned') == len(files))
        check(set(imports['importMap']) == set(paths))
        check(all(isinstance(targets, list) and set(targets) <= set(paths) for targets in imports['importMap'].values()))

        current = 'batching'
        batch_path = directory / 'batches.json'
        combined = {**scan, 'importMap': imports['importMap']}
        batches = invoke('batching', ['compute_batches', subject, '--scan-result', write(directory / 'combined-scan.json', combined), '--output', batch_path], batch_path)
        check(isinstance(batches.get('batches'), list))
        grouped = [file['path'] for batch in batches['batches'] for file in batch['files']]
        check(sorted(grouped) == sorted(paths))

        current = 'structure'
        start = time.monotonic()
        lookup = {f['path']: f for f in files}
        metrics, results = [], []
        first_error = None
        jobs = []
        for index, batch in enumerate(batches['batches']):
            name = f'structure-{index:06}'
            input_path = write(directory / (name + '-input.json'), dict(projectRoot=str(subject),
                batchFiles=batch['files'], batchImportData=batch['batchImportData'], includeCoverage=True))
            jobs.append((name, input_path, directory / (name + '.json'), [f['path'] for f in batch['files']]))

        def structure_job(job):
            name, input_path, output, expected = job
            try:
                metric = worker(command + ['extract_structure', str(input_path), str(output)], directory, name, stop, timeout)
            except StageError as error:
                # Continue accounting for completed workers without exposing raw logs.
                metric = error.metric
                if not output.exists():
                    return metric, None, expected, error.code
            try:
                value = read(output)
                metric['outputBytes'] = output.stat().st_size
                check(value.get('scriptCompleted') is True and isinstance(value.get('coverage'), list))
                check(sorted(e['path'] for e in value['coverage']) == sorted(expected))
                check(isinstance(value.get('results'), list) and value.get('filesAnalyzed') == len(value['results']))
                check(sorted([e['path'] for e in value['results']] + [e['path'] for e in value.get('filesUnreadable', [])]) == sorted(expected))
                for entry in value['coverage']:
                    check(entry['structure'] in ('succeeded', 'unsupported', 'failed', 'unreadable'))
                    check(entry['callGraph'] in ('succeeded', 'unsupported', 'failed', 'unreadable'))
                metric['outputDigest'] = digest(value)
                return metric, value, expected, metric['error']
            except (StageError, KeyError, TypeError, ValueError):
                metric.update(status='failed', error='invalid-output')
                return metric, None, expected, 'invalid-output'

        with ThreadPoolExecutor(max_workers=report['configuration']['concurrency']) as executor:
            # map returns in deterministic batch order, including failures.
            for metric, value, expected, error in executor.map(structure_job, jobs):
                if metric:
                    metrics.append(metric)
                if error:
                    first_error = first_error or error
                    coverage['invalidOutputs'] += int(error == 'invalid-output')
                if value is None:
                    continue
                results.extend(value['results'])
                for entry in value['coverage']:
                    key = {'succeeded': 'structureSucceeded', 'unsupported': 'structureUnsupported',
                           'failed': 'parseFailed', 'unreadable': 'unreadable'}[entry['structure']]
                    coverage[key] += 1
                    if entry['callGraph'] == 'succeeded':
                        coverage['callGraphSupported'] += 1
                    elif entry['callGraph'] == 'unsupported':
                        coverage['callGraphUnsupported'] += 1
        report['stages']['structure'] = combined_metrics(metrics, (time.monotonic() - start) * 1000)
        for key, code in [('structureUnsupported', 'unsupported-structure'), ('callGraphUnsupported', 'unsupported-call-graph'), ('parseFailed', 'parse-failed'), ('invalidOutputs', 'invalid-output')]:
            warn(report, 'structure', code, coverage[key])
        if first_error or coverage['parseFailed'] or coverage['unreadable']:
            raise StageError(first_error or 'parse-failed')
        check(coverage['structureSucceeded'] + coverage['structureUnsupported'] == len(files))
        check(input_identity(subject, files) == initial)
        results.sort(key=lambda f: f['path'])
        semantic = dict(scan=scan, imports=imports, batching=batches, structure=results)
        # Native batch outputs include projectRoot. Exclude it from public digests.
        def normalize(value):
            if isinstance(value, dict):
                return {k: normalize(v) for k, v in value.items() if k not in ('projectRoot',)}
            if isinstance(value, list):
                return [normalize(v) for v in value]
            return value
        report['stages']['batching']['outputDigest'] = digest(normalize(batches))
        report['stages']['structure']['outputDigest'] = digest(results)
        report['determinism']['outputDigest'] = digest(normalize(semantic))
        report['status'] = 'degraded' if report['warningCount'] else 'ok'
        report['error'] = None
    except (StageError, KeyError, TypeError, ValueError, OSError) as error:
        code = error.code if isinstance(error, StageError) else 'invalid-output'
        if code == 'input-unreadable':
            coverage['unreadable'] += error.count
        if code == 'invalid-output':
            coverage['invalidOutputs'] += 1
        if current in report['stages']:
            report['stages'][current].update(status='failed', error=code)
        report.update(status='failed', error=code)
