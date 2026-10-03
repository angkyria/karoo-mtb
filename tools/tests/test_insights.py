"""Post-ride insights (mirror of InsightsTest.kt)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from mtbdyn import insights  # noqa: E402
from mtbdyn.model import Ride, Sample  # noqa: E402


def lap(index, distance, seconds, flow):
    return {"index": index, "distance_m": distance, "duration_s": seconds, "flow_score": flow}


class InsightsTest(unittest.TestCase):
    def test_lap_comparison(self):
        laps = [lap(1, 3000, 200, 1.0), lap(2, 3050, 195, 0.6), lap(3, 2980, 190, 0.8),
                lap(4, 3010, 205, 0.9), lap(5, 3020, 215, 1.1), lap(6, 3000, 220, 1.2), lap(7, 900, 60, 0.1)]
        c = insights.lap_comparison(laps)
        self.assertEqual((6, 7, 3, 2), (c["comparable"], c["laps"], c["fastest_lap"], c["smoothest_lap"]))
        self.assertAlmostEqual(10.1, c["trend_pct"], delta=0.2)
        self.assertIsNone(insights.lap_comparison(laps[:1]))

    def test_braking_spots(self):
        samples = []
        dist = 0.0
        for i in range(200):
            flow = 2.0 if 50 <= i < 54 else 1.5 if 120 <= i < 128 and i != 122 else 0.0
            speed = 3.0 if flow else 7.0
            dist += speed
            samples.append(Sample(t=1000.0 + i, dist=dist, d_dist=speed, speed=speed, flow=flow, lat=46.0, lon=8.0 + i * 1e-4))
        segments = [{"type": "DESCENT", "name": "Descent 1", "start_offset_s": 100.0, "duration_s": 60.0}]
        spots = insights.braking_spots(Ride(samples=samples), segments)
        self.assertEqual(2, len(spots))
        self.assertEqual("Descent 1", spots[0]["segment"])   # 7 x 1.5 m beats 4 x 2 m (the 1 s gap is joined)
        self.assertAlmostEqual(10.5, spots[0]["flow_m"])
        self.assertIsNone(spots[1]["segment"])
        self.assertEqual(7.0, spots[0]["speed_before_ms"])

    def test_corner_sides(self):
        def corner(angle, kept):
            return {"angle": angle, "entry": 5.0, "min": 5.0 * kept}
        corners = [corner(60, 0.96)] * 5 + [corner(-60, 0.88)] * 6
        left, right = insights.corner_sides(corners)
        self.assertAlmostEqual(96.0, left)
        self.assertAlmostEqual(88.0, right)
        self.assertEqual("You lose more speed in right-handers (88% vs 96% kept)", insights.corner_side_hint(left, right))
        self.assertIsNone(insights.corner_sides(corners[1:])[0])


if __name__ == "__main__":
    unittest.main()


class TrailsJsonTest(unittest.TestCase):
    def test_trails_text(self):
        import json
        import tempfile

        from mtbdyn.history import trails_text
        from mtbdyn.report import Units
        state = {"schema": 1, "nextId": 3, "trails": [
            {"id": 1, "name": "Dragon", "distanceM": 1250.0, "dropM": 140.0, "track": [],
             "runs": [{"rideStartWallMs": 1790000000000, "timeSec": 212.0, "flowScore": 0.9, "brakingPct": 20, "jumps": 1, "avgSpeedMs": 6},
                      {"rideStartWallMs": 1790100000000, "timeSec": 198.0, "flowScore": 0.6, "brakingPct": 18, "jumps": 2, "avgSpeedMs": 6.3}]},
            {"id": 2, "name": "Trail 2", "distanceM": 800.0, "dropM": 60.0, "track": [], "runs": []},
        ]}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(state, f)
        text = trails_text(f.name, Units())
        os.unlink(f.name)
        self.assertIn("Dragon", text)
        self.assertIn("2 runs", text)
        self.assertIn("best 3:18", text)
        self.assertIn("smoothest Flow 0.6", text)
        self.assertNotIn("Trail 2", text)
