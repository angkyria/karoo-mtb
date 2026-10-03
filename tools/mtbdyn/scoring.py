"""Grit / Flow / score formulas (mirror of Scoring.kt) and physical constants."""
from __future__ import annotations

import math

G = 9.80665
SEMICIRCLE_TO_DEG = 180.0 / 2 ** 31
FIT_EPOCH_OFFSET = 631065600  # seconds from 1970-01-01 to 1989-12-31

# --------------------------------------------------------------------------------------------
# Formulas (mirror of Scoring.kt)
# --------------------------------------------------------------------------------------------
MOVING_SPEED = 1.0
GRIT_SCALE, GRIT_W_GRADE, GRIT_W_TURN, GRIT_W_ROUGH = 1.25, 1.2, 1.0, 1.0
CRR, AIR_K = 0.02, 0.0035
BRAKE_MIN, BRAKE_FULL, BRAKING_THRESHOLD = 0.3, 1.5, 0.5
DESCENT_GRADE = -2.5
MAX_LATERAL_G = 1.5
DEFAULT_FLOW_LAG = 3
WINDOW = 60


def _nz(v: float | None) -> float:
    return 0.0 if v is None or isinstance(v, float) and math.isnan(v) else v


def grade_term(grade: float | None) -> float:
    return min(8.0, (abs(_nz(grade)) / 8.0) ** 1.6)


def turn_term(curvature: float | None) -> float:
    return min(6.0, (max(0.0, _nz(curvature)) * 15.0) ** 1.3)


def rough_term(rough: float | None) -> float:
    if rough is None or math.isnan(rough):
        return 0.0
    return min(6.0, (max(0.0, rough) / 0.6) ** 1.3)


def grit_per_second(grade, curvature, rough) -> float:
    return GRIT_SCALE * (1.0 + GRIT_W_GRADE * grade_term(grade) + GRIT_W_TURN * turn_term(curvature)
                         + GRIT_W_ROUGH * rough_term(rough))


def coasting_accel(speed: float, grade: float | None) -> float:
    theta = math.atan(_nz(grade) / 100.0)
    return -G * math.sin(theta) - CRR * G * math.cos(theta) - AIR_K * speed * speed


def braking_decel(observed: float, speed: float, grade) -> float:
    # Downhill only real slowing counts; flat/uphill: slowing beyond gravity + resistance.
    return max(0.0, min(0.0, coasting_accel(speed, grade)) - observed)


def brake_weight(decel: float) -> float:
    return min(1.0, max(0.0, (decel - BRAKE_MIN) / (BRAKE_FULL - BRAKE_MIN)))


def braking_necessity(speed: float, curvature, grade, rough) -> float:
    k = max(0.0, _nz(curvature))
    lateral = speed * speed * k
    n_lat = min(1.0, max(0.0, (lateral - 1.5) / 3.0))
    n_rad = min(1.0, max(0.0, (k - 1 / 20.0) / (1 / 6.0 - 1 / 20.0)))
    n_grade = min(1.0, max(0.0, (-_nz(grade) - 6.0) / 12.0))
    n_rough = 0.0 if rough is None or math.isnan(rough) else min(1.0, max(0.0, (rough - 1.0) / 1.0))
    return max(n_lat, n_rad, n_grade, n_rough)


def flow_score(flow_m: float, dist_m: float) -> float:
    return 0.0 if dist_m < 1.0 else 100.0 * flow_m / dist_m


def difficulty_score(avg_grit: float) -> float:
    return 100.0 * (1.0 - math.exp(-max(0.0, avg_grit - GRIT_SCALE) / 3.5))


def smoothness_score(flow: float) -> float:
    return 100.0 * math.exp(-max(0.0, flow) / 6.0)


def air_score(total_air: float) -> float:
    return 100.0 * (1.0 - math.exp(-max(0.0, total_air) / 6.0))


def mtb_score(d: float, s: float, a: float) -> float:
    return 0.45 * d + 0.40 * s + 0.15 * a


def jump_height(air: float, drop: float = 0.0) -> float:
    if air <= 0:
        return 0.0
    vz0 = (G * air * air / 2.0 - drop) / air
    apex = vz0 * vz0 / (2 * G) if vz0 > 0 else 0.0
    return apex + max(0.0, drop)
