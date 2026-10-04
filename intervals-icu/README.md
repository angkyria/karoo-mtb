# MTB Dynamics in intervals.icu

> **Easiest:** the [step-by-step guide on the website](https://angkyria.github.io/karoo-mtb/intervals-icu.html)
> has every value and script below with copy buttons, plus a synthetic sample ride to try it.

The Karoo extension writes all MTB data into the ride's FIT file as developer fields
(`mtb_*`). intervals.icu keeps developer fields only once you tell it which ones to read, so
there is a one-time setup. After that every new Karoo ride shows Grit, Flow, jumps, braking etc.
For rides uploaded before the setup, open the activity and choose **Actions → Reprocess File**.
That re-reads the FIT file; *Re-analyse* only recomputes from data already imported. For many rides,
go to Calendar → activity list, tick the rides and reprocess them together.

**Do the setup while viewing a ride recorded with MTB Dynamics**: the FIT field lists only offer
the `mtb_*` fields when the open ride has them. No ride yet? Upload the synthetic
[sample ride](https://angkyria.github.io/karoo-mtb/sample/mtb-dynamics-sample.fit) and delete it afterwards.

### Automatic setup with your API key

[`tools/icu_setup.py`](../tools/icu_setup.py) creates every stream, field and chart below through
the intervals.icu API. Re-running it only updates what changed. From the repository root:

```sh
export INTERVALS_API_KEY=...                       # intervals.icu → Settings → Developer Settings
python3 tools/icu_setup.py --dry-run               # what would be created / updated
python3 tools/icu_setup.py                         # create / update the 40 items
python3 tools/icu_setup.py --no-items --reprocess 365 --snippet reprocess.js
```

intervals.icu only lets its website reprocess files, so `--reprocess 365` lists the rides of the
last year whose FIT file has MTB Dynamics or Flight Attendant / AXS data. Reprocess them in the
activity list (select them → **Reprocess File**, keep intervals), or paste `reprocess.js` into the
browser console of a logged-in intervals.icu tab: it sends the website's own Reprocess File request
for each ride, keeping intervals and manually entered field values.

Two things stay manual: add the charts to the activity page (**Charts** → **+**) and choose which
fields show in the activity list.

### Quick start (5 minutes)

1. Streams `MtbGrit` (record field `mtb_grit`, units `grit`), `MtbFlow` (script
   [streams/mtb_flow.js](streams/mtb_flow.js), units `m`) and `MtbJumpAir` (record field
   `mtb_jump_air`, units `s`).
2. Activity fields `MtbGrit`, `MtbFlow` and `MtbJumps`, each reading its FIT session field
   (`mtb_total_grit`, `mtb_flow_score`, `mtb_jumps`).
3. The chart [charts/mtb_dynamics.js](charts/mtb_dynamics.js).
4. **Actions → Reprocess File** on the ride.

> Want just a summary without the setup? With an intervals.icu API key in the MTB Dynamics app
> (0.3+), the Karoo writes an MTB block into each activity's description, and can fill the custom
> activity fields below once you have created them.

The scripts here also work for **Garmin Edge** rides: they fall back to Garmin's own MTB
Dynamics fields (`grit`, `flow`, `total_grit`, `avg_flow`, `jump_count`, jump messages).

> intervals.icu changes its UI from time to time, so the menu names below may differ slightly.
> Codes matter: the interval fields and charts look streams up by the codes in the tables.
> intervals.icu only accepts CamelCase codes and suggests one from the name (`MTBGrit`): replace
> it with the code from the table.

## 1. Custom activity streams (second-by-second data)

Open any activity → **Charts** (under the timeline) → **Custom Streams** → **Add Stream**.

| Name | Code | Source | Units |
|---|---|---|---|
| MTB Grit | `MtbGrit` | record field `mtb_grit` *(or script [streams/mtb_grit.js](streams/mtb_grit.js) to include Garmin rides)* | grit |
| MTB Flow | `MtbFlow` | script [streams/mtb_flow.js](streams/mtb_flow.js), tick **Processes fit file messages** | m |
| MTB Braking | `MtbBrake` | script [streams/mtb_brake.js](streams/mtb_brake.js), tick **Processes fit file messages** | m/s2 |
| MTB Roughness | `MtbRough` | record field `mtb_rough` | g |
| MTB Corner G | `MtbLatG` | record field `mtb_lat_g` | g |
| MTB Jump Airtime | `MtbJumpAir` | record field `mtb_jump_air` | s |
| MTB Jump Distance | `MtbJumpDist` | record field `mtb_jump_dist` | m |
| MTB Jump Height | `MtbJumpHeight` | record field `mtb_jump_height` | m |

**RockShox Flight Attendant / SRAM AXS** (the Karoo records these itself when the parts are paired):

| Name | Code | Source | Units |
|---|---|---|---|
| FA Fork | `FaFront` | record field `front_suspension` (0 Open, 1 Pedal, 2 Lock) | state |
| FA Shock | `FaRear` | record field `rear_suspension` | state |
| FA Effort Zone | `FaEffort` | record field `suspension_effort_zone` (0–3) | zone |
| Rear Cog | `RearCog` | script [streams/rear_cog.js](streams/rear_cog.js), tick **Processes fit file messages** | T |

Power, cadence and L/R balance from the XX SL power meter are standard streams already.

Why scripts for Flow and Braking: Flow needs to see the trail ahead (braking *before* a tight
corner is good riding), so the Karoo writes `mtb_flow` / `mtb_brake` three seconds late. The
scripts move the values back to the second they belong to (the lag is stored in the session
field `mtb_flow_lag`).

Streams with **Processes fit file messages** are computed first; keep the others below them.

## 2. Custom activity fields (ride totals)

**Settings → Custom Fields → Add field → Activity field.** Either read the FIT session field
directly, or paste the script (tick **Processes fit file messages**); the scripts also read
Garmin rides.

| Name | Code | FIT session field | Script | Units |
|---|---|---|---|---|
| MTB Grit | `MtbGrit` | `mtb_total_grit` | [mtb_grit.js](activity-fields/mtb_grit.js) | kGrit |
| MTB Flow | `MtbFlow` | `mtb_flow_score` | [mtb_flow.js](activity-fields/mtb_flow.js) | |
| MTB Jumps | `MtbJumps` | `mtb_jumps` | [mtb_jumps.js](activity-fields/mtb_jumps.js) | |
| MTB Max Airtime | `MtbMaxAir` | `mtb_max_air` | [mtb_max_air.js](activity-fields/mtb_max_air.js) | s |
| MTB Total Airtime | `MtbTotalAir` | `mtb_total_air` | [mtb_total_air.js](activity-fields/mtb_total_air.js) | s |
| MTB Score | `MtbScore` | `mtb_score` | [mtb_score.js](activity-fields/mtb_score.js) | |
| MTB Descent Braking | `MtbDescentBraking` | `mtb_descent_braking` | [mtb_descent_braking.js](activity-fields/mtb_descent_braking.js) | % |
| MTB Corners | `MtbCorners` | `mtb_corners` | [mtb_corners.js](activity-fields/mtb_corners.js) | |
| MTB Max Corner G | `MtbMaxCornerG` | `mtb_max_lat_g` | [mtb_max_corner_g.js](activity-fields/mtb_max_corner_g.js) | g |

**Flight Attendant / AXS / power meter** (the session fields are written by MTB Dynamics 0.2+
when the parts are paired; the scripts also compute them from older rides' records):

| Name | Code | FIT session field | Script | Units |
|---|---|---|---|---|
| FA Open on descents | `MtbFaOpenDesc` | `mtb_fa_open_desc` | [mtb_fa_open_desc.js](activity-fields/mtb_fa_open_desc.js) | % |
| FA locked on rough ground | `MtbFaLockRough` | `mtb_fa_lock_rough` | [mtb_fa_lock_rough.js](activity-fields/mtb_fa_lock_rough.js) | s |
| Shifts per km | `MtbShiftsKm` | `mtb_shifts_km` | [mtb_shifts_km.js](activity-fields/mtb_shifts_km.js) | /km |
| Climbing power | `MtbClimbPower` | `mtb_climb_power` | [mtb_climb_power.js](activity-fields/mtb_climb_power.js) | W |
| Pedalling on descents | `MtbDescPedal` | `mtb_desc_pedal` | [mtb_desc_pedal.js](activity-fields/mtb_desc_pedal.js) | % |

Also in the session: `mtb_fa_open_climb` (s open while pushing ≥ 200 W uphill), `mtb_fa_changes`,
`mtb_fa_reaction` (s until the fork opens on a descent, median), `mtb_shifts`, `mtb_climb_wkg`
(W/kg, with the weight from the Karoo profile), `mtb_cog_max` (largest cog used, T).

More session fields you can add the same way: `mtb_avg_grit` (grit/s), `mtb_total_flow` (m),
`mtb_max_jump_dist` (m), `mtb_max_jump_height` (m), `mtb_difficulty`, `mtb_smoothness`,
`mtb_air_score`, `mtb_corner_speed_kept` (%), `mtb_descent_time` (s), `mtb_descent_speed` (m/s),
`mtb_descent_flow`, `mtb_avg_rough` (g).

Custom activity fields can be shown in the activity list and plotted on the fitness page
(e.g. Flow over time to see whether your descending gets smoother).

## 3. Interval fields (trail segments, laps, any selection)

**Settings → Custom Fields → Add field → Interval field**, paste a script from
[interval-fields/](interval-fields/):

| Name | Code | Script | Units |
|---|---|---|---|
| Grit | `IntMtbGrit` | [interval_grit.js](interval-fields/interval_grit.js) | kGrit |
| Flow | `IntMtbFlow` | [interval_flow.js](interval-fields/interval_flow.js) | |
| Jumps | `IntMtbJumps` | [interval_jumps.js](interval-fields/interval_jumps.js) | |
| Max airtime | `IntMtbMaxAir` | [interval_max_air.js](interval-fields/interval_max_air.js) | s |
| Braking | `IntMtbBraking` | [interval_braking.js](interval-fields/interval_braking.js) | % |
| Roughness | `IntMtbRough` | [interval_roughness.js](interval-fields/interval_roughness.js) | g |

With the Flight Attendant / AXS streams above:

| Name | Code | Script | Units |
|---|---|---|---|
| FA Open | `IntFaOpen` | [interval_fa_open.js](interval-fields/interval_fa_open.js) | % |
| FA Lock | `IntFaLock` | [interval_fa_lock.js](interval-fields/interval_fa_lock.js) | % |
| Shifts | `IntShifts` | [interval_shifts.js](interval-fields/interval_shifts.js) | |
| Main cog | `IntCog` | [interval_cog.js](interval-fields/interval_cog.js) | T |

Karoo laps become intervals automatically. Drag across the activity chart to select a trail
and its Grit / Flow / jumps appear in the selection summary, handy for comparing your runs
down the same descent.

## 4. Activity charts

Activity → **Charts** → **+** → custom chart, paste a script from [charts/](charts/):

* [mtb_dynamics.js](charts/mtb_dynamics.js): altitude with Grit 60 s, Flow 60 s and jump markers
* [mtb_jumps.js](charts/mtb_jumps.js): one bar per jump (airtime, colour = height, hover = distance / speed)
* [mtb_segments.js](charts/mtb_segments.js): automatic climbs / descents / flats with Grit, Flow, braking and jumps per segment
* [mtb_bike.js](charts/mtb_bike.js): Flight Attendant state (Open / Pedal / Lock band) with the rear cog on top, and minutes per cog on climbs / flats / descents (needs the `FaFront` and `RearCog` streams)

## 5. Test without riding

```sh
pip install -r ../tools/requirements.txt
python3 ../tools/make_sample_fit.py sample-karoo.fit     # synthetic 40 min ride: 5 jumps, Flight Attendant, AXS, power
```

Upload `sample-karoo.fit` to intervals.icu (Upload activity) and check the streams, fields and
charts. Delete the activity afterwards.

## 6. From the command line

`tools/mtb_analyze.py` can pull a ride from intervals.icu, analyse it, write a summary into
the activity description and set custom fields through the API:

```sh
export INTERVALS_API_KEY=...   # intervals.icu → Settings → Developer Settings
python3 tools/mtb_analyze.py --icu latest --html report.html --icu-update \
    --icu-fields "MtbGrit=grit.total_k,MtbFlow=flow.score,MtbJumps=jumps.count"

# Across the rides of the last 90 days: suspension / drivetrain hours, service status, battery trend
python3 tools/mtb_analyze.py --icu-history 90 --html history.html
```

## Tests

`node test/run.mjs` runs every script here against a mocked `icu` object.
