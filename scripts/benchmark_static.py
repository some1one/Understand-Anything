#!/usr/bin/env python3
"""Report saved analysis statistics without running an engine or reading source."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sys


def read_object(path, optional=False):
    if optional and not path.exists():
        return None
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError(f'{path.name}: expected a JSON object')
    return data


def records(data, key):
    value = data.get(key)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f'{key}: expected an array of objects')
    return value


def counts(items, key):
    return dict(sorted(Counter(str(item.get(key) or 'unknown') for item in items).items()))


def summarize(directory, total_seconds=None, time_scope='unknown'):
    if total_seconds is not None and (not math.isfinite(total_seconds) or total_seconds <= 0):
        raise ValueError('total seconds must be a finite positive number')
    if time_scope not in ('unknown', 'full', 'incremental'):
        raise ValueError('invalid time scope')
    graph = read_object(directory / 'knowledge-graph.json')
    nodes, edges = records(graph, 'nodes'), records(graph, 'edges')
    layers = records(graph, 'layers') if 'layers' in graph else []
    meta = read_object(directory / 'meta.json', optional=True) or {}
    config = read_object(directory / 'config.json', optional=True) or {}
    scan = read_object(directory / 'intermediate/scan-result.json', optional=True)
    files = records(scan, 'files') if scan is not None else None
    warnings = [
        'Statistics describe saved artifacts; current source freshness and semantic accuracy are not verified.',
        'CPU, memory, stage timings, tokens and cost cannot be recovered from these artifacts.',
    ]
    ids = [node.get('id') for node in nodes]
    if any(not isinstance(value, str) or not value for value in ids):
        raise ValueError('every graph node must have a nonempty string id')
    id_set = set(ids)
    for edge in edges:
        if not isinstance(edge.get('source'), str) or not isinstance(edge.get('target'), str):
            raise ValueError('every edge must have string source and target IDs')
    paths = {node['filePath'] for node in nodes if isinstance(node.get('filePath'), str) and node['filePath']}
    file_nodes = [node for node in nodes if node.get('type') == 'file']
    scan_stats = None
    if files is not None:
        scan_paths = [item.get('path') for item in files]
        if any(not isinstance(path, str) or not path for path in scan_paths):
            raise ValueError('every scanned file must have a nonempty string path')
        if len(set(scan_paths)) != len(scan_paths):
            raise ValueError('scan contains duplicate file paths')
        lines = [item.get('sizeLines') for item in files]
        valid_lines = all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in lines)
        scan_stats = {
            'files': len(files),
            'lines': sum(lines) if valid_lines else None,
            'filesByLanguage': counts(files, 'language'),
            'filesByCategory': counts(files, 'fileCategory'),
            'filesWithoutGraphPath': len(set(scan_paths) - paths),
            'graphPathsOutsideScan': len(paths - set(scan_paths)),
        }
        warnings.append('The saved scan may have a different scope or revision from the merged graph; path differences are informational.')
        if not valid_lines:
            warnings.append('Incomplete or invalid saved line counts; line totals and line throughput are unavailable.')
    else:
        warnings.append('No saved intermediate/scan-result.json; scan totals and throughput are unavailable.')
    throughput = {'filesPerMinute': None, 'linesPerSecond': None}
    if total_seconds is not None:
        if time_scope == 'full' and scan_stats is not None:
            throughput['filesPerMinute'] = scan_stats['files'] * 60 / total_seconds
            if scan_stats['lines'] is not None:
                throughput['linesPerSecond'] = scan_stats['lines'] / total_seconds
            warnings.append('Throughput assumes the supplied time covers exactly the full saved scan, including any orchestration or LLM work in that time.')
        else:
            warnings.append('Snapshot throughput is suppressed unless TIME_SCOPE=full and a saved scan is available.')
    project = graph.get('project') or {}
    if not isinstance(project, dict):
        raise ValueError('project: expected an object')
    dangling = sum(edge['source'] not in id_set or edge['target'] not in id_set for edge in edges)
    connected = {endpoint for edge in edges for endpoint in (edge['source'], edge['target']) if endpoint in id_set}
    valid_edges = [edge for edge in edges if edge['source'] in id_set and edge['target'] in id_set]
    incoming = Counter(edge['target'] for edge in valid_edges)
    outgoing = Counter(edge['source'] for edge in valid_edges)
    by_id = {node['id']: node for node in nodes}

    def hubs(counter):
        return [{'id': key, 'name': by_id[key].get('name', key), 'relationships': count}
                for key, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:10]]

    return {
        'schemaVersion': '1.0.0',
        'reportType': 'saved-analysis-statistics',
        'project': {'name': project.get('name'), 'graphCommit': project.get('gitCommitHash'),
                    'analyzedAt': project.get('analyzedAt'), 'metadataCommit': meta.get('gitCommitHash'),
                    'metadataAnalyzedFiles': meta.get('analyzedFiles'), 'includedParts': config.get('includedParts')},
        'timing': {'totalSeconds': total_seconds, 'source': 'user-supplied' if total_seconds is not None else None,
                   'scope': time_scope},
        'scan': scan_stats,
        'graph': {'nodes': len(nodes), 'edges': len(edges), 'layers': len(layers),
                  'fileNodes': len(file_nodes), 'distinctFilePaths': len(paths),
                  'nodesByType': counts(nodes, 'type'), 'edgesByType': counts(edges, 'type'),
                  'isolatedNodes': len(id_set - connected),
                  'topIncomingRelationships': hubs(incoming), 'topOutgoingRelationships': hubs(outgoing)},
        'consistency': {'duplicateNodeIds': len(ids) - len(id_set), 'danglingEdges': dangling},
        'throughput': throughput,
        'warnings': warnings,
    }


def markdown(report):
    def show(value):
        return 'unavailable' if value is None else (f'{value:,.3f}' if isinstance(value, float) else str(value))

    lines = ['# Saved analysis statistics', '',
             'Counts reflect saved artifacts. Relationship hubs include all relationship types.', '',
             '| Metric | Value |', '| --- | --- |']
    metrics = [('Project', report['project']['name']), ('Graph commit', report['project']['graphCommit']),
               ('Analyzed at', report['project']['analyzedAt']),
               ('Total seconds (user-supplied)', report['timing']['totalSeconds']), ('Time scope', report['timing']['scope'])]
    if report['scan'] is not None:
        metrics += [('Scanned files', report['scan']['files']), ('Scanned lines', report['scan']['lines']),
                    ('Scanned files without graph path', report['scan']['filesWithoutGraphPath']),
                    ('Graph paths outside scan', report['scan']['graphPathsOutsideScan'])]
    metrics += [(key, report['graph'][key]) for key in ('nodes', 'edges', 'layers', 'fileNodes', 'distinctFilePaths', 'isolatedNodes')]
    metrics += list(report['consistency'].items()) + list(report['throughput'].items())

    def escape(value):
        return show(value).replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')

    lines += [f'| {key} | {escape(value)} |' for key, value in metrics]
    breakdowns = [('Nodes by type', report['graph']['nodesByType']), ('Relationships by type', report['graph']['edgesByType'])]
    if report['scan'] is not None:
        breakdowns += [('Files by language', report['scan']['filesByLanguage']), ('Files by category', report['scan']['filesByCategory'])]
    for title, values in breakdowns:
        lines += ['', f'## {title}', '', '| Type | Count |', '| --- | ---: |']
        lines += [f'| {escape(key)} | {value} |' for key, value in values.items()]
    for key, title in [('topIncomingRelationships', 'Most incoming relationships'), ('topOutgoingRelationships', 'Most outgoing relationships')]:
        lines += ['', f'## {title}', '', '| Node | Count |', '| --- | ---: |']
        lines += [f"| {escape(item['name'])} | {item['relationships']} |" for item in report['graph'][key]]
    lines += ['', '## Interpretation', ''] + ['- ' + warning for warning in report['warnings']]
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ua_dir', type=Path, help='existing .ua artifact directory')
    parser.add_argument('--total-seconds', default='', help='positive elapsed wall-clock seconds for the original analysis')
    parser.add_argument('--time-scope', choices=('unknown', 'full', 'incremental'), default='unknown')
    parser.add_argument('--format', choices=('markdown', 'json'), default='markdown')
    args = parser.parse_args(argv)
    try:
        seconds = float(args.total_seconds) if args.total_seconds else None
        report = summarize(args.ua_dir, seconds, args.time_scope)
    except (OSError, ValueError) as error:
        print(f'Cannot summarize saved analysis: {error}', file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, allow_nan=False) if args.format == 'json' else markdown(report), end='\n' if args.format == 'json' else '')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
