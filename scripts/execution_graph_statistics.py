"""Exact paired-block bootstrap, with repeated sequences counted by weight."""
from collections import Counter, defaultdict
import hashlib
from math import ceil, comb, isfinite, log, sqrt
from pathlib import Path
import random
import statistics
import sys
import _random


def paired_bootstrap_upper95(baseline, enabled):
    """Return the same quantile as enumerating all n**n ordered resamples.

    A count vector has n! / product(count!) ordered sequences. Identical paired
    blocks can be grouped; each group's multiplicity contributes multiplicity**count.
    Integer weights preserve the complete distribution, without Monte Carlo error.
    The fixed 12-block limit bounds this diagnostic/acceptance calculation.
    """
    n = len(baseline)
    if not 1 <= n <= 12 or len(enabled) != n:
        raise ValueError('Matched samples require between one and twelve blocks')
    if any(not isfinite(value) or value <= 0 for value in [*baseline, *enabled]):
        raise ValueError('Elapsed samples must be finite and positive')
    grouped = Counter(zip(baseline, enabled))
    pairs, multiplicities = zip(*grouped.items())
    orders = [sorted(range(len(pairs)), key=lambda i: pairs[i][column]) for column in (0, 1)]
    counts = [0] * len(pairs)
    distribution = defaultdict(int)

    def median(column):
        total = 0
        low = None
        for i in orders[column]:
            total += counts[i]
            if low is None and total > (n - 1) // 2:
                low = pairs[i][column]
            if total > n // 2:
                return (low + pairs[i][column]) / 2
        raise AssertionError('Resample is missing observations')

    def visit(index, remaining, weight):
        if index == len(pairs) - 1:
            counts[index] = remaining
            weight *= multiplicities[index] ** remaining
            distribution[median(1) / median(0) - 1] += weight
            return
        for count in range(remaining + 1):
            counts[index] = count
            visit(index + 1, remaining - count,
                  weight * comb(remaining, count) * multiplicities[index] ** count)

    visit(0, n, 1)
    sequences = n ** n
    assert sum(distribution.values()) == sequences
    threshold = (95 * sequences + 99) // 100
    cumulative = 0
    for value, weight in sorted(distribution.items()):
        cumulative += weight
        if cumulative >= threshold:
            return value
    raise AssertionError('Incomplete resampling distribution')


def paired_bootstrap_conservative_upper95(baseline, enabled, *, resamples, seed):
    """Bound the conditional upper95 quantile with explicit simulation error.

    DKW gives P(sup|F_empirical-F| > epsilon) <= 2*exp(-2*m*epsilon**2).
    Thus the empirical (0.95+epsilon) quantile conservatively bounds the true
    conditional bootstrap upper95 quantile except with probability 1e-6 under
    independent uniform resampling. The seeded Python PRNG makes the numerical
    procedure reproducible; this is not a population or sequential-test bound.
    """
    n = len(baseline)
    if not 1 <= n <= 18 or len(enabled) != n:
        raise ValueError('Matched simulation supports at most eighteen blocks')
    if any(not isfinite(value) or value <= 0 for value in [*baseline, *enabled]):
        raise ValueError('Elapsed samples must be finite and positive')
    if type(resamples) is not int or not 10000 <= resamples <= 1_000_000 or type(seed) is not int:
        raise ValueError('Declare 10000 to 1000000 resamples and an integer seed')
    alpha = 1e-6
    epsilon = sqrt(log(2 / alpha) / (2 * resamples))
    level = .95 + epsilon
    assert level < 1
    rng = random.Random(seed)
    ratios = []
    for _ in range(resamples):
        indices = [rng.randrange(n) for _ in range(n)]
        ratios.append(statistics.median(enabled[i] for i in indices)
                      / statistics.median(baseline[i] for i in indices) - 1)
    ratios.sort()
    def file_identity(name):
        if name is None:
            return None
        path = Path(name).resolve()
        return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    return {
        'upper95_slowdown': ratios[ceil(level * resamples) - 1],
        'estimated_upper95_slowdown': ratios[ceil(.95 * resamples) - 1],
        'sampled_quantile_level': level, 'dkw_epsilon': epsilon,
        'simulation_error_probability': alpha, 'resamples': resamples, 'seed': seed,
        'runtime': {
            'python_version': sys.version, 'implementation': sys.implementation.name,
            'cache_tag': sys.implementation.cache_tag,
            'interpreter': file_identity(sys.executable),
            'random_module': file_identity(random.__file__),
            'random_backend': file_identity(getattr(_random, '__file__', None)),
        },
        'method': 'paired-block Monte Carlo with conservative DKW quantile inflation',
    }
