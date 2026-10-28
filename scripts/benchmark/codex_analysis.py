#!/usr/bin/env python3
"""Run the packaged Understand Anything skill with explicit Codex model settings."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def command(subject, plugin, run_dir):
    prompt = (
        f'Read {plugin}/HOSTS.md and {plugin}/skills/understand/SKILL.md. '
        f'Execute the understand skill for {subject} with --all --full --no-auto-update. '
        'This is an explicitly authorized full benchmark run. Use the default ignore rules; '
        'the initial ignore review and inclusion of all detected parts are preapproved. '
        'Use the packaged binary and preconfigured language assets; do not rebuild or download. '
        'Complete every analysis phase and write the merged knowledge graph and metadata. '
        'Do not change source files or install software. Do not run rm commands. '
        'Use only this packaged plugin, not a global installation. '
        'Stop and report any actual runtime or authentication failure.'
    )
    return ['codex', 'exec', '--ignore-user-config', '--model', 'gpt-6.1-sol',
            '--config', 'model_reasoning_effort="medium"', '--config', 'service_tier="default"',
            '--config', 'approval_policy="never"', '--sandbox', 'workspace-write',
            '--skip-git-repo-check', '--cd', str(subject), '--add-dir', str(run_dir),
            '--json', '--output-last-message', str(run_dir / 'codex-final-message.txt'), prompt]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('subject', type=Path)
    parser.add_argument('plugin', type=Path)
    parser.add_argument('run_dir', type=Path)
    args = parser.parse_args(argv)
    subject, plugin, run_dir = args.subject.resolve(), args.plugin.resolve(), args.run_dir.resolve()
    if not subject.is_relative_to(run_dir) or not (plugin / 'skills/understand/SKILL.md').is_file():
        parser.error('requires a run-local subject snapshot and the rebuilt plugin payload')
    skills = subject / '.agents/skills'
    skills.mkdir(parents=True)
    for skill in (plugin / 'skills').iterdir():
        if (skill / 'SKILL.md').is_file():
            (skills / skill.name).symlink_to(skill, target_is_directory=True)
    events = run_dir / 'codex-events.jsonl'
    with events.open('w') as output:
        result = subprocess.run(command(subject, plugin, run_dir), stdout=output)
    usage = {}
    for line in events.read_text().splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('type') == 'turn.completed':
            for key, value in (event.get('usage') or {}).items():
                if isinstance(value, int):
                    usage[key] = usage.get(key, 0) + value
    (run_dir / 'codex-usage.json').write_text(json.dumps({'model': 'gpt-6.1-sol', 'reasoningEffort': 'medium',
                                                       'serviceTierRequested': 'default', 'usageReportedByCli': usage or None}, indent=2) + '\n')
    if result.returncode:
        return result.returncode
    graph_path = subject / '.ua/knowledge-graph.json'
    try:
        graph = json.loads(graph_path.read_text())
        if not isinstance(graph.get('nodes'), list) or not isinstance(graph.get('edges'), list):
            raise ValueError('missing graph arrays')
    except (OSError, ValueError) as error:
        print(f'Codex did not produce a valid merged graph: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
