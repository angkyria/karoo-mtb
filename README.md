# MTB Dynamics for Hammerhead Karoo 2 & Karoo 3

[![Build](https://github.com/angkyria/karoo-mtb/actions/workflows/build.yml/badge.svg)](https://github.com/angkyria/karoo-mtb/actions/workflows/build.yml)
[![Website](https://img.shields.io/badge/website-angkyria.github.io%2Fkaroo--mtb-ff6d00)](https://angkyria.github.io/karoo-mtb/)
![Status: testing](https://img.shields.io/badge/status-testing%20%2F%20debug-f9a825)

> [!WARNING]
> **Testing / debug builds (v0.2.0).** This runs on the developer's Karoo 2 and was calibrated
> with real rides. But there is no signed release yet, numbers can still change between versions,
> and parts of it have not been on a real ride yet (see [Testing status](#testing-status)).
> Please [report bugs](../../issues/new/choose) with logs: [Testing & debugging](#testing--debugging)
> shows how to collect them.

**Website with a demo ride report: <https://angkyria.github.io/karoo-mtb/>**

Garmin-style **MTB Dynamics** for the Karoo, built on Hammerhead's
[karoo-ext](https://github.com/hammerheadnav/karoo-ext) extension SDK:

* **Grit**: trail difficulty from gradient, elevation, turns and terrain roughness (ride, 60 s, lap)
* **Flow**: smoothness, i.e. how much you brake where the trail did not ask for it (ride, 60 s, lap; lower is better)
* **Jumps**: take-off → airborne → landing: count, airtime, distance, height, landing g, rotations
* **Jump records**: longest, farthest, highest jump and hardest landing
* **Cornering**: corners from the gyroscope, entry / apex / exit speed, lateral g, radius
* **Descending**: time, drop, speed, braking %, Flow and Grit on descents
* **MTB score**: 0-100 from difficulty, smoothness and airtime
* **Trail segments**: the ride split into climbs, descents and flat sections (plus your laps), with every metric per segment
* **Bike systems**: RockShox **Flight Attendant**, SRAM **AXS** shifting and the **power meter**, joined with the
  terrain: suspension coach, gear usage per terrain, power and pedalling per terrain, battery alerts
* **Service tracker**: fork / shock hours, chain kilometres, cog usage and battery history across rides, with reminders

When the ride ends, a summary goes to your phone over **[ntfy](https://ntfy.sh)**. Everything is
also written into the ride's **FIT file**, so intervals.icu, Garmin Connect, GoldenCheetah and the
included **analysis script** can use it.

```
MTB Dynamics · Trail · Mon 21 Sep 17:13

🚵 MTB score 70 · difficulty 61 · smoothness 94 · air 37

⛰️ Grit 10.0 kGrit · avg 5.9/s · peak 60 s 10.6
🌊 Flow 0.4 (lower = smoother) · descents 0.8 · worst 60 s 1.4
🪂 4 jumps · 2.8 s total airtime
  • Longest: 0.83 s · 6.2 m · 27.0 km/h
  • Farthest 6.2 m · highest ~0.8 m · hardest landing 3.0 g
↪️ 30 corners (16 L / 14 R) · max 0.79 g · speed kept 100%
⬇️ Descents 10:00 · 482 m ↓ · avg 22.9 km/h · braking 21%
〰️ Roughness avg 0.31 g

Trail segments
⬆️ Climb 1: 1.9 km · +152 m · 9:55 · Grit 2.3
⬇️ Descent 1: 2.0 km · −243 m · 5:12 · Flow 0.8 · brake 20% · 2 jumps
⬇️ Descent 2: 1.9 km · −235 m · 5:07 · Flow 0.7 · brake 20% · 2 jumps

⏱ 28:00 (moving 28:00) · 📏 8.1 km · ↗ 393 m · ⚡ 17.4 km/h avg
```
*(a synthetic test ride; the real message uses Markdown bold)*

With Flight Attendant, AXS and a power meter paired, the message gets a bike section (and service
reminders when something is due):

```
🔩 Flight Attendant descents 93% open · climbs 100% lock · opens 22 s into descents
⚙️ 2 shifts (0.7/km) · cogs 18–32T · climbs 32T
💪 Power climbs 230 W (3.1 W/kg) · pedalling on 1% of descents · best 5 min 230 W · L/R 47/53
🔋 FA fork low ⚠️ · AXS derailleur good

🛠️ Fork lower-leg service due · 50.3 h since the last one (every 50.0 h)
```

## Testing status

| Area | State |
|---|---|
| Extension, data fields, settings screen, alerts | ✅ runs on a Karoo 2 (Android 8.1) |
| Sensors | ✅ accelerometer and gyroscope at ~98 Hz |
| FIT file | ✅ `mtb_*` developer fields plus Garmin's native grit / flow / jump count |
| ntfy summary | ✅ delivered at ride end; retried for 7 days when offline |
| Grit, Flow, cornering | ✅ recalibrated on a real 2 h trail ride |
| Jump detection | 🟡 thresholds still need raw-sensor data from real jumps ([Tuning](#tuning)) |
| Flight Attendant / AXS / power meter (v0.2) | 🟡 tested with simulated streams, and the analyser on real rides; the first ride with the extension is pending |
| Service tracker (v0.2) | 🟡 unit-tested; needs real use over many rides |
| Karoo 3 | ⚪ not tested yet (same SDK, should work) |

54 Kotlin, 19 Python and 15 JavaScript tests run in CI on every push.

---

## Contents

1. [Install on the Karoo](#install-on-the-karoo) (test builds)
2. [ntfy ride summary](#ntfy-ride-summary)
3. [Data fields](#data-fields)
4. [Bike systems: Flight Attendant, AXS, power meter](#bike-systems-flight-attendant-axs-power-meter)
5. [Service tracker](#service-tracker)
6. [FIT file](#fit-file)
7. [intervals.icu](#intervalsicu)
8. [Analysis script](#analysis-script)
9. [How the metrics are calculated](#how-the-metrics-are-calculated)
10. [Tuning](#tuning) · [Testing & debugging](#testing--debugging)
11. [Building from source](#building-from-source) · [Website](#website)

## Install on the Karoo

Works on **Karoo 2** (Android 8.1) and **Karoo 3**. Both have the accelerometer and gyroscope the
extension needs. Karoo OS must support extensions (any 2024+ firmware).

1. Get a test build. **There is no signed release yet**, so either
   * build it yourself (see [Building from source](#building-from-source)): `./gradlew :app:assembleDebug`, or
   * download the `karoo-mtb` artifact of the latest successful [CI run](../../actions/workflows/build.yml)
     (needs a GitHub login),

   and install it over USB: `adb install -r app-debug.apk` (or `karoo-mtb.apk` from CI).
   Builds signed with different keys (your own build, CI) don't install over each other. Pull your
   ride folder first ([Testing & debugging](#testing--debugging)), then uninstall the old build.
   Once signed releases exist, the Hammerhead companion app can install the APK from the release
   page (long-press `karoo-mtb.apk` → *Share* → **Hammerhead**), and the Karoo offers updates
   through the release's `manifest.json`.
2. On the Karoo open **MTB Dynamics** from the app drawer:
   * scan the QR code with your phone and subscribe to the topic in the **ntfy** app
     ([Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy) / [iOS](https://apps.apple.com/app/ntfy/id1625396347)),
   * press **Send test notification**,
   * optionally press **Test sensors (5 s)**: it shows the sample rates and |a| at rest (≈ 1.0 g).
     Gently toss the Karoo onto a cushion during the test to see a "flight" detected.
3. Add data fields to a ride profile: *Profiles → (profile) → page → add field → MTB Dynamics*.
   The extension always runs while you record, even with no MTB field on screen.

The extension starts with every recorded ride. To use it only for mountain biking, enable
**Only in MTB / eMTB ride profiles** (the profile's activity type must be *Mountain Bike* or
*eMTB*).

## ntfy ride summary

* Sent when the ride ends (Karoo goes from recording/paused to idle) and the ride has at least
  the configured moving minutes (default 3, so discarded test rides are skipped).
* Delivered through the Karoo's network: Wi-Fi, LTE on Karoo 2, or **your phone via the Hammerhead
  companion app** on Karoo 3. If the Karoo is offline it queues and sends when a connection
  appears. Failed deliveries are retried for 7 days, and the settings screen can resend the last ride.
* Default server `https://ntfy.sh` with a random topic (`mtb-xxxxxxxxxxxxxx`). ntfy.sh topics are
  public to anyone who knows the name, so keep it random, or use your own server plus an access
  token (`tk_…`) or `user:password`.
* Optional: attach the full JSON report (all jumps, corners, segments) to the notification.
* Tapping the notification opens `https://intervals.icu/activities` (changeable).

## Data fields

| Field | Shows |
|---|---|
| **MTB Dynamics** (graphical) | Grit, Flow, jumps and last airtime in one field |
| Grit | ride difficulty so far, kGrit |
| Grit 60s | current difficulty (grit per second, 60 s average) |
| Lap Grit | current lap, kGrit |
| Flow | ride smoothness (lower is better) |
| Flow 60s / Lap Flow | smoothness over the last minute / this lap |
| Jumps | jumps this ride |
| Last Airtime / Last Jump Dist | the last jump (distance follows your unit setting) |
| Max Airtime | longest airtime this ride |
| Corner G | current lateral acceleration |
| Corners | corners this ride |
| Roughness | trail vibration (g RMS, 60 s) |
| Descent Braking | share of descending time spent braking |
| MTB Score | 0-100 |
| **Bike Systems** (graphical) | Flight Attendant state, rear cog, power, trail roughness |
| **Suspension Coach** (graphical) | Flight Attendant state on green (fits the terrain), red (locked on rough ground) or amber (open while climbing hard), with the effort zone |
| FA Open Descent | share of descending time with the fork open |
| Easier Gears Left | larger cogs still available |

After every jump an in-ride alert shows airtime, distance, speed and landing g (like Garmin's
"Nice jump"). Beeps are optional.

## Bike systems: Flight Attendant, AXS, power meter

Tested against a RockShox SID / SIDLuxe Ultimate **Flight Attendant**, SRAM XX SL Eagle
**Transmission** and the XX SL power meter, but it uses the Karoo's generic data types, so any
Flight Attendant, AXS drivetrain and power meter paired with the Karoo works. Nothing to set up:
pair the parts with the Karoo as usual. Without them, the bike sections stay empty. The Reverb
AXS dropper is not exposed to extensions by the Karoo, so it is not used.

Recorded every second next to the MTB data: power, cadence, L/R balance, Flight Attendant fork /
shock state (0 Open, 1 Pedal, 2 Lock), effort zone, mode and bias, rear gear and cog. Each rear
shift is an event with the power and cadence at that moment.

**In the ride**

* *Suspension locked on rough ground*: Lock for 5 s while the trail vibrates at ≥ 0.9 g (alert, 2 min cooldown).
* *Easier gear available*: grinding a ≥ 6 % climb below 55 rpm for 8 s with larger cogs left (off by default).
* *Battery low*: an AXS or Flight Attendant battery reports low / critical (once per part and ride).

**After the ride** (ntfy, `summary.json`, FIT session, analysis script), split by climbs / descents / flats:

| Metric | Meaning |
|---|---|
| Flight Attendant shares | Open / Pedal / Lock % per terrain |
| Locked on rough ground | seconds in Lock at ≥ 0.9 g vibration: the system (or bias) was too firm |
| Open on hard climbs | seconds open while pushing ≥ 200 W up ≥ 2 %: energy lost to bobbing |
| Reaction | median seconds from the start of a descent until the fork opens |
| Changes | Flight Attendant state changes (per km) |
| Shifts | rear shifts (per km), shifts under load (≥ 250 W), easier shifts in the 15 s before vs. 30 s after a climb starts (anticipation) |
| Cog usage | minutes per cog, cogs never used, median cog on climbs / descents / flats |
| Steep climbing | cadence, torque and time under 60 rpm on ≥ 6 % |
| Power by terrain | average W and W/kg (weight from the Karoo profile), pedalling % on descents, best 5 min, L/R balance |

Every climb / descent / lap also gets its average power, W/kg, VAM, cadence, main cog, Flight
Attendant shares, pedalling % and shifts.

## Service tracker

Adds up, over all rides **where the Karoo receives Flight Attendant or AXS data** (so rides on
other bikes do not count): fork and shock hours (and how much of it on rough ground), Flight
Attendant changes, shifts, kilometres on the drivetrain, hours per cog and the battery status per
ride. The settings screen shows each service item with its usage. You can correct the usage (e.g.
the hours since the last service before you installed this), change the interval, or tap
**Serviced** to start again from zero.

| Item | Default interval |
|---|---|
| Fork lower-leg service | 50 h |
| Fork damper & spring service | 200 h |
| Shock air-can service | 50 h |
| Shock damper service | 200 h |
| Chain wear check | 1500 km |

The defaults follow the RockShox / SRAM service guides for SID / SIDLuxe and an Eagle chain:
**check the manual of your parts**. When an item becomes due, the Karoo shows a notification. Due
and nearly due (90 %) items are listed in every ntfy summary. The totals are in `service.json`
next to the rides folder, readable by the analysis script (`--service-json`).

## FIT file

The extension writes **developer fields** (karoo-ext `FitEffect`) into every ride:

**Record messages (1 per second)**

| Field | Units | Meaning |
|---|---|---|
| `mtb_grit` | grit | grit points of this second |
| `mtb_flow` | m | unnecessary-braking metres; **written `mtb_flow_lag` (3) s late** |
| `mtb_brake` | m/s² | braking deceleration; also 3 s late |
| `mtb_rough` | g | trail vibration RMS |
| `mtb_lat_g` | g | lateral acceleration (speed × yaw rate) |
| `mtb_jump_air` / `mtb_jump_dist` / `mtb_jump_height` | s / m / m | on the second a jump lands, otherwise 0 |

**Session message**: `mtb_total_grit` (kGrit), `mtb_avg_grit`, `mtb_flow_score`, `mtb_total_flow`,
`mtb_jumps`, `mtb_max_air`, `mtb_total_air`, `mtb_max_jump_dist`, `mtb_max_jump_height`, `mtb_score`,
`mtb_difficulty`, `mtb_smoothness`, `mtb_air_score`, `mtb_corners`, `mtb_max_lat_g`,
`mtb_corner_speed_kept`, `mtb_descent_time`, `mtb_descent_braking`, `mtb_descent_speed`,
`mtb_descent_flow`, `mtb_avg_rough`, `mtb_flow_lag`. With Flight Attendant / AXS / power meter
paired also: `mtb_fa_open_desc` (%), `mtb_fa_lock_rough` (s), `mtb_fa_open_climb` (s),
`mtb_fa_changes`, `mtb_fa_reaction` (s), `mtb_shifts`, `mtb_shifts_km`, `mtb_cog_max` (T),
`mtb_climb_power` (W), `mtb_climb_wkg`, `mtb_desc_pedal` (%).

The Karoo itself records the Flight Attendant states (`front_suspension`, `rear_suspension`,
`suspension_effort_zone`, …), every rear shift (`rear_gear_change` events) and the batteries of
paired parts (`device_info`), so these are in the FIT file as well.

**Garmin-native fields** (setting, default on): record `grit` (114) / `flow` (115) and session
`total_grit`, `total_flow`, `jump_count`, `avg_grit`, `avg_flow`, so tools that understand
Garmin MTB Dynamics can show them. FIT jump messages (285) cannot be written by extensions, so
jumps are only in the developer fields.

Why the lag: Flow has to know what comes next, because braking before a tight corner is good
technique and should not count. The Karoo therefore evaluates Flow 3 s behind real time. The
intervals.icu scripts and the analysis script shift those values back.

Every ride is also saved on the Karoo as CSV + JSON (`samples.csv`, `events.jsonl`,
`summary.json`):

```sh
adb pull /sdcard/Android/data/io.github.angkyria.karoomtb/files/rides
adb pull /sdcard/Android/data/io.github.angkyria.karoomtb/files/service.json
```

## intervals.icu

See **[intervals-icu/README.md](intervals-icu/README.md)**: copy-paste custom streams, activity
fields, interval fields (Grit/Flow/jumps for any selected trail section or lap) and activity
charts (MTB Dynamics, Jumps, Trail segments, Suspension & gears). They work for Karoo and Garmin
rides; the Flight Attendant / AXS ones need a Karoo ride with those parts paired.

## Analysis script

[`tools/mtb_analyze.py`](tools/mtb_analyze.py) analyses a ride and writes a console report, an
interactive HTML report (map coloured by Grit / Flow / speed / roughness, profile, Grit/Flow
chart, braking chart, jumps, segment and lap tables), CSV and JSON.

```sh
pip install -r tools/requirements.txt

python3 tools/mtb_analyze.py ride.fit --html report.html --open     # Karoo or Garmin FIT
python3 tools/mtb_analyze.py --karoo-dir rides/1790000000000 --csv out/ride
export INTERVALS_API_KEY=...                                         # intervals.icu → Settings → Developer
python3 tools/mtb_analyze.py --icu latest --html report.html --icu-update \
        --icu-fields "MtbGrit=grit.total_k,MtbFlow=flow.score,MtbJumps=jumps.count"
python3 tools/mtb_analyze.py --history rides/ --service-json service.json --html history.html
```

* Karoo FITs: reads the `mtb_*` fields, realigns Flow/braking, refines jump heights with the barometer.
* Garmin FITs: reads native grit/flow and jump messages, estimates braking from speed.
* `--rescore` recomputes Grit / Flow with the current formulas (rides recorded by older versions).
* `--karoo-dir <ride> --imu` replays a raw sensor log (see Tuning) through every jump sensitivity
  and lists the longest rejected flights with the reason.
* Any other ride: estimates Grit and Flow from GPS and altitude (no jumps, no roughness).
* `--icu-update` puts a short MTB block into the intervals.icu description. Re-running replaces it.
* Flight Attendant / AXS / power meter: the report adds suspension, drivetrain, power and battery
  sections, and the HTML a *Suspension & gears* chart and cog usage per terrain. `--weight` sets
  the rider weight for W/kg (default: the weight on intervals.icu).
* `--history PATH…` reports across rides (FIT files, Karoo ride folders or the pulled `rides`
  folder): per-ride fork hours, rough hours, Flight Attendant changes, open-on-descents %, shifts
  and climbing power; totals and cog hours; service status; battery level per part with the drain
  since the last charge and the rides left. The same ride as FIT and ride folder counts once.
  `--icu-history 90` does the same with the last 90 days on intervals.icu, `--service-json`
  takes the usage from the Karoo's tracker, `--html` draws it.
* `tools/make_sample_fit.py` writes synthetic Karoo / Garmin / plain FIT files for testing (the
  Karoo one with Flight Attendant, AXS and power).

## How the metrics are calculated

Garmin does not publish its algorithms. These follow the definitions in the Garmin FIT profile
and are tuned to land in similar ranges. They are **not identical** to an Edge's numbers. All
constants live in
[`Scoring.kt`](app/src/main/kotlin/io/github/angkyria/karoomtb/engine/Scoring.kt), mirrored in
`tools/mtb_analyze.py`.

**Sensors.** Accelerometer and gyroscope at up to 100 Hz (orientation-independent: everything is
relative to a running "up" estimate), plus the Karoo's speed, grade, barometric altitude,
distance and GPS streams at 1 Hz.

**Grit** (FIT profile: *time spent going over sharp turns or large grade slopes*). For every
moving second:

```
grit = 1.25 × (1 + 1.2·G_grade + 1.0·G_turn + 1.0·G_rough)     (+4 per second of jump airtime)
G_grade = min(8, (|grade %| / 8)^1.6)                  4 % → 0.33, 8 % → 1, 16 % → 3
G_turn  = min(6, (15 · curvature)^1.3)                 radius 15 m → 1, 5 m → 4.2
G_rough = min(6, (vibration g / 0.6)^1.3)              0.35 g → 0.5, 0.6 g → 1, 1.2 g → 2.5, 2 g → 4.8
```

Ride Grit = Σ / 1000 in **kGrit**; *Grit 60s* = average per second over the last minute.
Rough guide, like Garmin's bands: easy < 20 kGrit, moderate 20-40, hard > 40.

**Flow** (FIT profile: *how long, distance-wise, a cyclist decelerates where deceleration is
unnecessary, such as smooth turns or small grades*):

```
braking  = deceleration beyond what gravity, rolling and air resistance explain
           (downhill: only real slowing down; holding a steady speed does not count)
weight   = 0 below 0.3 m/s², 1 from 1.5 m/s²  (the Karoo's 1 Hz speed smooths brake taps)
need     = max over the next 3 s of: lateral g needed for the coming curve at current speed,
           tight radius (20 m → 6 m), steep descent (−6 % → −18 %), rough ground (1.0 → 2.0 g)
flow_m   = distance × weight × (1 − need)
Flow     = 100 × Σ flow_m / Σ distance          → unnecessary-braking metres per 100 m
```

**Jumps.** A bike in the air is in free fall, so the head unit reads far below 1 g. Take-off
is when |a| (30 ms filter) drops below 0.45 g. Touchdown is when it climbs over 0.8 g, ignoring
spikes under 50 ms (a push on the bars). A jump counts when the airtime is 0.28-3 s, the flight
averaged < 0.6 g, the landing impact reached ≥ 1.15 g, and take-off speed was ≥ 8 km/h.

* **Distance** = take-off speed (median of the 2.5 s before) × airtime
* **Height** = g·t²/8 (ballistic). With a barometric drop of ≥ 1 m (step-downs) it becomes
  peak height above the lower of take-off and landing.
* **Rotations** from integrated gyroscope; **landing g** = impact peak; **score** = 100·air + 2·distance + 50·rotations

**Cornering.** Yaw rate = gyroscope projected on vertical, corrected for lean (÷ cos lean). A
corner starts above 0.20 rad/s at ≥ 2 m/s and ends when the bike straightens (< 0.10 rad/s for
0.5 s) or turns the other way (S-bends). It counts at ≥ 35° heading change. Lateral g = speed ×
yaw rate / g, averaged over ~1 s (the Karoo sits on the handlebar, so steering wobble is filtered
out) and capped at 1.5 g. Without a gyroscope, GPS bearing is used.

**Descending.** Moving seconds with grade ≤ −2.5 % (trail descents are often gentle). *Braking %*
= share of them with ≥ 0.5 m/s² braking deceleration.

**MTB score** = 0.45 · difficulty + 0.40 · smoothness + 0.15 · air, where
difficulty = 100·(1 − e^−(avg grit − 1.25)/3.5), smoothness = 100·e^−Flow/6, air = 100·(1 − e^−airtime/6).

**Trail segments.** Smoothed barometric altitude, split where it reverses by ≥ 15 m
(configurable). Flat stretches (< 2.5 % for ≥ 400 m) are cut out, so "descent – fire road –
descent" gives three segments. Every segment and lap gets distance, time, elevation, grade,
speed, Grit, Flow, braking %, jumps, corners and max g.

Calibration. Roughness on a real Karoo 2 ride: smooth gravel ~0.35 g, rooty singletrack ~0.9 g,
rough descents 1.2-2 g (Flight Attendant's Lock / Pedal / Open states lined up with exactly these
levels). Synthetic rides are in `CalibrationTest.kt`:

| Ride | kGrit | grit/s | Roughness | Score |
|---|---|---|---|---|
| Gravel road, 60 min (synthetic) | 6.0 | 1.7 | 0.17 g | 45 |
| Flow trail, 90 min (synthetic) | 21.4 | 4.0 | 0.34 g | 61 |
| **Real ride, Karoo 2: 1:48 moving, 36 km, 450 m, 12 trail laps** | **28.3** | **4.4** | **0.62 g** | **74** |
| Technical, 120 min (synthetic) | 75.7 | 10.5 | 0.63 g | 97 |

## Tuning

* **Mount the Karoo solidly.** Free-fall detection needs it rigidly attached to the bars. A
  rattling mount inflates roughness.
* **Jump sensitivity** (settings):
  *Low* (< 0.35 g, ≥ 0.35 s, landing ≥ 1.3 g) for only clear jumps;
  *Medium* (default); *High* (< 0.55 g, ≥ 0.20 s, landing ≥ 1.05 g) for bunny hops.
  Missing real jumps → go higher; jumps on rough ground that weren't jumps → go lower.
* **Segment split** (default 15 m): smaller for short, punchy trails.
* **Debug: save raw sensor data** stores the 100 Hz accelerometer / gyroscope with each ride
  (`imu.csv.gz`, ~3 MB/h). Ride a few known jumps, pull the ride folder and run
  `mtb_analyze.py --karoo-dir <ride> --imu` to see what each sensitivity would detect.

## Testing & debugging

**Logs.** What the extension does (ride states, sensors, ntfy delivery):

```sh
adb logcat -s MtbExtension MtbRide MtbImu MtbHttp MtbNotifier
```

**Ride data.** Each ride is saved on the Karoo in its own folder. `samples.csv` has one row per
second (MTB values plus power, cadence, Flight Attendant and gear columns). `events.jsonl` lists
the jumps, corners and shifts. There's also `summary.json`, and `ntfy.json` with the delivery
status. The service tracker's totals are in `service.json`.

```sh
adb pull /sdcard/Android/data/io.github.angkyria.karoomtb/files/rides
adb pull /sdcard/Android/data/io.github.angkyria.karoomtb/files/service.json
python3 tools/mtb_analyze.py --karoo-dir rides/<ride> --html report.html --open
python3 tools/mtb_analyze.py --history rides/ --service-json service.json
```

The Karoo's own FIT file of the same ride (from the Hammerhead dashboard or intervals.icu) can be
analysed the same way, which is handy for comparing what the extension saw with what the Karoo recorded.

**Jumps.** Turn on *Debug: save raw sensor data*, ride a few known jumps, note their times, then
run `mtb_analyze.py --karoo-dir <ride> --imu` ([Tuning](#tuning)).

**Reporting a bug.** [Open an issue](../../issues/new/choose) with the Karoo model and firmware,
the app version (top of the settings screen), what happened and when, and the logcat output.
Ride folders and FIT files contain your GPS track: don't attach them to a public issue. Mention
that you have them and share them privately instead.

**Common problems**

* *No notification*: check the topic in the ntfy app, use **Send test notification**, see "ntfy:
  …" under *Last ride* in the app. HTTP 403/401 means the topic or token is wrong.
* *Fields show only whole numbers*: numeric extension fields borrow the formatting of a built-in
  Karoo field (`UpdateNumericConfig`). Use the graphical **MTB Dynamics** field if a Karoo
  firmware ignores it.
* *Jumps / roughness empty*: run **Test sensors** in the app. It lists the accelerometer and
  gyroscope found and their real sample rates (a Karoo 2 gives about 98 Hz).

## Website

<https://angkyria.github.io/karoo-mtb/> is served by GitHub Pages from [`docs/`](docs/). The demo
ride report and history are generated from synthetic rides only:

```sh
python3 tools/make_site_demo.py     # rebuilds docs/demo/report.html and docs/demo/history.html
```

## Building from source

Needs JDK 17, the Android SDK (compileSdk 35), and a GitHub token with `read:packages`: karoo-ext
is on GitHub Packages, which always requires authentication.

```sh
export GPR_USER=<github user> GPR_KEY=$(gh auth token)   # or gpr.user / gpr.key in local.properties
./gradlew :app:testDebugUnitTest :app:assembleDebug      # APK: app/build/outputs/apk/debug/
./gradlew :app:installDebug                              # Karoo connected over USB

python3 -m unittest discover -s tools/tests             # analyser tests
node intervals-icu/test/run.mjs                          # intervals.icu script tests
```

**Releases**: push a tag like `v0.1.0`. The workflow builds, tests and attaches `karoo-mtb.apk`,
`manifest.json` and the icon to a GitHub release. The Karoo then offers updates automatically.
For updates to install over each other, sign every release with the same key:

```sh
keytool -genkeypair -v -keystore karoo-mtb.jks -alias karoo-mtb -keyalg RSA -keysize 2048 -validity 10000
base64 -i karoo-mtb.jks | pbcopy     # → repository secret KEYSTORE_BASE64
```

Add the secrets `KEYSTORE_PASSWORD`, `KEY_ALIAS` (`karoo-mtb`) and `KEY_PASSWORD`. Without them
the APK is signed with the CI debug key, which changes between builds. The release URLs assume the
repository `github.com/angkyria/karoo-mtb`; CI sets `BASE_URL` from the actual repository.

### Layout

```
app/src/main/kotlin/io/github/angkyria/karoomtb/
  engine/    pure Kotlin MTB engine (IMU processing, jumps, corners, Grit/Flow, segments, bike systems, summary)
  karoo/     KarooExtension service, ride controller, data fields, sensors
  fit/       FIT developer + native fields
  notify/    ntfy messages, HTTP via the Karoo bridge, summary text
  storage/   per-ride CSV/JSON, crash recovery
  service/   service and battery tracker across rides
  ui/        settings screen
tools/        mtb_analyze.py (analysis, HTML report, history, intervals.icu API), make_sample_fit.py, make_site_demo.py
intervals-icu/ custom streams, fields, charts for intervals.icu (+ tests)
docs/         website (GitHub Pages) with demo reports
```

---

Not affiliated with Garmin or Hammerhead/SRAM. "Grit", "Flow" and "MTB Dynamics" describe
Garmin's features this project is modelled on.
