"""Trail mode: the roughness schedule (TrailMode.kt) and the trail gates in find_flights (JumpDetector.kt)."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from mtbdyn import imu  # noqa: E402
from mtbdyn.model import Ride, Sample  # noqa: E402

G = 9.80665


def _ride(roughs):
    return Ride(samples=[Sample(t=float(i), rough=r) for i, r in enumerate(roughs)])


def _hop(t0, air, air_g=0.3, rate=100):
    """|a| profile: 1 g, a flight of `air` s at `air_g`, a 3 g landing, 1 g again (as accel tuples)."""
    out, t = [], 0.0
    while t < t0 + air + 2.0:
        if t0 <= t < t0 + air:
            g = air_g
        elif t0 + air <= t < t0 + air + 0.06:
            g = 3.0
        else:
            g = 1.0
        out.append((t, 0.0, 0.0, g * G))
        t += 1.0 / rate
    return out


class TrailScheduleTest(unittest.TestCase):
    def test_road_is_not_a_trail(self):
        at = imu.trail_schedule(_ride([0.3] * 60))
        self.assertFalse(at(59))

    def test_sustained_roughness_is_a_trail(self):
        at = imu.trail_schedule(_ride([1.3] * 30))
        self.assertFalse(at(5))     # not enough seconds yet
        self.assertTrue(at(29))

    def test_rough_patch_on_the_road_is_ignored(self):
        at = imu.trail_schedule(_ride([0.3] * 25 + [1.8] * 5))
        self.assertFalse(at(29))

    def test_missing_roughness_is_skipped(self):
        at = imu.trail_schedule(_ride([1.3] * 30 + [None] * 30))
        self.assertTrue(at(59))

    def test_no_roughness_no_schedule(self):
        self.assertIsNone(imu.trail_schedule(_ride([None] * 10)))
        self.assertIsNone(imu.trail_schedule(None))


class TrailGatesTest(unittest.TestCase):
    def test_short_hop_counts_only_on_a_trail(self):
        accel = _hop(40.0, 0.19)
        road = imu.find_flights(accel, "HIGH", lambda t: False)
        trail = imu.find_flights(accel, "HIGH", lambda t: True)
        self.assertEqual([f["reason"] != "" for f in road], [True])
        self.assertEqual([f["reason"] for f in trail], [""])
        self.assertTrue(trail[0]["trail"])

    def test_without_schedule_presets_are_unchanged(self):
        accel = _hop(40.0, 0.19)
        self.assertNotEqual(imu.find_flights(accel, "HIGH")[0]["reason"], "")

    def test_trail_gates_are_wider_than_the_preset(self):
        for name in imu.PRESETS:
            base, trail = imu.preset_thresholds(name), imu.trail_thresholds(name)
            self.assertGreater(trail.takeoff_g, base.takeoff_g)
            self.assertLess(trail.min_air, base.min_air)
            self.assertGreater(trail.max_mean_air_g, base.max_mean_air_g)
            self.assertEqual(trail.min_landing_g, base.min_landing_g)


if __name__ == "__main__":
    unittest.main()
