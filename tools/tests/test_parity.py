"""The analyser's formulas must match testdata/scoring_vectors.json (Scoring.kt is checked against the same file)."""
import json
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from mtbdyn import imu, scoring  # noqa: E402

VECTORS = os.path.join(HERE, "..", "..", "testdata", "scoring_vectors.json")

FUNCTIONS = {
    "gritPerSecond": scoring.grit_per_second,
    "brakingDecel": scoring.braking_decel,
    "brakeWeight": scoring.brake_weight,
    "brakingNecessity": scoring.braking_necessity,
    "flowScore": scoring.flow_score,
    "difficultyScore": scoring.difficulty_score,
    "smoothnessScore": scoring.smoothness_score,
    "airScore": scoring.air_score,
    "mtbScore": scoring.mtb_score,
    "jumpHeight": scoring.jump_height,
}


class ParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(VECTORS) as f:
            cls.data = json.load(f)

    def test_formulas_match_vectors(self):
        seen = set()
        for case in self.data["cases"]:
            fn = FUNCTIONS[case["fn"]]
            got = fn(*case["args"])
            self.assertTrue(math.isclose(got, case["expected"], rel_tol=1e-9, abs_tol=1e-12),
                            f"{case['fn']}{tuple(case['args'])} = {got}, vectors say {case['expected']}")
            seen.add(case["fn"])
        self.assertEqual(set(FUNCTIONS), seen)

    def test_constants_match_vectors(self):
        c = self.data["constants"]
        mine = {
            "G": scoring.G, "MOVING_SPEED": scoring.MOVING_SPEED, "GRIT_SCALE": scoring.GRIT_SCALE,
            "GRIT_W_GRADE": scoring.GRIT_W_GRADE, "GRIT_W_TURN": scoring.GRIT_W_TURN, "GRIT_W_ROUGH": scoring.GRIT_W_ROUGH,
            "CRR": scoring.CRR, "AIR_K": scoring.AIR_K, "BRAKE_MIN": scoring.BRAKE_MIN, "BRAKE_FULL": scoring.BRAKE_FULL,
            "BRAKING_THRESHOLD": scoring.BRAKING_THRESHOLD, "DESCENT_GRADE": scoring.DESCENT_GRADE,
            "MAX_LATERAL_G": scoring.MAX_LATERAL_G, "FLOW_LAG": scoring.DEFAULT_FLOW_LAG,
            "JUMP_LAND_G": imu.LAND_G, "JUMP_MAX_AIR": imu.MAX_AIR, "JUMP_MAX_MEAN_AIR_G": imu.MAX_MEAN_AIR_G,
            "JUMP_GLITCH": imu.GLITCH, "JUMP_LANDING_WINDOW": imu.LANDING_WINDOW, "JUMP_COOLDOWN": imu.COOLDOWN,
            "JUMP_MIN_SPEED": imu.MIN_JUMP_SPEED,
        }
        self.assertEqual(mine, c)
        presets = {n: {"takeoffG": t, "minAirSec": a, "minLandingG": land} for n, (t, a, land) in imu.PRESETS.items()}
        self.assertEqual(presets, self.data["presets"])


if __name__ == "__main__":
    unittest.main()
