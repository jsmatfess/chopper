"""Independent sampling while the runner hashes inputs/artifacts or waits.

The owner supplies descendant stopping; a failure never kills the controller
that must retain Original until pending operations and handles are resolved.
"""
from pathlib import Path
import threading
import time
from .guard import load_runner


class Watchdog:
    def __init__(self, guard, failure_path, terminate=None,
                 interval=1, stale=5):
        if not callable(terminate):raise ValueError('Owning descendant-stop callback required')
        self.guard, self.path, self.terminate = guard, Path(failure_path), terminate
        self.interval, self.stale = interval, stale
        self.done = threading.Event()
        self.initial = threading.Event()
        self.lock = threading.Lock()
        self.completed = time.monotonic()
        self.failure = None
        self.error = None
        self.termination_error = None
        self.launch_uncertain = False
        self.sampler = threading.Thread(target=self.sample_loop, daemon=True)
        self.monitor = threading.Thread(target=self.monitor_loop, daemon=True)

    def fail(self, error):
        with self.lock:
            if self.failure is not None:
                return
            self.failure = str(error)
            self.error = error
        try:
            load_runner().write_json(self.path, dict(status='failed', checkpoint='independent-watchdog',
                error=self.failure, sampled_unix=time.time()))
        finally:
            try:self.terminate()  # The owner remains alive with Original held.
            except BaseException as error:self.termination_error=error

    def sample_loop(self):
        while not self.done.is_set():
            try:
                self.guard()
                self.completed = time.monotonic()
                self.initial.set()
            except BaseException as error:
                self.fail(error)
                return
            self.done.wait(self.interval)

    def monitor_loop(self):
        while not self.done.wait(min(self.interval, self.stale / 4)):
            if time.monotonic() - self.completed >= self.stale:
                self.fail(OSError('scale guard sampling stale: no completed physical/identity sample within five seconds'))
                return

    def start(self):
        self.launch_uncertain = True
        self.sampler.start()
        self.monitor.start()
        self.launch_uncertain = False
        return self

    def check(self):
        if self.failure is not None:
            raise OSError('scale independent watchdog: ' + self.failure) from self.error

    def stop(self):
        self.done.set()
        for thread in (self.sampler,self.monitor):
            if thread.ident is not None:thread.join(timeout=self.stale)
        if self.sampler.is_alive() or self.monitor.is_alive():
            self.fail(OSError('scale watchdog did not stop'))
        self.check()
