"""Test cron/manager.py (ch.5 scheduling subsystem).

Regression coverage for two gaps: CronManager required a Path (a str cwd
raised TypeError), and the module had no tests at all.
"""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from openharness.cron.manager import CronManager, cron_due


class TestCronDue(unittest.TestCase):
    def test_every_minute_matches(self):
        self.assertTrue(cron_due("* * * * *", datetime(2026, 10, 21, 12, 34)))

    def test_fixed_minute_only_matches_that_minute(self):
        self.assertTrue(cron_due("30 * * * *", datetime(2026, 10, 21, 12, 30)))
        self.assertFalse(cron_due("30 * * * *", datetime(2026, 10, 21, 12, 31)))

    def test_step_and_range_fields(self):
        self.assertTrue(cron_due("*/15 * * * *", datetime(2026, 10, 21, 12, 45)))
        self.assertFalse(cron_due("*/15 * * * *", datetime(2026, 10, 21, 12, 46)))
        self.assertTrue(cron_due("* 9-11 * * *", datetime(2026, 10, 21, 10, 0)))
        self.assertFalse(cron_due("* 9-11 * * *", datetime(2026, 10, 21, 12, 0)))

    def test_malformed_schedule_never_matches(self):
        self.assertFalse(cron_due("* * *", datetime(2026, 10, 21, 12, 0)))


class TestCronManagerPersistence(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="oh_test_"))

    def test_accepts_str_cwd(self):
        # Regression: previously `cwd / "data"` raised TypeError for a str.
        manager = CronManager(str(self.dir))
        self.assertEqual(manager.cwd, self.dir)

    def test_accepts_path_cwd(self):
        manager = CronManager(self.dir)
        self.assertEqual(manager.cwd, self.dir)

    def test_create_and_persist(self):
        manager = CronManager(str(self.dir))
        job = manager.create("* * * * *", "command", command="echo hi")

        self.assertEqual(job.kind, "command")
        self.assertEqual(len(manager.list()), 1)
        self.assertTrue((self.dir / "data" / "cron.json").exists())

        reloaded = CronManager(str(self.dir))
        self.assertEqual(len(reloaded.list()), 1)
        self.assertEqual(reloaded.list()[0].command, "echo hi")

    def test_delete_removes_and_persists(self):
        manager = CronManager(str(self.dir))
        job = manager.create("0 * * * *", "agent", prompt="check")

        self.assertTrue(manager.delete(job.job_id))
        self.assertEqual(manager.list(), [])
        self.assertEqual(CronManager(str(self.dir)).list(), [])

    def test_delete_unknown_returns_false(self):
        self.assertFalse(CronManager(str(self.dir)).delete("cron-999"))

    def test_corrupt_file_falls_back_to_empty(self):
        (self.dir / "data").mkdir()
        (self.dir / "data" / "cron.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(CronManager(str(self.dir)).list(), [])


if __name__ == "__main__":
    unittest.main()
