"""Mount calibration, in-flight rotation and barometric drop (mirrors of MountCalibrator.kt and PressureTrack.kt)."""
import gzip
import math
import os
import random
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from mtbdyn import mount  # noqa: E402

TILT = math.radians(13.0)
FORWARD = [0.0, -math.cos(TILT), -math.sin(TILT)]
UP = [0.0, -math.sin(TILT), math.cos(TILT)]
LEFT = mount._cross(UP, FORWARD)


def sensor(fwd, left, up):
    return [FORWARD[k] * fwd + LEFT[k] * left + UP[k] * up for k in range(3)]


def angle_deg(a, b):
    return math.degrees(math.acos(max(-1.0, min(1.0, mount._dot(a, b)))))


class MountTest(unittest.TestCase):
    def ride(self, cal, seconds, noise=1.0):
        rnd = random.Random(11)
        for i in range(seconds):
            v, yaw = 6.0, 0.4 * math.sin(i / 5.0)
            a = sensor(-2.0 if i % 7 == 0 else 0.0, v * yaw, mount.G)
            cal.on_second([c + rnd.gauss(0, noise) for c in a], yaw, v)

    def test_finds_the_forward_axis_from_corners(self):
        cal = mount.MountCalibrator()
        self.ride(cal, 600)
        self.assertLess(angle_deg(cal.forward, FORWARD), 5.0)
        self.assertGreater(cal.agreement, 0.3)

    def test_needs_enough_corner_seconds(self):
        cal = mount.MountCalibrator()
        self.ride(cal, 40)
        self.assertIsNone(cal.forward)

    def test_straight_riding_does_not_calibrate(self):
        cal = mount.MountCalibrator()
        for _ in range(600):
            cal.on_second(sensor(0.5, 0.0, mount.G), 0.0, 6.0)
        self.assertEqual(cal.corners, 0)
        self.assertIsNone(cal.forward)

    def test_flight_rotation_along_the_bike(self):
        nose, turn = math.radians(12.0), math.radians(-20.0)
        rate = [(LEFT[k] * nose + UP[k] * turn) / 0.3 for k in range(3)]   # constant over a 0.3 s flight
        gyro = [(10.0 + i * 0.01, *rate) for i in range(31)]
        r = mount.flight_rotation(gyro, 10.0, 10.3, FORWARD, UP)
        self.assertAlmostEqual(r["pitch"], 12.0, delta=0.1)
        self.assertAlmostEqual(r["yaw"], -20.0, delta=0.1)
        self.assertAlmostEqual(r["roll"], 0.0, delta=0.1)
        self.assertIsNone(mount.flight_rotation(gyro, 10.0, 10.3, None, UP))


class BaroTest(unittest.TestCase):
    def pressure(self, drop_m, noise=0.03):
        rnd, out, t = random.Random(3), [], 0.0
        while t < 14.0:
            alt = 0.0 if t < 10.0 else -drop_m
            out.append((t, 980.0 - 0.1176 * alt + rnd.gauss(0, noise), 0.0, 0.0))
            t += 0.075
        return out

    def test_a_1_m_drop(self):
        self.assertAlmostEqual(mount.baro_drop(self.pressure(1.0), 10.0, 10.6), 1.0, delta=0.25)

    def test_flat(self):
        self.assertAlmostEqual(mount.baro_drop(self.pressure(0.0), 10.0, 10.6), 0.0, delta=0.25)

    def test_no_samples(self):
        self.assertIsNone(mount.baro_drop([], 10.0, 10.6))

    def test_formula(self):
        self.assertAlmostEqual(mount.altitude_m(1013.25), 0.0)
        self.assertAlmostEqual(mount.altitude_m(1000.0), 110.9, delta=0.2)


class LoadSensorsTest(unittest.TestCase):
    def test_reads_every_sensor(self):
        with tempfile.NamedTemporaryFile(suffix=".csv.gz", delete=False) as f:
            path = f.name
        try:
            with gzip.open(path, "wt") as g:
                g.write("# wall_ms=1790000000000 elapsed_ms=1000\nsensor,elapsed_ms,x,y,z\n")
                g.write("a,1000.00,0.1,0.2,9.8\ng,1010.00,0.0,0.0,0.1\np,1020.00,997.7800,0.0,0.0\n")
            s = mount.load_sensors(path)
            self.assertEqual([len(s[k]) for k in "agp"], [1, 1, 1])
            self.assertAlmostEqual(s["p"][0][0], 1790000000.02)
            self.assertAlmostEqual(s["p"][0][1], 997.78)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
