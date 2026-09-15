import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / "tools/tx_probe_report.py"
spec = importlib.util.spec_from_file_location("probe", PATH)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
ROW = "stage=tx_probe cycle=1 tag=1 sequence=8 phase=Finished accepted_us=10 queued_us=11 picked_us=12 finished_us=Some(15) result=Some(Ok(0))"
ROW = ROW.replace("queued_us=11", "queued_us=Some(11)").replace("picked_us=12", "picked_us=Some(12)")
SUMMARY = "stage=tx_probe_summary cycle=1 retained=1 capacity=64 rejected=0 exhausted=0 invalid=0 scope_changes=0 attempt_hooks=false"


class ProbeReport(unittest.TestCase):
    def test_discards_unrelated_lines(self):
        text = "private unrelated material\n\x1b[32mINFO " + ROW + "\x1b[0m\n" + SUMMARY
        report = probe.parse(text)
        self.assertEqual(report["entries"][0]["result"], {"success": True, "retries": 0})
        self.assertNotIn("private", str(report))

    def test_preserves_failure_without_invented_attempt_count(self):
        for error in ("MacProtocol(AckTimeout)", "ChannelAccess(Collision)", "DisabledKeySlot",
                      "MacProtocol(RtsChannelAccessError(Timeout))",
                      "MacProtocol(Unknown { error: 3, sub_error: 4 })"):
            report = probe.parse(ROW.replace("Some(Ok(0))", "Some(Err(" + error + "))"))
            self.assertEqual(report["entries"][0]["result"], {"success": False, "error": error, "retries": None})
            self.assertEqual(report["cycles_without_summary"], [1])

    def test_incomplete_is_not_success(self):
        row = ROW.replace("phase=Finished", "phase=Picked").replace("finished_us=Some(15)", "finished_us=None").replace("Some(Ok(0))", "None")
        self.assertIsNone(probe.parse(row)["entries"][0]["result"])

    def test_limits_remain_visible(self):
        report = probe.parse(ROW + "\n" + SUMMARY.replace("rejected=0", "rejected=2"))
        self.assertEqual(report["summaries"][0]["rejected"], 2)

    def test_bad_records_fail_closed(self):
        for bad in (ROW.replace("Some(15)", "Some(9)"), ROW.replace("Some(Ok(0))", "None"),
                    ROW.replace("Some(Ok(0))", "Some(Ok(300))"), ROW.replace("sequence=8", "sequence=21"),
                    ROW.replace("Some(Ok(0))", "unrelated secret text"), ROW + "\n" + ROW,
                    ROW + "\n" + SUMMARY.replace("retained=1", "retained=2")):
            with self.assertRaises(ValueError):
                probe.parse(bad)


if __name__ == "__main__":
    unittest.main()
