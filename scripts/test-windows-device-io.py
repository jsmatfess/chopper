"""Counter arithmetic and inference gates; no Windows privileges or jobs needed."""
import copy
import importlib.util
from pathlib import Path
import unittest


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


device = load('deviceio_tests', 'windows-device-io.py')
harness = load('deviceio_harness_tests', 'benchmark-windows-device-io.py')


class DeviceCounterTests(unittest.TestCase):
    def setUp(self):
        self.before = {'query_start_perf_ns': 0, 'query_end_perf_ns': 100,
                       'counters': {name: {'path': name, 'counter_type': 272696576,
                                          'timestamp_filetime': 1, 'raw_bytes': 100}
                                    for name in ('read', 'write')}}
        self.after = copy.deepcopy(self.before)
        self.after.update(query_start_perf_ns=2_000_000_000, query_end_perf_ns=2_000_000_100)
        for value in self.after['counters'].values():
            value.update(timestamp_filetime=2, raw_bytes=500)

    def test_raw_bytes_are_subtracted_without_rate_scaling(self):
        self.assertEqual(device.delta(self.before, self.after),
                         {'read_bytes': 400, 'write_bytes': 400, 'snapshot_midpoint_seconds': 2})

    def test_reset_stale_timestamp_and_identity_change_are_rejected(self):
        for change in [{'raw_bytes': 99}, {'timestamp_filetime': 1},
                       {'path': 'other'}, {'counter_type': 0}]:
            with self.subTest(change=change):
                altered = copy.deepcopy(self.after)
                altered['counters']['read'].update(change)
                with self.assertRaises(ValueError):
                    device.delta(self.before, altered)

    def test_subsecond_delta_is_rejected_even_with_advancing_provider_timestamp(self):
        self.after['query_start_perf_ns'] = 999_999_999
        with self.assertRaisesRegex(ValueError, 'at least one second'):
            device.delta(self.before, self.after)

    def test_noise_gates_use_idle_rates_and_drain_totals(self):
        zero = {'delta': {'read_bytes': 0, 'write_bytes': 0, 'snapshot_midpoint_seconds': 2}}
        noisy = {'delta': {'read_bytes': 50, 'write_bytes': 0, 'snapshot_midpoint_seconds': 2}}
        job = {'read_bytes': 100, 'write_bytes': 0, 'snapshot_midpoint_seconds': 1}
        self.assertEqual(harness.noise_flags(job, noisy, zero, zero),
                         ['read:pre_idle_exceeds_10pct', 'write:zero_job_delta'])
        self.assertEqual(harness.noise_flags(job, zero, noisy, zero),
                         ['read:drain_exceeds_10pct', 'write:zero_job_delta'])
        self.assertEqual(harness.noise_flags(job, zero, zero, noisy),
                         ['read:post_idle_exceeds_10pct', 'write:zero_job_delta'])


class FakeClock:
    def __init__(self):
        self.now = 0
        self.sleeps = []
        self.undersleep_once = False

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        advance = round(seconds * 1e9)
        if self.undersleep_once:
            advance //= 2
            self.undersleep_once = False
        self.now += advance


class FakeDevice(device.DeviceIO):
    """Exercise the real scheduler against a deterministic counter provider."""
    def __init__(self, clock, query_ns=0):
        self.clock_ns, self.sleep = clock.clock, clock.sleep
        self.last_snapshot = None
        self.collection_end_ns = None
        self.clock, self.query_ns, self.collections = clock, query_ns, []
        self.initial_snapshot = self.snapshot()

    def _collect(self, started):
        self.collections.append(started)
        self.clock.now += self.query_ns
        return {'query_start_perf_ns': started, 'query_end_perf_ns': self.clock.now,
                'counters': {name: {'path': name, 'counter_type': 272696576,
                                    'timestamp_filetime': len(self.collections),
                                    'raw_bytes': len(self.collections) * 100}
                             for name in ('read', 'write')}}


class CadenceTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.device = FakeDevice(self.clock, query_ns=100)

    def test_early_snapshot_rejects_before_provider_and_never_sleeps(self):
        for offset in [0, device.MIN_COLLECTION_NS - 1]:
            self.clock.now = 100 + offset
            with self.assertRaisesRegex(ValueError, 'at least one second'):
                self.device.snapshot()
        self.assertEqual(self.device.collections, [0])
        self.assertEqual(self.clock.sleeps, [])
        self.clock.now = 100 + device.MIN_COLLECTION_NS
        self.device.snapshot()
        self.assertEqual(self.device.collections, [0, 1_000_000_100])

    def test_explicit_wait_rechecks_undersleep_and_records_elapsed_wait(self):
        self.clock.undersleep_once = True
        after, waited = self.device.snapshot_when_ready()
        self.assertEqual(self.clock.sleeps, [1, .5])
        self.assertEqual(waited, 1)
        self.assertEqual(after['query_start_perf_ns'], 1_000_000_100)

    def test_ready_collection_does_not_label_call_overhead_as_padding(self):
        self.clock.now += 2_000_000_000
        def ticking_clock():
            self.clock.now += 10
            return self.clock.now
        self.device.clock_ns = ticking_clock
        _, waited = self.device.snapshot_when_ready()
        self.assertEqual(waited, 0)
        self.assertEqual(self.clock.sleeps, [])

    def test_oversleep_is_recorded_as_elapsed_wait(self):
        def oversleep(seconds):
            self.clock.now += round(seconds * 1e9) + 50_000_000
        self.device.sleep = oversleep
        after, waited = self.device.snapshot_when_ready()
        self.assertEqual(waited, 1.05)
        self.assertEqual(after['query_start_perf_ns'], 1_050_000_100)

    def test_long_job_has_no_padding_and_controls_share_boundaries(self):
        pre = harness.window(self.device, 2, self.device.initial_snapshot)
        started = self.clock.now
        self.clock.now += 3_000_000_000
        job = harness.finish_job_window(self.device, pre['after'], started, self.clock.now)
        drain = harness.window(self.device, 2, job['after'])
        post = harness.window(self.device, 2, drain['after'])
        self.assertIs(job['before'], pre['after'])
        self.assertIs(drain['before'], job['after'])
        self.assertIs(post['before'], drain['after'])
        self.assertEqual(job['post_cli_padding_seconds'], 0)
        self.assertEqual(job['cli_seconds'], 3)
        self.assertEqual(job['attribution_flags'], [])
        self.assertEqual(len(self.device.collections), 5)
        for previous, following in zip(self.device.collections, self.device.collections[1:]):
            self.assertGreaterEqual(following - previous, device.MIN_COLLECTION_NS + 100)

    def test_short_job_retains_cli_time_and_records_wider_device_interval(self):
        before = self.device.initial_snapshot
        started = self.clock.now
        self.clock.now += 200_000_000
        job = harness.finish_job_window(self.device, before, started, self.clock.now)
        self.assertEqual(job['cli_seconds'], .2)
        self.assertEqual(job['post_cli_padding_seconds'], .8)
        self.assertEqual(job['post_cli_boundary_gap_seconds'], .8)
        self.assertEqual(job['attribution_flags'], ['short_cli_interval', 'device_window_padded_after_cli'])
        self.assertGreaterEqual(job['delta']['snapshot_midpoint_seconds'], 1)

    def test_short_cli_with_large_setup_gap_still_excludes_attribution(self):
        self.clock.now += 2_000_000_000
        started = self.clock.now
        self.clock.now += 200_000_000
        job = harness.finish_job_window(self.device, self.device.initial_snapshot, started, self.clock.now)
        self.assertEqual(job['post_cli_padding_seconds'], 0)
        self.assertEqual(job['attribution_flags'], ['short_cli_interval'])

    def test_invalid_cli_interval_and_short_control_do_not_collect(self):
        with self.assertRaises(ValueError):
            harness.finish_job_window(self.device, self.device.initial_snapshot, 0, 1)
        with self.assertRaises(ValueError):
            harness.window(self.device, .5, self.device.initial_snapshot)
        self.assertEqual(self.device.collections, [0])

    def test_stale_boundary_and_nonfinite_controls_are_rejected(self):
        before = self.device.initial_snapshot
        self.device.snapshot_when_ready()
        with self.assertRaisesRegex(ValueError, 'latest device boundary'):
            harness.window(self.device, 2, before)
        with self.assertRaisesRegex(ValueError, 'latest device boundary'):
            harness.finish_job_window(self.device, before, self.clock.now, self.clock.now)
        for seconds in [float('nan'), float('inf')]:
            with self.assertRaises(ValueError):
                harness.window(self.device, seconds, self.device.last_snapshot)

    def test_failed_provider_still_enforces_retry_cadence(self):
        self.clock.now += device.MIN_COLLECTION_NS
        original = self.device._collect
        def failing_provider(started):
            original(started)
            raise OSError('provider failure')
        self.device._collect = failing_provider
        with self.assertRaises(OSError):
            self.device.snapshot()
        self.device._collect = original
        with self.assertRaisesRegex(ValueError, 'at least one second'):
            self.device.snapshot()
        self.device.snapshot_when_ready()
        self.assertEqual(len(self.device.collections), 3)


if __name__ == '__main__':
    unittest.main()
