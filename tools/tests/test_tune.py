"""Corpus, fit and fixture export."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from test_labels import WALL0, write_imu  # noqa: E402

from mtbdyn import groundtruth, imu, tune  # noqa: E402
from mtbdyn.model import Ride, Sample  # noqa: E402


def labelled_ride(d, jump_label="jump", hop_label="nojump"):
    write_imu(os.path.join(d, "imu.csv.gz"))
    ride = Ride(samples=[Sample(t=WALL0 + i, speed=6.0, lat=35.0 + i * 0.001, lon=33.0) for i in range(30)])
    ride.folder = d
    groundtruth.append_label(d, int((WALL0 + 3.0) * 1000), jump_label, "review")
    groundtruth.append_label(d, int((WALL0 + 23.0) * 1000), hop_label, "review")
    return ride


class CorpusTest(unittest.TestCase):
    def test_add_is_idempotent_and_label_changes_replace(self):
        d, corpus = tempfile.mkdtemp(), tempfile.mkdtemp()
        ride = labelled_ride(d)
        self.assertEqual(2, tune.add_ride(ride, os.path.join(d, "imu.csv.gz"), corpus))
        self.assertEqual(2, tune.add_ride(ride, os.path.join(d, "imu.csv.gz"), corpus))
        clips = tune.load_corpus(corpus)
        self.assertEqual(2, len(clips))
        self.assertEqual({"jump", "nojump"}, {c["label"] for c in clips})
        groundtruth.append_label(d, int((WALL0 + 23.0) * 1000), "jump", "review")   # changed my mind
        tune.add_ride(ride, os.path.join(d, "imu.csv.gz"), corpus)
        self.assertEqual({"jump"}, {c["label"] for c in tune.load_corpus(corpus)})

    def test_clips_carry_no_position_or_date(self):
        d, corpus = tempfile.mkdtemp(), tempfile.mkdtemp()
        tune.add_ride(labelled_ride(d), os.path.join(d, "imu.csv.gz"), corpus)
        for name in os.listdir(corpus):
            with open(os.path.join(corpus, name)) as f:
                text = f.read()
            self.assertNotIn("35.0", text)
            self.assertNotIn("lat", text)
            self.assertNotIn("wall_ms", text)

    def test_cli_corpus_without_imu_log_exits_cleanly(self):
        from test_groundtruth import _write_min_ride

        from mtbdyn.cli import main
        d, corpus = tempfile.mkdtemp(), tempfile.mkdtemp()
        _write_min_ride(d, [])
        self.assertEqual(0, main(["--karoo-dir", d, "--corpus", corpus, "--quiet"]))
        self.assertEqual([], os.listdir(corpus))


def synthetic_corpus(corpus, rides=3, per_ride=8):
    """Jumps of 0.40-0.575 s air vs 0.18-0.25 s rollers: separable, the right minAirSec lies in (0.26, 0.40)."""
    import make_imu_fixtures
    os.makedirs(corpus, exist_ok=True)
    for r in range(rides):
        for k in range(per_ride):
            for label, air in (("jump", 0.40 + 0.2 * k / per_ride), ("nojump", 0.18 + 0.08 * k / per_ride)):
                rows = make_imu_fixtures.ride(7.0, (3.0, air), 3.0 if label == "jump" else 1.8, 0.05, seed=r * 100 + k)
                base = f"{r}_{k}_{label}"
                imu.write_snippet(os.path.join(corpus, base + ".csv"), rows, {"label": label})
                with open(os.path.join(corpus, base + ".json"), "w") as f:
                    json.dump({"file": base + ".csv", "label": label, "source": "review", "speed": 6.0,
                               "rate_hz": 100, "ride": str(r), "spot": f"{r}:{k}:{label}", "air": air}, f)


class FitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = tempfile.mkdtemp()
        synthetic_corpus(cls.corpus)
        cls.result = tune.fit(cls.corpus, out=lambda *_a: None)

    def test_guard_with_too_few_labels_proposes_nothing(self):
        corpus = tempfile.mkdtemp()
        synthetic_corpus(corpus, rides=1, per_ride=3)
        lines = []
        self.assertIsNone(tune.fit(corpus, out=lines.append))
        self.assertTrue(any("need" in x for x in lines), lines)
        self.assertFalse(os.path.exists(os.path.join(corpus, "fit-result.json")))

    def test_empty_corpus_hits_the_guard(self):
        lines = []
        self.assertIsNone(tune.fit(tempfile.mkdtemp(), out=lines.append))
        self.assertTrue(any("need" in x for x in lines), lines)

    def test_fit_finds_the_gap_and_meets_targets(self):
        med = self.result["proposed"]["MEDIUM"]
        self.assertTrue(0.26 < med["minAirSec"] < 0.40, med)
        self.assertGreaterEqual(self.result["validation"]["MEDIUM"]["precision"], 0.95)
        self.assertGreaterEqual(self.result["validation"]["MEDIUM"]["recall"], 0.9)
        with open(os.path.join(self.corpus, "fit-result.json")) as f:
            saved = json.load(f)
        self.assertEqual(48, len(saved["clips"]))
        self.assertEqual({"LOW", "MEDIUM", "HIGH"}, set(saved["clips"][0]["verdicts"]))

    def test_margin_tie_break_picks_the_middle_of_the_gap(self):
        self.assertAlmostEqual(0.33, self.result["proposed"]["MEDIUM"]["minAirSec"], delta=0.035)

    def test_thresholds_that_do_not_matter_stay_at_the_current_preset(self):
        med = self.result["proposed"]["MEDIUM"]
        self.assertEqual(1.15, med["minLandingG"])    # only airtime separates this corpus
        # (takeoffG may move: it changes the measured airtime, so the margin legitimately differs per take-off threshold)
        self.assertEqual(imu.MAX_MEAN_AIR_G, self.result["jumpMaxMeanAirG"])
        self.assertEqual(1.3, self.result["proposed"]["LOW"]["minLandingG"])

    def test_export_picks_boundary_clips_with_per_preset_expect(self):
        out = tempfile.mkdtemp()
        written = tune.export_fixtures(self.corpus, self.result, out, limit=6)
        with open(os.path.join(out, "manifest.json")) as f:
            fx = json.load(f)["fixtures"]
        self.assertLessEqual(len(fx), 6)
        self.assertIn("manifest.json", written)
        self.assertEqual({"LOW", "MEDIUM", "HIGH"}, set(fx[0]["expect"]))
        airs = sorted(x["airSec"] for x in fx)
        self.assertTrue(any(a < 0.30 for a in airs) and any(a > 0.38 for a in airs), airs)   # both sides of the boundary
        for e in fx:
            self.assertRegex(e["file"], r"^real_\d{3}_(jump|nojump)\.csv$")       # no ride id or time in the name
            with open(os.path.join(out, e["file"])) as f:
                self.assertTrue(f.readline().startswith("# label="))

    def test_cli_fit_with_export(self):
        from mtbdyn.cli import main
        out = tempfile.mkdtemp()
        self.assertEqual(0, main(["--fit", self.corpus, "--export-fixtures", out]))
        self.assertTrue(os.path.exists(os.path.join(out, "manifest.json")))

    def test_spot_weights_share_one_feature(self):
        self.assertEqual([0.5, 0.5, 1.0], tune.weights([{"spot": "a"}, {"spot": "a"}, {"spot": "b"}]))


if __name__ == "__main__":
    unittest.main()
