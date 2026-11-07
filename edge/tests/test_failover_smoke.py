"""A short failover run with assertions on the invariants. The 30-repetition measurement is failover_test.py itself."""
from __future__ import annotations

import json
import subprocess
import sys

import stack


def test_failover_invariants(tmp_path):
    out = tmp_path / "failover_smoke.json"
    result = subprocess.run([sys.executable, str(stack.EDGE / "tests/failover_test.py"), "--reps", "2", "--out", str(out)],
                            capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    data = json.loads(out.read_text())
    for name in ("takeover_hold_last", "takeover_safe_first"):
        run = data[name]
        assert run["dual_drive_violations"] == 0
        assert run["state_continuity_failures"] == 0
        assert run["overflowed"] is False
        assert run["control_gap_ms"]["max"] < 1500
    assert data["takeover_hold_last"]["watchdog_trips"] == 0
    assert data["takeover_safe_first"]["safe_before_new_write_reps"] == data["takeover_safe_first"]["reps"]
    assert data["zombie"]["stale_accepted_total"] == 0
    assert data["zombie"]["violations"] == 0
    assert data["partition"]["stale_accepted_total"] == 0
    assert data["split_brain"]["standby_writes_accepted"] == 0
    assert data["split_brain"]["standby_writes_refused"] > 0
    assert all("refused" in v for v in data["stale_write"].values())
    assert data["state_transfer"]["failed_latch_after_takeover"] == "TRUE"
    migration = data["migration"]
    assert migration["violations"] == 0 and migration["wrong_node_granted"] == 0
    assert migration["watchdog_trips"] == 0 and migration["output_changes_in_gap"] == 0
    assert migration["bumpless_reps"] == migration["reps"]
    assert len(migration["digests"]) == 1
