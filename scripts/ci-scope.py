#!/usr/bin/env python3
"""Conservative path routing shared by PR and main CI; unknown paths run all jobs."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

JOB_IDS = {'native': 'native', 'features': 'surviving-features', 'core': 'portable-core',
           'browser': 'browser', 'evidence': 'evidence', 'tooling': 'tooling'}
JOBS = tuple(JOB_IDS)
PLATFORM_JOBS = {'all': JOBS, 'linux': JOBS, 'windows': ('native', 'tooling'), 'macos': ('native',)}
TOOLS = {'scripts/windows-native.py', 'scripts/test-windows-native.py',
         'scripts/package-release.py', 'scripts/test-package-release.py',
         'docs/releases/native-usage.txt',
         'docs/releases/native-quickstart.txt', 'examples/quickstart-job.json',
         'scripts/graphify.sh', 'scripts/graphify.ps1', 'RTK.md', '.codex/hooks.json'}
EVIDENCE_SCRIPTS = {'scripts/benchmark-catalog.py', 'scripts/test-benchmark-catalog.py',
                    'scripts/performance-registry.py', 'scripts/test-performance-registry.py',
                    'scripts/evidence-documents.py', 'scripts/performance-narratives.py',
                    'scripts/test-performance-narratives.py', 'scripts/evidence-views.py',
                    'scripts/test-evidence-views.py',
                    'scripts/evidence-resolver.py', 'scripts/test-evidence-resolver.py',
                    'scripts/evidence-migration.py', 'scripts/test-evidence-migration.py',
                    'scripts/requirements-evidence.txt', 'scripts/audit-strategy-evidence.py',
                    'scripts/summarize-performance-decisions.py'}


def classify(paths, full=False, platform='all'):
    selected = set(JOBS) if full else set()
    for path in paths:
        if path == 'docs/releases/native-usage.txt':
            selected.add('browser')
        if path.startswith('scripts/hosted_picker/') or path in {
                'scripts/test-hosted-qualification.py', 'scripts/browser-hosted-qualification.test.mjs'}:
            selected.update(('browser', 'tooling'))
            continue
        # These helpers also own tooling controls; retain their browser routing below.
        if path in {'scripts/browser-artifacts.mjs', 'scripts/browser-small-runner.py',
                    'scripts/browser-small-windows.py', 'scripts/test-browser-small-runner.py',
                    'scripts/build-browser.mjs', 'scripts/build-browser.sh', 'scripts/browser-build.test.mjs'}:
            selected.add('tooling')
        if path in {'Cargo.toml', 'Cargo.lock', '.gitattributes', '.gitignore',
                    'scripts/ci-scope.py', 'scripts/test-ci-scope.py',
                    'scripts/local-ci.py', 'scripts/test-local-ci.py'} or path.startswith('.github/'):
            selected.update(JOBS)
        elif path in TOOLS:
            selected.add('tooling')
        elif path in EVIDENCE_SCRIPTS:
            selected.add('evidence')
        elif path.startswith(('schemas/', 'scripts/fixtures/release-upgrade/')) or path in {
                'docs/job-json.md', 'scripts/test-job-schema.py', 'scripts/requirements-job-schema.txt',
                'docs/cli-reference.md', 'docs/job-recipes.md', 'scripts/cli-reference.py',
                'scripts/test-job-recipes.py', 'docs/native-manifest.md', 'examples/verify_manifest.py',
                'scripts/test-native-manifest.py', 'docs/compatibility.md', 'scripts/test-release-upgrade.py'}:
            selected.add('native')
        elif path.endswith('.md') and not path.startswith('docs/'):
            pass
        elif path.startswith(('crates/', 'vendor/')):
            selected.update(('native', 'features', 'browser'))
            if path.startswith('crates/chopper-core/'):
                selected.add('core')
        elif path.startswith('ui/'):
            selected.update(('native', 'browser'))
        elif path.startswith('docs/'):
            if path.startswith(('docs/benchmarks/', 'docs/history/', 'docs/evidence-', 'docs/performance/')) or path in {
                'docs/performance.md', 'docs/performance-overview.md', 'docs/performance-decisions.md',
                'docs/strategy-review.md', 'docs/specification.md', 'docs/pipeline-rewrites.md',
                'docs/validation.md', 'docs/validation-index.md', 'docs/direct-execution.md', 'docs/resource-policy-research.md',
                'docs/csv-ingestion-techniques.md'}:
                selected.add('evidence')
        elif path in {'scripts/graph-codec-fixtures.py', 'scripts/benchmark-execution-graph.mjs',
                      'scripts/analyze-execution-graph.py', 'scripts/test-execution-graph-analysis.py',
                      'scripts/extend-execution-graph-analysis.py', 'scripts/final-execution-graph-analysis.py',
                      'scripts/execution_graph_statistics.py',
                      'scripts/test-execution-graph-extension.py'} or path.startswith(('scripts/build-browser', 'scripts/test-browser', 'scripts/build-hosted',
                              'scripts/serve-hosted', 'scripts/browser-', 'scripts/probe-browser')):
            selected.add('browser')
        elif path.endswith('.md') or path == 'LICENSE' or path.startswith('.agents/skills/'):
            pass
        else:
            selected.update(JOBS)
    return {job: job in selected and job in PLATFORM_JOBS[platform] for job in JOBS}


def changed_paths(base, head):
    # Both names of a rename/copy must participate in routing. NUL delimiting
    # preserves spaces and newlines; no GitHub API file-count truncation applies.
    data = subprocess.check_output(['git', 'diff', '--no-renames', '--name-only', '-z', base, head, '--'])
    return [name.decode('utf-8', errors='surrogateescape') for name in data.split(b'\0') if name]


def failed_jobs(results):
    failed = {name for name, value in results.items() if value['result'] not in ('success', 'skipped')}
    changes = results.get('changes', {})
    flags = changes.get('outputs', {})
    if changes.get('result') != 'success' or any(flags.get(flag) not in ('true', 'false') for flag in JOBS):
        failed.add('changes')
    for flag, job in JOB_IDS.items():
        if flags.get(flag) == 'true' and results.get(job, {}).get('result') != 'success':
            failed.add(job)
    return sorted(failed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base')
    parser.add_argument('--head', default='HEAD')
    parser.add_argument('--full', action='store_true')
    parser.add_argument('--platform', choices=tuple(PLATFORM_JOBS), default='all')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--check-results', action='store_true', help='Validate the RESULTS needs-context environment')
    args = parser.parse_args()
    if args.check_results:
        failed = failed_jobs(json.loads(os.environ['RESULTS']))
        print('Failed, cancelled or unexpectedly skipped jobs:', failed)
        return int(bool(failed))
    if not args.full and not args.base:
        parser.error('--base is required unless --full')
    paths = [] if args.full else changed_paths(args.base, args.head)
    result = classify(paths, full=args.full, platform=args.platform)
    print(json.dumps({'paths': paths, 'jobs': result}, indent=2))
    if args.output:
        with args.output.open('a', encoding='utf-8') as output:
            for job, enabled in result.items():
                output.write(f'{job}={str(enabled).lower()}\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
