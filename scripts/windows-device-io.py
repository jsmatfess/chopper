"""Read-only whole-device Windows byte counters; never process attribution.

PDH PhysicalDisk raw byte counters count host-visible device traffic, including
other processes, paging, metadata and delayed writes. They do not measure NAND
traffic. Cache hits need not reach the device. No flush/cache/admin changes.

API/counter contracts:
https://learn.microsoft.com/en-us/windows/win32/api/pdh/nf-pdh-pdhgetrawcountervalue
https://learn.microsoft.com/en-us/windows/win32/api/pdh/ns-pdh-pdh_raw_counter
https://learn.microsoft.com/en-us/windows/win32/perfctrs/about-performance-counters
https://learn.microsoft.com/en-us/windows/win32/api/winioctl/ni-winioctl-ioctl_volume_get_volume_disk_extents
"""
import argparse
import ctypes as C
from ctypes import wintypes as W
import json
import math
import os
from pathlib import Path
import time


MIN_COLLECTION_NS = 1_000_000_000


class RawCounter(C.Structure):
    _fields_ = [('status', W.DWORD), ('timestamp', W.FILETIME),
                ('first', C.c_longlong), ('second', C.c_longlong), ('multiple', W.DWORD)]


class DiskExtent(C.Structure):
    _fields_ = [('disk_number', W.DWORD), ('offset', C.c_longlong), ('length', C.c_longlong)]


class VolumeExtents(C.Structure):
    _fields_ = [('count', W.DWORD), ('extents', DiskExtent * 1)]


def volume_mapping(path):
    """Resolve mount root and demand a single physical-disk extent."""
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.GetVolumePathNameW.argtypes = [W.LPCWSTR, W.LPWSTR, W.DWORD]
    kernel.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p,
                                  W.DWORD, W.DWORD, W.HANDLE]
    kernel.CreateFileW.restype = W.HANDLE
    kernel.DeviceIoControl.argtypes = [W.HANDLE, W.DWORD, C.c_void_p, W.DWORD,
                                      C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p]
    kernel.CloseHandle.argtypes = [W.HANDLE]
    resolved = str(Path(path).resolve(strict=True))
    root = C.create_unicode_buffer(32768)
    if not kernel.GetVolumePathNameW(resolved, root, len(root)):
        raise C.WinError(C.get_last_error())
    # Restrict to simple local drive roots; mounted/spanned volumes need an
    # explicit instance mapping and must not be silently guessed.
    if len(root.value) != 3 or root.value[1:] != ':\\':
        raise ValueError(f'unsupported volume root: {root.value!r}')
    handle = kernel.CreateFileW('\\\\.\\' + root.value[:2], 0, 3, None, 3, 0, None)
    if handle == W.HANDLE(-1).value:
        raise C.WinError(C.get_last_error())
    try:
        extents, returned = VolumeExtents(), W.DWORD()
        if not kernel.DeviceIoControl(handle, 0x00560000, None, 0,
                                      C.byref(extents), C.sizeof(extents), C.byref(returned), None):
            raise C.WinError(C.get_last_error())
        if extents.count != 1 or returned.value < C.sizeof(extents):
            raise ValueError('single physical-disk extent required')
        extent = extents.extents[0]
        return {'path': resolved, 'volume_root': root.value,
                'disk_number': extent.disk_number, 'extent_offset_bytes': extent.offset,
                'extent_length_bytes': extent.length,
                'instance': f'{extent.disk_number} {root.value[:2]}',
                'mapping_api': 'IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS'}
    finally:
        kernel.CloseHandle(handle)


class DeviceIO:
    def __init__(self, path):
        if os.name != 'nt':
            raise OSError('Windows required')
        self.mapping = volume_mapping(path)
        self.pdh = C.WinDLL('pdh')
        self.pdh.PdhOpenQueryW.argtypes = [W.LPCWSTR, C.c_size_t, C.POINTER(W.HANDLE)]
        self.pdh.PdhAddEnglishCounterW.argtypes = [W.HANDLE, W.LPCWSTR, C.c_size_t,
                                                 C.POINTER(W.HANDLE)]
        self.pdh.PdhCollectQueryData.argtypes = [W.HANDLE]
        self.pdh.PdhGetRawCounterValue.argtypes = [W.HANDLE, C.POINTER(W.DWORD),
                                                 C.POINTER(RawCounter)]
        self.pdh.PdhCloseQuery.argtypes = [W.HANDLE]
        self.query, self.counters = W.HANDLE(), {}
        self.clock_ns, self.sleep = time.perf_counter_ns, time.sleep
        self.last_snapshot = None
        self.collection_end_ns = None
        self.check(self.pdh.PdhOpenQueryW(None, 0, C.byref(self.query)))
        try:
            for direction in ('read', 'write'):
                counter = W.HANDLE()
                counter_path = f'\\PhysicalDisk({self.mapping["instance"]})\\Disk {direction.title()} Bytes/sec'
                self.check(self.pdh.PdhAddEnglishCounterW(self.query, counter_path, 0, C.byref(counter)))
                self.counters[direction] = (counter, counter_path)
            self.initial_snapshot = self.snapshot()  # Verify before jobs; reuse this boundary.
        except BaseException:
            self.close()
            raise

    @staticmethod
    def check(status):
        if status:
            raise OSError(f'PDH status 0x{status & 0xffffffff:08x}')

    def snapshot(self):
        """Collect immediately or reject; never hide a wait inside a boundary."""
        started = self.clock_ns()
        if self.collection_end_ns is not None and started - self.collection_end_ns < MIN_COLLECTION_NS:
            raise ValueError('device collections require at least one second between queries')
        try:
            result = self._collect(started)
        finally:
            # A failed provider read still attempted collection; do not permit
            # an immediate retry that violates the provider's sampling cadence.
            self.collection_end_ns = self.clock_ns()
        self.last_snapshot = result
        return result

    def snapshot_when_ready(self, *, not_before_ns=0):
        """Explicitly wait for cadence/deadline and report the wait separately."""
        if self.collection_end_ns is not None:
            not_before_ns = max(not_before_ns, self.collection_end_ns + MIN_COLLECTION_NS)
        waiting_started = self.clock_ns()
        now = waiting_started
        while now < not_before_ns:
            self.sleep((not_before_ns - now) / 1e9)
            now = self.clock_ns()
        result = self.snapshot()
        return result, (now - waiting_started) / 1e9

    def _collect(self, started):
        self.check(self.pdh.PdhCollectQueryData(self.query))
        values = {}
        for direction, (handle, path) in self.counters.items():
            raw, kind = RawCounter(), W.DWORD()
            self.check(self.pdh.PdhGetRawCounterValue(handle, C.byref(kind), C.byref(raw)))
            if raw.status not in (0, 1):
                raise OSError(f'PDH invalid raw status 0x{raw.status:08x}: {path}')
            if kind.value != 272696576:  # PERF_COUNTER_BULK_COUNT, raw cumulative bytes.
                raise ValueError(f'unexpected counter type {kind.value}: {path}')
            if raw.first < 0:
                raise ValueError('negative cumulative byte count')
            values[direction] = {'path': path, 'raw_bytes': raw.first, 'status': raw.status,
                                 'counter_type': kind.value, 'second_value': raw.second,
                                 'timestamp_filetime': (raw.timestamp.dwHighDateTime << 32) | raw.timestamp.dwLowDateTime}
        return {'query_start_perf_ns': started, 'query_end_perf_ns': self.clock_ns(),
                'counters': values}

    def close(self):
        if self.query:
            self.pdh.PdhCloseQuery(self.query)
            self.query = W.HANDLE()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def delta(before, after):
    """Return raw device deltas, rejecting reset/change rather than wrapping."""
    result = {}
    if after['query_start_perf_ns'] - before['query_end_perf_ns'] < MIN_COLLECTION_NS:
        raise ValueError('device delta requires at least one second between queries')
    for direction in ('read', 'write'):
        old, new = (item['counters'][direction] for item in (before, after))
        if new['path'] != old['path'] or new['counter_type'] != old['counter_type']:
            raise ValueError('counter identity changed')
        if new['timestamp_filetime'] <= old['timestamp_filetime']:
            raise ValueError('counter timestamp did not advance')
        difference = new['raw_bytes'] - old['raw_bytes']
        if difference < 0:
            raise ValueError('device counter reset')
        result[f'{direction}_bytes'] = difference
    result['snapshot_midpoint_seconds'] = (
        after['query_start_perf_ns'] + after['query_end_perf_ns']
        - before['query_start_perf_ns'] - before['query_end_perf_ns']) / 2e9
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--path', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=2)
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or not 1 <= args.seconds <= 60:
        parser.error('seconds must be at least one and at most 60')
    with DeviceIO(args.path) as device:
        before = device.initial_snapshot
        after, waited = device.snapshot_when_ready(not_before_ns=before['query_end_perf_ns'] + int(args.seconds * 1e9))
        print(json.dumps({'type': 'device_idle_probe', 'mapping': device.mapping,
                          'scope': 'whole physical disk; all processes; not NAND or process-attributed I/O',
                          'requested_seconds': args.seconds, 'wait_seconds': waited,
                          'before': before, 'after': after, 'delta': delta(before, after)}))
