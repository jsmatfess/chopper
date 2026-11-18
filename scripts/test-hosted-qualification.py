"""Fake-only maintained hosted qualification controls. No native dispatch."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE / 'hosted_picker'), str(HERE / 'hosted_picker/tests')]

if __name__ == '__main__':
    suite = unittest.defaultTestLoader.discover(str(HERE / 'hosted_picker/tests'))
    raise SystemExit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
