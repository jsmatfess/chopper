#!/usr/bin/env python3
"""Small synthetic controls only: no builds, Chopper execution or speed samples."""
import copy
import csv
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v = load('verify-shuffle-swarm')
b = load('bench-shuffle-swarm')


class Controls(unittest.TestCase):
    def test_quota_ties_and_zeros(self):
        self.assertEqual(v.quotas(1, [50, 0, 50]), [1, 0, 0])
        self.assertEqual(v.quotas(3, [50, 0, 50]), [2, 0, 1])
        self.assertEqual(v.quotas(0), [0, 0, 0, 0])
        self.assertEqual(v.quotas(12003), [2041, 0, 3961, 6001])
        self.assertEqual(v.quotas(6), [1, 0, 2, 3])

    def test_recipes_and_alternation(self):
        self.assertEqual(list(v.recipes()), ['exact-fit', 'exact-spill', 'exact-many', 'exact-wide',
                         'exact-downstream', 'mixed-fit', 'mixed-retained', 'mixed-wide', 'mixed-upstream',
                         'mixed-downstream', 'adaptive-fit', 'adaptive-spill', 'balanced-fit', 'balanced-spill', 'combined-fit'])
        self.assertEqual([b.order(i) for i in range(-1, 3)],
                         [('candidate', 'baseline'), ('baseline', 'candidate'),
                          ('candidate', 'baseline'), ('baseline', 'candidate')])
        r = v.recipes()['exact-many']
        groups, stages, constraints = v.expected(r)
        self.assertEqual(stages[0], dict(operation=1, input_groups=1, output_groups=257,
                         smallest_group=100, largest_group=101, empty_groups=0))
        self.assertEqual(len(groups), 1028)
        self.assertEqual(constraints[v.key([dict(operation=0, part=1)])], set(range(101)))
        self.assertEqual(sum(g[0] for g in groups), 25703)
        downstream, _, _ = v.expected(v.recipes()['exact-downstream'])
        self.assertEqual([g[0] for g in downstream], [4251, 4250, 0, 0, 8251, 8250, 12501, 12500])

    def sample(self, root):
        recipe = copy.deepcopy(v.recipes()['exact-many'])
        recipe.update(rows=11, operations=[{'type': 'balanced', 'files': 2},
                       {'type': 'shuffle', 'strategy': 'uniform'}, recipe['operations'][-1]])
        job = b.make_job(recipe, root / 'input.csv', root)
        records = []
        # Hand-specified balanced ranges and exact counts, independent of expected().
        for part, ids, counts in [(1, list(range(6)), [1, 0, 2, 3]),
                                  (2, list(range(6, 11)), [1, 0, 2, 2])]:
            offset = 0
            for name, count in zip(v.NAMES, counts):
                path = f'{len(records):03d}.csv'
                with (root / path).open('x', newline='', encoding='utf-8') as stream:
                    writer = csv.writer(stream, lineterminator='\n')
                    writer.writerow(v.header(recipe))
                    for identity in ids[offset:offset + count]:
                        writer.writerow(v.fields(recipe, identity))
                offset += count
                size = (root / path).stat().st_size
                records.append(dict(type='output', path=path, rows=count, csv_bytes=size,
                                    stored_bytes=size, compressed_target_exceeded=False,
                                    lineage=[dict(operation=0, part=part), dict(operation=2, allocation=name)]))
        analysis = dict(rows=11, columns=3, header=v.header(recipe), groups=8, workers=1,
                        memory_budget_bytes=32 * 1024**2, output_files=8,
                        output_csv_bytes=sum(r['csv_bytes'] for r in records), stages=[
                            dict(operation=1, input_groups=1, output_groups=2, smallest_group=5, largest_group=6, empty_groups=0),
                            dict(operation=2, input_groups=2, output_groups=2, smallest_group=5, largest_group=6, empty_groups=0),
                            dict(operation=3, input_groups=2, output_groups=8, smallest_group=0, largest_group=3, empty_groups=2)])
        return recipe, job, analysis, [dict(type='job', schema_version=1, config=job, analysis=analysis), *records]

    def check_sample(self, mutation=None, message=None):
        with tempfile.TemporaryDirectory(prefix='chopper-swarm-selfcheck-') as directory:
            root = Path(directory)
            recipe, job, analysis, records = self.sample(root)
            if mutation:
                mutation(root, analysis, records)
            (root / 'manifest.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in records))
            if message:
                with self.assertRaisesRegex(ValueError, message):
                    v.verify(root, recipe, job, analysis)
            else:
                result = v.verify(root, recipe, job, analysis)
                self.assertEqual(result['rows'], 11)
                self.assertEqual(len(result['output_files']), 8)

    def test_valid(self):
        self.check_sample()

    def test_canonical_defaults(self):
        self.assertTrue(v.matches_config({'groups': [dict(name='x', percent='100')], 'strata': []},
                                         {'groups': [dict(name='x', percent='100')]}))
        self.assertFalse(v.matches_config({'rows': 1}, {'rows': 2}))
        self.assertFalse(v.matches_config([1, 2], [1]))

    def test_missing_named_empty(self):
        self.check_sample(lambda p, a, r: r.pop(2), 'empty named group')

    def test_path_escape(self):
        self.check_sample(lambda p, a, r: r[1].update(path='../escape.csv'), 'unsafe output path')

    def test_manifest_bytes(self):
        self.check_sample(lambda p, a, r: r[1].update(csv_bytes=1), 'byte metadata')

    def test_stage_index(self):
        self.check_sample(lambda p, a, r: a['stages'][1].update(operation=9), 'logical stages')

    def test_parent_membership(self):
        # Exchange equal-sized files across parents: conservation/quotas still hold.
        def mutate(root, analysis, records):
            first, second = root / records[1]['path'], root / records[5]['path']
            data = first.read_bytes()
            first.write_bytes(second.read_bytes())
            second.write_bytes(data)
            for record in (records[1], records[5]):
                record.update(csv_bytes=(root / record['path']).stat().st_size,
                              stored_bytes=(root / record['path']).stat().st_size)
        self.check_sample(mutate, 'parent membership')

    def test_quota_and_fields(self):
        def mutate(root, analysis, records):
            # A source ID is valid but its fields are changed; metadata is kept honest.
            path = root / records[1]['path']
            path.write_text(path.read_text().replace('é', 'a'))
            records[1].update(csv_bytes=path.stat().st_size, stored_bytes=path.stat().st_size)
        self.check_sample(mutate, 'field corruption')
        self.check_sample(lambda p, a, r: r[1]['lineage'][-1].update(allocation='fifty'), 'quota mismatch|group order')

    def test_provenance_rejects_changed_artifact(self):
        with tempfile.TemporaryDirectory(prefix='chopper-swarm-provenance-') as directory:
            root = Path(directory)
            binary = root / 'fake-binary'
            binary.write_bytes(b'not an executable')
            runner = root / 'runner.json'
            runner.write_text('{}')
            source = root / 'source.json'
            source.write_text(json.dumps(dict(source_head='fake-head', captured_after_source_freeze=True,
                git_status='synthetic', files={'scripts/verify-shuffle-swarm.py': v.sha(v.__file__)})))
            toolchain = root / 'toolchain.json'
            toolchain.write_text('{}')
            for path in (source, toolchain):
                path.chmod(0o444)
            manifest = root / 'artifact-manifest.json'
            manifest.write_text(json.dumps(dict(source_head='fake-head', features=[],
                artifacts=[dict(path=str(binary), sha256=v.sha(binary), size=binary.stat().st_size)],
                runner_receipt=str(runner), runner_receipt_sha256=v.sha(runner), plan_sha256='test',
                provenance=[dict(path=str(path), sha256=v.sha(path), role=role)
                    for path, role in ((source, 'source'), (toolchain, 'toolchain'))])))
            manifest.chmod(0o444)
            receipt = b.provenance(binary, manifest, root / 'captured', candidate=True)
            self.assertEqual(receipt['binary_sha256'], v.sha(binary))
            binary.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'differs from build artifact'):
                b.provenance(binary, manifest, root / 'rejected', candidate=True)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux GNU time and POSIX process groups required')
    def test_process_receipts_with_fakes(self):
        with tempfile.TemporaryDirectory(prefix='chopper-swarm-process-') as directory:
            root = Path(directory)
            fail = root / 'fail'
            fail.mkdir()
            result = b.run_process([sys.executable, '-c', 'import sys; print("retained"); sys.exit(7)'], fail, 5)
            self.assertEqual(result['exit_code'], 7)
            self.assertIn('retained', (fail / 'stdout').read_text())
            self.assertTrue((fail / 'process.json').is_file())
            timeout = root / 'timeout'
            timeout.mkdir()
            result = b.run_process([sys.executable, '-c', 'import time; time.sleep(10)'], timeout, 0.05)
            self.assertTrue(result['timed_out'])
            self.assertNotEqual(result['exit_code'], 0)
            self.assertTrue((timeout / 'stderr').is_file())

    def test_wide_parser(self):
        recipe = v.recipes()['mixed-wide']
        row = v.fields(recipe, recipe['rows'] - 7)
        self.assertEqual(len(row), 33)
        self.assertLess(len(','.join(row).encode()), 1048576)
        import io
        stream = io.StringIO(newline='')
        csv.writer(stream).writerow(row)
        stream.seek(0)
        self.assertEqual(next(csv.reader(stream)), row)


if __name__ == '__main__':
    unittest.main()
