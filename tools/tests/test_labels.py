"""Jump labels (markers / labels file), detection rate per sensitivity and IMU snippet export."""
import gzip
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import make_imu_fixtures  # noqa: E402

from mtbdyn import imu  # noqa: E402
from mtbdyn.model import Ride, Sample  # noqa: E402

WALL0 = 1_790_000_000.0


def write_imu(path):
    """Two rides' worth of IMU: a 0.6 s jump at 3 s and a 0.25 s hop at 23 s (wall clock WALL0 + t)."""
    rows = make_imu_fixtures.ride(8.0, (3.0, 0.6), 3.0, 0.05, seed=1)
    rows += [(s, t + 20.0, x, y, z) for s, t, x, y, z in make_imu_fixtures.ride(8.0, (3.0, 0.25), 1.8, 0.05, seed=2)]
    with gzip.open(path, "wt") as f:
        f.write(f"# wall_ms={int(WALL0 * 1000)} elapsed_ms=0\nsensor,elapsed_ms,x,y,z\n")
        for s, t, x, y, z in rows:
            f.write(f"{s},{t * 1000:.2f},{x:.4f},{y:.4f},{z:.4f}\n")


class LabelsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.imu_path = os.path.join(self.dir, "imu.csv.gz")
        write_imu(self.imu_path)
        self.ride = Ride(samples=[Sample(t=WALL0 + i, speed=6.0) for i in range(30)])
        # Marked right after the jump (lands at 3.6 s) and after the hop.
        self.ride.markers = [{"n": 1, "t": WALL0 + 8.0}, {"n": 2, "t": WALL0 + 26.0}]

    def test_markers_rate_each_sensitivity(self):
        accel, _ = imu.load_imu(self.imu_path)
        labels = imu.labels_for(self.ride, None, 0)
        ev = imu.evaluate_labels(accel, labels)
        self.assertEqual(1, ev["MEDIUM"]["found"])   # the 0.25 s hop is too short for MEDIUM (0.28 s), not for HIGH (0.20 s)
        self.assertEqual(1, ev["MEDIUM"]["missed"])
        self.assertEqual(2, ev["HIGH"]["found"])
        text = "\n".join(imu.labels_report(ev, labels))
        self.assertIn("best fit: HIGH", text)

    def test_labels_file_with_nojump(self):
        labels_path = os.path.join(self.dir, "labels.csv")
        with open(labels_path, "w") as f:
            f.write("# time (UTC), label\n")
            f.write(f"{WALL0 + 3.0},jump\n{WALL0 + 23.0},nojump\n")
        accel, _ = imu.load_imu(self.imu_path)
        ev = imu.evaluate_labels(accel, imu.labels_for(None, labels_path, 0))
        self.assertEqual((1, 0), (ev["MEDIUM"]["found"], ev["MEDIUM"]["false"]))
        self.assertEqual((1, 1), (ev["HIGH"]["found"], ev["HIGH"]["false"]))

    def test_export_writes_fixtures_and_manifest(self):
        out = os.path.join(self.dir, "fixtures")
        written = imu.export_snippets(self.imu_path, imu.labels_for(self.ride, None, 0), out, "r1_")
        self.assertEqual(["r1_01_jump.csv", "r1_02_jump.csv", "manifest.json"], written)
        with open(os.path.join(out, "manifest.json")) as f:
            manifest = json.load(f)["fixtures"]
        self.assertEqual(2, len(manifest))
        self.assertAlmostEqual(0.6, manifest[0]["airSec"], delta=0.05)
        with open(os.path.join(out, "r1_01_jump.csv")) as f:
            head = [next(f) for _ in range(3)]
        self.assertTrue(head[0].startswith("# label=jump source=real"))
        self.assertTrue(head[2].split(",")[1] == "0.00")   # relative time, nothing that locates the ride
        # Exporting again replaces, not duplicates.
        imu.export_snippets(self.imu_path, imu.labels_for(self.ride, None, 0), out, "r1_")
        with open(os.path.join(out, "manifest.json")) as f:
            self.assertEqual(2, len(json.load(f)["fixtures"]))


if __name__ == "__main__":
    unittest.main()
