#!/usr/bin/env python3
"""Run the documented native Job recipes against the release quickstart CSV."""

import argparse
import csv
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def csv_rows(path):
    with path.open(encoding='utf-8', newline='') as file:
        return list(csv.reader(file, strict=True))


class JobRecipes(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.root = Path(work.name)
        fixture = self.root / 'quickstart/customers.csv'
        fixture.parent.mkdir()
        shutil.copyfile(FIXTURE, fixture)
        self.header, *self.source = csv_rows(fixture)
        self.assertEqual(len(self.source), 12)

    def test_saved_quickstart_job_produces_the_documented_files(self):
        shutil.copyfile(QUICKSTART_JOB, self.root / 'quickstart/job.json')
        result = subprocess.run(
            [BINARY, 'run', '--config', 'quickstart/job.json', '--yes'],
            cwd=self.root, capture_output=True, encoding='utf-8', timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = self.root / 'quickstart-output'
        job, *chunks = map(json.loads, (output / 'manifest.jsonl').read_text(encoding='utf-8').splitlines())
        self.assertEqual(job['config']['limits']['rows'], 5)
        self.assertEqual([(chunk['path'], chunk['rows']) for chunk in chunks],
                         [(f'part-{index:08}.csv', rows) for index, rows in enumerate((5, 5, 2), 1)])
        self.assertEqual([row for chunk in chunks for row in csv_rows(output / chunk['path'])[1:]],
                         self.source)

    def run_recipe(self, destination, groups):
        commands = [shlex.split(line) for line in re.findall(
            r'^```sh\n(\./chopper run [^\n]+)\n```$',
            (ROOT / 'docs/job-recipes.md').read_text(encoding='utf-8'), re.M,
        )]
        commands = [args for args in commands if args[args.index('--output') + 1] == destination]
        self.assertEqual(len(commands), 1, f'Expected one documented command for {destination}')
        result = subprocess.run([BINARY, *commands[0][1:]], cwd=self.root,
                                capture_output=True, encoding='utf-8', timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = self.root / destination
        job, *chunks = map(json.loads, (output / 'manifest.jsonl').read_text(encoding='utf-8').splitlines())
        self.assertEqual(job['type'], 'job')
        self.assertEqual(set(output.iterdir()),
                         {output / 'manifest.jsonl', *(output / c['path'] for c in chunks)})

        all_rows = []
        for chunk in chunks:
            path = output / chunk['path']
            header, *rows = csv_rows(path)
            self.assertEqual(chunk['type'], 'output')
            self.assertEqual(header, self.header)
            self.assertEqual(chunk['rows'], len(rows))
            self.assertEqual(chunk['csv_bytes'], path.stat().st_size)
            self.assertEqual(chunk['stored_bytes'], chunk['csv_bytes'])
            all_rows.extend(rows)
        self.assertCountEqual(all_rows, self.source)
        self.assertEqual(json.loads(result.stdout), {
            'status': 'published', 'rows': 12, 'columns': 4,
            'groups': groups, 'output_files': len(chunks),
            'output_csv_bytes': sum(chunk['csv_bytes'] for chunk in chunks),
        })
        return output, job['config'], chunks

    def test_upload_chunks_preserve_order_and_enforce_both_caps(self):
        output, config, chunks = self.run_recipe('recipe-upload', groups=1)
        self.assertEqual((config['limits']['rows'], config['limits']['bytes']), (2, 85))
        self.assertEqual([chunk['rows'] for chunk in chunks], [1, 1, 2, 2, 2, 2, 2])
        self.assertTrue(all(chunk['csv_bytes'] <= 85 for chunk in chunks))
        self.assertEqual([row for chunk in chunks for row in csv_rows(output / chunk['path'])[1:]],
                         self.source)

    def test_balanced_export_has_exact_file_count_and_preserves_order(self):
        output, _, chunks = self.run_recipe('recipe-balanced', groups=3)
        self.assertEqual([chunk['rows'] for chunk in chunks], [4, 4, 4])
        self.assertEqual([row for chunk in chunks for row in csv_rows(output / chunk['path'])[1:]],
                         self.source)

    def test_partition_preserves_exact_country_membership(self):
        output, _, chunks = self.run_recipe('recipe-country', groups=3)
        self.assertEqual(len(chunks), 3)
        self.assertEqual({chunk['lineage'][0]['values'][0]: chunk['rows'] for chunk in chunks},
                         {'DE': 3, 'GB': 4, 'US': 5})
        for chunk in chunks:
            country = chunk['lineage'][0]['values'][0]
            self.assertEqual(chunk['lineage'], [{'operation': 0, 'values': [country]}])
            self.assertEqual(csv_rows(output / chunk['path'])[1:],
                             [row for row in self.source if row[1] == country])

    def test_exact_allocation_preserves_quotas_and_order_within_each_group(self):
        output, _, chunks = self.run_recipe('recipe-experiment', groups=2)
        self.assertEqual(len(chunks), 2)
        self.assertEqual({chunk['lineage'][0]['allocation']: chunk['rows'] for chunk in chunks},
                         {'treatment': 9, 'control': 3})
        for chunk in chunks:
            group = chunk['lineage'][0]['allocation']
            self.assertEqual(chunk['lineage'], [{'operation': 0, 'allocation': group}])
            rows = csv_rows(output / chunk['path'])[1:]
            self.assertEqual(rows, sorted(rows, key=self.source.index))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('--quickstart', type=Path, help='Use the quickstart folder of an extracted release')
    args = parser.parse_args()
    BINARY = args.binary.resolve(strict=True)
    FIXTURE = (args.quickstart or ROOT / 'examples') / 'customers.csv'
    QUICKSTART_JOB = args.quickstart / 'job.json' if args.quickstart else ROOT / 'examples/quickstart-job.json'
    unittest.main(argv=[__file__])
