"""Sample file space in an owned benchmark directory; no device-I/O claim."""
import os
from pathlib import Path
import threading

class StorageSampler:
    """Sample owned job/staging/output files; exclude source/config/time files."""
    def __init__(self, root, excluded):
        self.root, self.excluded = root, set(excluded)
        self.stop = threading.Event()
        self.samples = self.logical = self.allocated = self.files = 0
        self.thread = threading.Thread(target=self.run, daemon=True)

    def sample(self):
        logical = allocated = files = 0
        for directory, _, names in os.walk(self.root):
            for name in names:
                path = Path(directory) / name
                if path in self.excluded: continue
                try:
                    stat = path.stat()
                except OSError: continue  # Job-owned files may disappear or publish atomically.
                logical += stat.st_size; allocated += stat.st_blocks * 512; files += 1
        self.samples += 1
        self.logical = max(self.logical, logical)
        self.allocated = max(self.allocated, allocated)
        self.files = max(self.files, files)

    def run(self):
        while not self.stop.is_set():
            self.sample(); self.stop.wait(0.01)

    def finish(self):
        self.stop.set(); self.thread.join(); self.sample()
        return {'interval_seconds': 0.01, 'samples': self.samples,
                'peak_logical_bytes': self.logical, 'peak_allocated_bytes': self.allocated,
                'peak_files': self.files,
                'scope': 'sampled job intermediates plus publication staging/retained outputs; source/config/time files excluded; directory metadata excluded; sampled peaks are lower bounds'}
