"""Data model: one-second samples, jumps and a ride."""
from __future__ import annotations

from dataclasses import dataclass, field

from .scoring import BRAKING_THRESHOLD, DEFAULT_FLOW_LAG, DESCENT_GRADE, MOVING_SPEED, _nz


# --------------------------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------------------------
@dataclass
class Sample:
    t: float                     # epoch seconds
    dt: float = 1.0
    dist: float = 0.0            # cumulative metres
    d_dist: float = 0.0
    speed: float = 0.0
    alt: float | None = None
    lat: float | None = None
    lon: float | None = None
    grade: float | None = None
    hr: float | None = None
    power: float | None = None
    grit: float | None = None    # grit points this second
    flow: float | None = None    # unnecessary-braking metres this second (aligned)
    rough: float | None = None   # g
    lat_g: float | None = None   # g
    brake: float | None = None   # m/s² (aligned)
    curvature: float | None = None
    yaw: float | None = None     # rad/s, + = left
    jump_air: float = 0.0
    jump_dist: float = 0.0
    jump_height: float = 0.0
    lap: int = 0
    # SRAM / RockShox (Karoo records these when the components are paired)
    cadence: float | None = None
    balance: float | None = None   # left %, power meter estimate
    fa_front: int | None = None    # Flight Attendant fork: 0 Open, 1 Pedal, 2 Lock
    fa_rear: int | None = None
    effort_zone: int | None = None
    rear_gear: int | None = None   # 1 = largest (easiest) cog
    rear_teeth: int | None = None

    @property
    def moving(self) -> bool:
        return self.speed >= MOVING_SPEED

    @property
    def descending(self) -> bool:
        return self.moving and _nz(self.grade) <= DESCENT_GRADE

    @property
    def braking(self) -> bool:
        return self.moving and (self.brake or 0.0) >= BRAKING_THRESHOLD


@dataclass
class Jump:
    n: int
    t: float                 # take-off, epoch seconds
    air: float
    distance: float
    height: float
    speed: float
    drop: float | None = None
    landing_g: float | None = None
    rotations: int = 0
    score: float | None = None
    lat: float | None = None
    lon: float | None = None


@dataclass
class Ride:
    samples: list[Sample]
    jumps: list[Jump] = field(default_factory=list)
    lap_starts: list[int] = field(default_factory=lambda: [0])
    session: dict = field(default_factory=dict)
    source: str = ""
    device: str = ""
    has_imu: bool = False          # roughness / jumps measured with the accelerometer
    estimated: bool = False        # grit / flow estimated from GPS + altitude
    flow_lag: int = DEFAULT_FLOW_LAG
    karoo_summary: dict | None = None
    karoo_corners: list[dict] | None = None   # gyroscope corners from a Karoo ride folder
    shifts: list[dict] = field(default_factory=list)    # {t, gear, teeth, from_teeth, power, cadence}
    devices: list[dict] = field(default_factory=list)   # SRAM components with battery level
    fa_mode: int | None = None
    fa_bias: int | None = None
    cassette: list[int] | None = None
    weight: float | None = None                          # rider kg, for W/kg

    @property
    def start(self) -> float:
        return self.samples[0].t if self.samples else 0.0
