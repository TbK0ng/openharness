# Session-level cleanup for scratch directories created by the suite.
# `pythonpath = ["src", "."]` in pyproject.toml already makes `tests.util`
# importable, so no sys.path juggling is needed here.

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Scratch directories the suite creates in the project root. They are
# git-ignored, but the tests never removed them on exit, so repeated runs
# piled up dozens of leftover dirs. Wipe them once the session finishes.
_SCRATCH = ("_tmp_tests", "tmp*", "oh_test_*", "oh_hooks_*")


def pytest_sessionfinish(session, exitstatus):
    for pattern in _SCRATCH:
        for path in ROOT.glob(pattern):
            if path.is_dir() and path != ROOT:
                shutil.rmtree(path, ignore_errors=True)
