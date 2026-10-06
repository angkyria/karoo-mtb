"""Corpus, fit and fixture export."""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from test_labels import WALL0, write_imu  # noqa: E402

from mtbdyn import groundtruth, tune  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
