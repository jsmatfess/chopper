"""Independent controls for the scalable plain-Balanced benchmark verifier."""
import copy
import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('movement', Path(__file__).with_name('benchmark-data-movement.py'))
BENCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCH)


class PlainVerification(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.recipe = dict(name='plain-verifier-control', rows=19, payload_bytes=8, wide=False,
                           operations=[dict(type='balanced', files=8)])
        self.job = dict(operations=self.recipe['operations'], resources=dict(workers=8, memory_mb=256),
                        limits=dict(rows=3, bytes=1024))
        self.analysis = dict(rows=19, columns=3, header=BENCH.verify.header(self.recipe), groups=8,
                             workers=8, memory_budget_bytes=256*1024**2, output_files=8,
                             output_csv_bytes=0, stages=[dict(operation=1, input_groups=1, output_groups=8,
                                                             smallest_group=2, largest_group=3, empty_groups=0)])
        outputs = []
        identity = 0
        for part in range(8):
            quota = 19//8 + (part < 19%8)
            path = self.root / f'part-{part}.csv'
            with path.open('w', newline='', encoding='utf-8') as stream:
                writer = csv.writer(stream, lineterminator='\n')
                writer.writerow(self.analysis['header'])
                for _ in range(quota):
                    writer.writerow(BENCH.verify.fields(self.recipe, identity))
                    identity += 1
            size = path.stat().st_size
            outputs.append(dict(type='output', path=path.name, rows=quota, csv_bytes=size, stored_bytes=size,
                                compressed_target_exceeded=False, lineage=[dict(operation=0, part=part+1)]))
            self.analysis['output_csv_bytes'] += size
        self.records = [dict(type='job', schema_version=1, config=self.job, analysis=self.analysis), *outputs]
        self.save_manifest()

    def save_manifest(self):
        (self.root/'manifest.jsonl').write_text(''.join(json.dumps(v)+'\n' for v in self.records))

    def check(self):
        return BENCH.check(self.recipe, self.root, self.analysis, self.job)

    def test_accepts_nondivisible_quoted_multiline_fields_and_explicit_workers(self):
        self.assertTrue(self.check()['exact_encounter_order'])

    def test_rejects_reordered_rows_with_unchanged_counts_bytes_and_membership(self):
        path = self.root/'part-0.csv'
        with path.open(newline='', encoding='utf-8') as stream:
            rows = list(csv.reader(stream))
        rows[1], rows[2] = rows[2], rows[1]
        with path.open('w', newline='', encoding='utf-8') as stream:
            csv.writer(stream, lineterminator='\n').writerows(rows)
        with self.assertRaisesRegex(ValueError, 'encounter-order'):
            self.check()

    def test_rejects_wrong_resolved_worker_count(self):
        self.analysis['workers'] = 1
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'resources'):
            self.check()

    def test_rejects_csv_and_row_caps(self):
        for field, cap in [('rows', 1), ('bytes', 1)]:
            original = copy.deepcopy(self.job['limits'])
            self.job['limits'][field] = cap
            self.save_manifest()
            with self.assertRaisesRegex(ValueError, 'cap'):
                self.check()
            self.job['limits'] = original

    def test_rejects_unlisted_output_and_unsafe_paths(self):
        extra = self.root/'extra.csv'
        extra.write_text('unexpected')
        with self.assertRaisesRegex(ValueError, 'unlisted'):
            self.check()
        extra.unlink()
        self.records[1]['path'] = '../outside.csv'
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            self.check()


if __name__ == '__main__':
    unittest.main()
