"""Jump pins: passes over each pin and the Karoo's verdict (testdata/pins_fixture.json, shared with pins.test.mjs)."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from mtbdyn import pins  # noqa: E402

FIXTURE = os.path.join(HERE, "..", "..", "testdata", "pins_fixture.json")


class PinsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURE) as f:
            cls.fx = json.load(f)

    def report(self):
        fx = self.fx
        return pins.ride_report([tuple(p) for p in fx["track"]], [tuple(j) for j in fx["jumps"]], fx["pins"])

    def test_fixture(self):
        r, want = self.report(), self.fx["expected"]
        for key in ("jump_passes", "counted", "nojump_counted", "elsewhere"):
            self.assertEqual(r[key], want[key], key)
        got = [{"pin": p["pin"], "t": round(p["t"] - self.fx["t0"], 6), "d": round(p["d"], 6), "jump": p["jump"]} for p in r["passes"]]
        self.assertEqual(got, want["passes"])

    def test_passes_closer_than_the_gap_are_one(self):
        fx = self.fx
        c = [p for p in self.report()["passes"] if p["pin"] == 2]
        self.assertEqual(len(c), 1)   # out and back over the turn-around pin within 20 s
        self.assertEqual(pins.passes([tuple(p) for p in fx["track"]], fx["pins"][3]), [])

    def test_a_jump_counts_one_pass_only(self):
        fx = self.fx
        t0 = fx["t0"]
        r = pins.ride_report([tuple(p) for p in fx["track"]], [(1, t0 + 10.5), (2, t0 + 10.6)], fx["pins"][:1])
        self.assertEqual(r["counted"], 1)
        self.assertEqual(r["elsewhere"], [2])

    def test_load_pins_keeps_labelled_spots(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"spots": [{"lat": 35, "lon": 33, "label": "jump"}, {"lat": 35, "lon": 33, "label": "?"}], "detections": {}}, f)
        try:
            self.assertEqual(len(pins.load_pins(f.name)), 1)
        finally:
            os.unlink(f.name)


if __name__ == "__main__":
    unittest.main()
