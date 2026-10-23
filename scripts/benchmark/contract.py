"""Version 2 Rust benchmark contract; public fields contain no source or paths."""
import hashlib
import json
import uuid

VERSION = '2.0.0'
SCHEMA = 'large-repo-report-2.0.0.schema.json'
STAGES = ('scan', 'imports', 'batching', 'structure')
SAMPLE_LIMIT = 5


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def new_report():
    return {
        'schemaVersion': VERSION, 'schemaUrl': SCHEMA, 'pairId': str(uuid.uuid4()),
        'mode': 'rust-deterministic', 'status': 'failed',
        'run': {'startedAt': None, 'finishedAt': None, 'durationMs': None},
        'tool': {'commit': None, 'dirty': None, 'packageVersion': None, 'binaryDigest': None},
        'subject': {'commit': None, 'dirty': None},
        'environment': {'os': None, 'release': None, 'arch': None, 'cpuModel': None,
                        'logicalCores': None, 'totalMemoryBytes': None, 'rustc': None,
                        'parserVersion': None, 'parserAssetsDigest': None, 'dictionary': 'unused'},
        'configuration': {'concurrency': 1, 'buildMode': 'release',
                          'parserCache': 'cold-process; warm-within-batch',
                          'filesystemCache': 'potentially-cold', 'ignoreRules': None},
        'scale': None, 'stages': {}, 'coverage': None, 'determinism': None,
        'warnings': [], 'warningCount': 0, 'warningsTruncated': False,
        'secondaryErrors': [], 'error': 'not-started',
    }
