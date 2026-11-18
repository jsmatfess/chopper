# Historical reproduction only: requires matching pinned pre-removal bucket builds.
# Not a candidate harness for the current engine; preserve original diagnostic flags.
"""Preregistered disjoint-cohort follow-up; original bucket flags remain intact."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import statistics
import tempfile

spec = importlib.util.spec_from_file_location('bucket_window', Path(__file__).with_name('reproduce-bucket-window.py'))
repro = importlib.util.module_from_spec(spec); spec.loader.exec_module(repro)


def ideal(seed):
    def rng(purpose):
        return random.Random(int.from_bytes(hashlib.sha256(('independent-buckets-window-ideal-v1/' + purpose + '/' + seed).encode()).digest(), 'big'))
    routing = rng('route'); buckets = [[] for _ in range(16)]
    for source in range(256): buckets[routing.randrange(16)].append(source)
    for index, bucket in enumerate(buckets): rng(f'leaf/{index}').shuffle(bucket)
    order = [source for bucket in buckets for source in bucket]
    return repro.diag.combined([order], repro.diag.fixture('ascending'))[repro.diag.METRICS.index('window_labels')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--null-cache', required=True, type=Path)
    args = parser.parse_args()
    cache = repro.load_calibration(args.null_cache)
    seeds = [[f'independent-buckets-window-followup-v1/c{cohort:02}/s{sample:02}' for sample in range(32)] for cohort in range(16)]
    flat = [seed for cohort in seeds for seed in cohort]
    assert len(set(flat)) == 512 and set(flat).isdisjoint(repro.diag.SEEDS)
    emit = lambda record: print(json.dumps(record), flush=True)
    emit({'type': 'design', 'version': 'independent-buckets-window-followup-v1', 'cohorts': seeds, 'algorithms': ['buckets', 'uniform_v1', 'ideal_buckets'], 'metric': 'window_labels', 'comparisons': 48, 'threshold': 0.05 / 48, 'ideal_expectation': 6 * 256 / 255, 'binary_sha256': hashlib.sha256(args.binary.read_bytes()).hexdigest(), 'null_cache_sha256': hashlib.sha256(args.null_cache.read_bytes()).hexdigest(), 'design_sha256': hashlib.sha256(Path('docs/independent-buckets-acceptance.md').read_bytes()).hexdigest(), 'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'observer_sha256': hashlib.sha256(Path(__file__).with_name('reproduce-bucket-window.py').read_bytes()).hexdigest()})
    aggregate = {algorithm: [] for algorithm in ['buckets', 'uniform_v1', 'ideal_buckets']}; flags = []
    with tempfile.TemporaryDirectory(prefix='chopper-window-followup-') as directory:
        root = Path(directory); repro.write_fixture(root)
        for cohort, batch in enumerate(seeds):
            values = {algorithm: [] for algorithm in aggregate}
            for seed in batch:
                for algorithm in aggregate:
                    if algorithm == 'ideal_buckets': metric, fingerprint = ideal(seed), None
                    else: metric, fingerprint = repro.observe(args.binary.resolve(), root, seed, 'auto' if algorithm == 'buckets' else 'uniform')
                    values[algorithm].append(metric); aggregate[algorithm].append(metric)
                    emit({'type': 'sample', 'cohort': cohort, 'algorithm': algorithm, 'seed': seed, 'window_labels': metric, 'fingerprint': fingerprint})
            for algorithm, observations in values.items():
                mean = statistics.mean(observations); p = repro.compare(mean, cache); flagged = p < 0.05 / 48
                if flagged: flags.append(f'{cohort}/{algorithm}')
                emit({'type': 'comparison', 'cohort': cohort, 'algorithm': algorithm, 'mean': mean, 'p': p, 'threshold': 0.05 / 48, 'flagged': flagged})
    emit({'type': 'summary', 'native_jobs': 1024, 'ideal_samples': 512, 'comparisons': 48, 'flags': flags, 'descriptive_aggregate': {algorithm: {'count': len(values), 'mean': statistics.mean(values), 'min': min(values), 'max': max(values)} for algorithm, values in aggregate.items()}, 'interpretation': 'Separate finite follow-up; original flags retained; no proof of independence or uniformity.'})


if __name__ == '__main__':
    main()
