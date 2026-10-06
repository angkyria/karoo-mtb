"""labels.csv, marker labels and label precedence; review candidates, spots and review mode."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from mtbdyn import groundtruth, imu  # noqa: E402
from mtbdyn.model import Ride, Sample  # noqa: E402

WALL0 = 1_790_000_000.0


def _write_min_ride(d, events):
    """meta.json + a 10-row samples.csv + events.jsonl, the columns load_karoo_dir needs."""
    with open(os.path.join(d, "meta.json"), "w") as f:
        json.dump({"startWallMs": int(WALL0 * 1000), "appVersion": "test"}, f)
    cols = ["wall_ms", "dt", "distance_m", "d_dist_m", "speed_ms", "grade_pct", "altitude_m", "lat", "lon"]
    with open(os.path.join(d, "samples.csv"), "w") as f:
        f.write(",".join(cols) + "\n")
        for i in range(10):
            f.write(f"{int((WALL0 + i) * 1000)},1,{6 * i},6,6,0,100,35.0,33.0\n")
    with open(os.path.join(d, "events.jsonl"), "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


class LabelsFileTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_append_then_read_back_with_mixed_formats(self):
        groundtruth.append_label(self.dir, int((WALL0 + 3.0) * 1000), "jump", "review")
        groundtruth.append_label(self.dir, int((WALL0 + 23.0) * 1000), "nojump", "review")
        path = os.path.join(self.dir, groundtruth.LABELS_FILE)
        with open(path, "a") as f:
            f.write("13:33:25,nojump")          # old format, no trailing newline (crash mid-write)
        labels = imu.read_labels(path, day_start=WALL0 - (WALL0 % 86400))
        self.assertEqual(["jump", "nojump", "nojump"], [x["label"] for x in labels])
        self.assertAlmostEqual(WALL0 + 3.0, labels[0]["t"], places=3)
        self.assertEqual("review", labels[0]["source"])
        self.assertEqual("file", labels[2]["source"])
        with open(path) as f:
            self.assertEqual("wall_ms,label,source\n", f.readline())
        groundtruth.append_label(self.dir, int((WALL0 + 40.0) * 1000), "jump", "review")   # repairs the missing newline
        self.assertEqual(4, len(imu.read_labels(path, day_start=0)))

    def test_review_beats_button_on_the_same_flight(self):
        flights = [{"t": WALL0 + 3.0, "air": 0.25}]
        labels = [
            {"t": WALL0 + 8.0, "label": "jump", "kind": "marker", "source": "button"},
            {"t": WALL0 + 3.1, "label": "nojump", "kind": "file", "source": "review"},
        ]
        pairs = groundtruth.resolve(flights, labels)
        self.assertEqual(1, len(pairs))
        self.assertEqual("nojump", pairs[0][1]["label"])

    def test_nojump_marker_without_flight_is_dropped(self):
        pairs = groundtruth.resolve([], [{"t": WALL0, "label": "nojump", "kind": "marker", "source": "button"}])
        self.assertEqual([], pairs)


class MarkerLabelLoadTest(unittest.TestCase):
    def test_events_jsonl_marker_label_and_default(self):
        from mtbdyn.loaders import load_karoo_dir
        d = tempfile.mkdtemp()
        _write_min_ride(d, [
            {"marker": {"n": 1, "wallMs": int(WALL0 * 1000), "offsetSec": 1.0}},
            {"marker": {"n": 2, "wallMs": int(WALL0 * 1000) + 5000, "offsetSec": 6.0, "label": "nojump"}},
        ])
        ride = load_karoo_dir(d)
        self.assertEqual(["jump", "nojump"], [m["label"] for m in ride.markers])
        labels = imu.labels_for(ride, None, 0)
        self.assertEqual(["button", "button"], [x["source"] for x in labels])
        self.assertEqual(["jump", "nojump"], [x["label"] for x in labels])

    def test_labels_csv_in_ride_folder_is_read_automatically(self):
        from mtbdyn.loaders import load_karoo_dir
        d = tempfile.mkdtemp()
        _write_min_ride(d, [])
        groundtruth.append_label(d, int((WALL0 + 4) * 1000), "nojump", "review")
        labels = imu.labels_for(load_karoo_dir(d), None, 0)
        self.assertEqual([("nojump", "review")], [(x["label"], x["source"]) for x in labels])

    def test_fit_marker_label_field(self):
        from mtbdyn.loaders import _markers_from_fit
        ev = [{"event": "user_marker", "timestamp": WALL0, "developer_fields": {1: 1}},
              {"event": "user_marker", "timestamp": WALL0 + 5, "developer_fields": {}}]
        names = {1: "mtb_marker_label"}
        out = _markers_from_fit(ev, lambda m: {names.get(k, str(k)): v for k, v in (m.get("developer_fields") or {}).items()})
        self.assertEqual(["nojump", "jump"], [m["label"] for m in out])


class CandidatesTest(unittest.TestCase):
    def test_thresholds_match_presets_and_verdict_order(self):
        th = imu.preset_thresholds("MEDIUM")
        self.assertEqual((0.45, 0.28, 1.15, imu.MAX_MEAN_AIR_G), (th.takeoff_g, th.min_air, th.min_landing_g, th.max_mean_air_g))
        fl = {"air": 0.25, "mean_g": 0.3, "landing_g": 3.0}
        self.assertTrue(imu.verdict(fl, th, 6.0).startswith("airtime"))
        self.assertEqual("", imu.verdict(fl, imu.preset_thresholds("HIGH"), 6.0))
        self.assertTrue(imu.verdict(fl, imu.preset_thresholds("HIGH"), 1.0).startswith("speed"))

    def test_candidates_include_short_flights_and_per_preset_verdicts(self):
        from test_labels import write_imu
        d = tempfile.mkdtemp()
        p = os.path.join(d, "imu.csv.gz")
        write_imu(p)                                     # 0.6 s jump at 3 s, 0.25 s hop at 23 s
        accel, _ = imu.load_imu(p)
        ride = Ride(samples=[Sample(t=WALL0 + i, speed=6.0, lat=35.0, lon=33.0) for i in range(30)])
        cands = groundtruth.candidates(ride, accel)
        self.assertEqual(2, len(cands))
        hop = cands[1]
        self.assertEqual("", hop["verdicts"]["HIGH"])
        self.assertTrue(hop["verdicts"]["MEDIUM"].startswith("airtime"))
        slow = Ride(samples=[Sample(t=WALL0 + i, speed=1.0) for i in range(30)])
        self.assertEqual([], groundtruth.candidates(slow, accel))   # below take-off speed: never a candidate

    def test_spots_group_passes_within_15_m(self):
        a = {"t": 1, "lat": 35.0, "lon": 33.0}
        b = {"t": 2, "lat": 35.00005, "lon": 33.0}       # ~5.5 m north
        c = {"t": 3, "lat": 35.001, "lon": 33.0}         # ~111 m north
        groups = groundtruth.spots([a, b, c])
        self.assertEqual([[1, 2], [3]], [[x["t"] for x in g] for g in groups])
        nopos = [{"t": 1, "lat": None, "lon": None}, {"t": 2, "lat": None, "lon": None}]
        self.assertEqual([[1], [2]], [[x["t"] for x in g] for g in groundtruth.spots(nopos)])


class ReviewTest(unittest.TestCase):
    def _ride(self):
        from test_labels import write_imu
        d = tempfile.mkdtemp()
        write_imu(os.path.join(d, "imu.csv.gz"))
        ride = Ride(samples=[Sample(t=WALL0 + i, speed=6.0, lat=35.0 + i * 0.001, lon=33.0) for i in range(30)])
        ride.folder = d
        accel, _ = imu.load_imu(os.path.join(d, "imu.csv.gz"))
        return ride, d, accel

    def test_review_writes_each_answer_and_skips_labelled_on_rerun(self):
        ride, d, accel = self._ride()
        answers = iter(["J", "q"])
        n = groundtruth.review(ride, d, accel, ask=lambda _p: next(answers), out=lambda *_a: None)
        self.assertEqual(1, n)
        answers = iter(["N"])
        n = groundtruth.review(ride, d, accel, ask=lambda _p: next(answers), out=lambda *_a: None)
        self.assertEqual(1, n)                         # only the second flight was left
        labels = imu.read_labels(os.path.join(d, "labels.csv"), 0)
        self.assertEqual(["jump", "nojump"], [x["label"] for x in labels])
        self.assertEqual({"review"}, {x["source"] for x in labels})

    def test_review_label_each_pass(self):
        ride, d, accel = self._ride()
        ride.samples = [Sample(t=WALL0 + i, speed=6.0, lat=35.0, lon=33.0) for i in range(30)]   # one spot, 2 passes
        answers = iter(["e", "j", "n"])
        self.assertEqual(2, groundtruth.review(ride, d, accel, ask=lambda _p: next(answers), out=lambda *_a: None))
        self.assertEqual(["jump", "nojump"], [x["label"] for x in imu.read_labels(os.path.join(d, "labels.csv"), 0)])

    def test_dump_has_an_empty_label_column_and_no_positions(self):
        ride, d, accel = self._ride()
        path = os.path.join(d, "candidates.csv")
        self.assertEqual(2, groundtruth.dump_candidates(ride, accel, path))
        with open(path) as f:
            head = f.readline().strip().split(",")
            row = f.readline().strip().split(",")
        self.assertEqual("label", head[1])
        self.assertEqual("", row[1])
        self.assertNotIn("lat", head)
        self.assertEqual([], imu.read_labels(path, 0))   # unfilled rows are not labels

    def test_cli_review_without_imu_log_exits_cleanly(self):
        from mtbdyn.cli import main
        d = tempfile.mkdtemp()
        _write_min_ride(d, [])
        self.assertEqual(0, main(["--karoo-dir", d, "--review", "--quiet"]))


if __name__ == "__main__":
    unittest.main()
