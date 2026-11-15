# Jump ground truth: labels, fit and regression gate

Date: 2026-10-06 · Status: design approved in chat, awaiting spec review

## Why

The jump count is the least trustworthy number in the ride summary. On the 2026-10-06 afternoon
ride (sensitivity HIGH) the Karoo counted 13 jumps; `mtb_analyze.py --imu` shows MEDIUM and LOW
would have counted 0. All 13 had 0.20–0.30 s of air, just above HIGH's 0.20 s `minAirSec`, and the
next ten flights were rejected at 0.12–0.20 s. Whether those were real jumps or a roller hit every
lap cannot be told today: the "Mark moment" button only says "jump", nothing collects labels across
rides, and the three presets in `MtbConfig.kt` were set by hand.

## Goal and success criteria

* **Trustworthy counts.** When the summary says N jumps, they are N real jumps. Missing a small hop
  is acceptable; counting a roller is not.
* Precision targets on labelled flights, per preset:
  * MEDIUM (the default, and the setting that means "trustworthy count"): **≥ 95 %**
  * LOW: **≥ 99 %**
  * HIGH: **≥ 85 %**
* Under each target, recall is as high as possible.
* Precision and recall are measured with leave-one-ride-out validation, not on the data the fit
  was tuned on.
* No new preset values are proposed until the corpus holds **≥ 20 jump and ≥ 20 not-a-jump labels
  from ≥ 3 rides**.

## Non-goals

* A per-rider "Custom" sensitivity, or thresholds loaded at runtime. Fitted values ship in the
  presets.
* A learned classifier.
* Labels for anything other than jumps (corners, drops, roughness).
* An HTML or browser review UI. That belongs to the future browser analyser, which will read the
  same `labels.csv`.
* Barometric jump height (sub-project B, a separate spike) and mount calibration (sub-project C).
* CI access to the private corpus, and automatic edits to `MtbConfig.kt`.

## 1. Labels on the Karoo

* New bonus action `nojump` ("Not a jump") in `res/xml/extension_info.xml`, next to `mark`. It is
  assigned to a controller button the same way.
* `MtbExtension` routes both actions to `RideController.markMoment(label)`. `MtbEngine.markMoment`
  and the `Marker` model get `label: MarkLabel` (`JUMP`, `NOJUMP`). Ride files without the field
  read as `JUMP`.
* The flight a press refers to is unchanged: the longest flight, counted or rejected, that landed
  within the last 15 s (`MARKER_WINDOW_S` in `tools/mtbdyn/imu.py`, same rule in Kotlin). "Not a
  jump" on a counted flight is a false positive; "Jump" on a rejected flight is a miss.
* The toast names the flight and the detector's verdict, e.g. "Not a jump #3 · 0.24 s flight,
  counted" or "Jump #4 · 0.18 s flight, rejected (airtime)", via `SummaryFormatter.markerDetail`.
* `events.jsonl`: the marker object gets `"label": "jump" | "nojump"`.
* FIT: the same `user_marker` event plus a new developer field `mtb_marker_label` (UINT8,
  0 = jump, 1 = not a jump) in `MtbFitFields`. `loaders.py` reads it from both FIT and
  `events.jsonl`.

## 2. Labels file and review mode

### `labels.csv`

Lives in the ride folder. One line per labelled flight:

```
wall_ms,label,source
1791295522140,nojump,review
```

* `label` is `jump` or `nojump`. `source` is `button` or `review`.
* `read_labels` still accepts the existing `HH:MM:SS,label` (UTC) lines for `--labels`. New files
  are written with `wall_ms`.
* No positions are stored.
* Precedence: when a button press and a review label match the same flight, the review label wins.
  The fit sees exactly one label per flight.

### `mtb_analyze.py --karoo-dir <ride> --review`

Interactive terminal pass.

* **Candidates:** every flight with ≥ 0.12 s of air and take-off speed ≥ `jumpMinSpeed`, found by
  the Python detector with the gates opened to the bounds of the fit's search grid. This is
  broader than any preset.
* **Spots:** candidates whose take-off points lie within 15 m of each other (GPS, used locally
  only) are grouped into one spot. Each spot is shown once, with every pass listed: time, lap,
  air, mean in-flight g, landing g, the LOW/MEDIUM/HIGH verdicts and any existing label.
* **Keys:** `J` all passes jump, `N` all passes not a jump, `e` label each pass, `s` skip,
  `q` quit.
* **Saving:** every answer is appended to `labels.csv` immediately. A rerun skips flights that are
  already labelled, and shows button labels so you can confirm or override them (overrides are
  saved as `review`).
* **Without a TTY:** `--review --dump candidates.csv` writes the same list (with an empty `label`
  column) for editing by hand, then reading back with `--labels`.

## 3. Corpus and fit

### Corpus: `--corpus <dir>`

Default `~/karoo-mtb-corpus/`, outside the repository.

* For each labelled flight in the ride, it writes:
  * `<rideId>_<takeoffMs>.csv`: ±3 s of raw IMU, in the existing snippet format, with no GPS and
    no wall date.
  * `<rideId>_<takeoffMs>.json`: `label`, `source`, take-off speed, IMU sample rate, ride id,
    spot id.
* Re-adding a ride is idempotent. A changed label replaces the old one.

### Fit: `mtb_analyze.py --fit <corpus>`

* **Search grid**, every combination replayed through the Python detector (`mtbdyn`, kept in
  parity with Kotlin by `test_parity.py`):
  * `takeoffG`: 0.30–0.65 g in 0.05 steps
  * `minAirSec`: 0.12–0.45 s in 0.02 steps
  * `minLandingG`: 1.0–1.6 g in 0.05 steps
  * `jumpMaxMeanAirG`: 0.45–0.70 g in 0.05 steps

  `jumpMaxMeanAirG` is global in `MtbConfig`, so one value is chosen for all presets: the best
  for MEDIUM.
* **Per preset:** the feasible set is the combinations that meet the preset's precision target.
  Pick the highest recall. Break ties with the largest margin, i.e. the smallest normalised
  distance from any threshold to the nearest labelled flight is as large as possible, so a value
  does not sit right at the edge of the labelled flights.
* **Weighting:** each spot has total weight 1 per ride, shared across its passes, so six laps over
  one roller count as one feature per ride.
* **Validation:** leave-one-ride-out. The reported precision and recall come from rides the
  values were not fitted on.
* **Output:**
  * a table of current vs proposed precision and recall per preset
  * proposed `Sensitivity` entries, ready to paste into `MtbConfig.kt`
  * every labelled flight the proposal still gets wrong (ride, time, air, g values)
  * `fit-result.json` in the corpus: proposed values plus the Python verdict per flight per preset
    (used by section 4)
* **Guard:** below the minimum corpus (20 / 20 / 3 rides), it prints current-preset precision and
  recall and the missing counts, and proposes nothing.

## 4. Regression gate

### Public fixtures (CI, every build)

* `--fit <corpus> --export-fixtures app/src/test/resources/imu` copies at most ~30 clips into the
  repository:
  * for each preset and threshold, the labelled flights nearest the boundary on both sides
  * one clear jump, one roller and one rough patch
* Each manifest entry gets per-preset expectations:
  `"expect": {"LOW": false, "MEDIUM": false, "HIGH": true}`. Existing entries with `expectJump`
  (and optional `preset`) keep their meaning.
* `JumpFixtureTest.kt` replays each fixture under every preset named in `expect`. `knownFailure`
  is unchanged.

### Private corpus (local)

* `./gradlew test -Pcorpus=~/karoo-mtb-corpus` adds `CorpusPrecisionTest`. It:
  * replays every corpus clip through the real `ImuProcessor` and `JumpDetector`
  * asserts each preset's precision target
  * compares each verdict with `fit-result.json`; any Python/Kotlin disagreement fails, listing the
    flight
* Without `-Pcorpus` the test is skipped, so CI is unaffected.

### Preset update workflow

1. `mtb_analyze.py --fit` and review the table.
2. Paste the values into `MtbConfig.kt`.
3. Run `--export-fixtures`.
4. Run `./gradlew test` and `./gradlew test -Pcorpus=…`, plus the Python tests.
5. Release only when all pass.

After the first fitted presets ship, the README recommends MEDIUM as the trustworthy-count
setting.

## Privacy

* Ride folders, `labels.csv` and the corpus stay outside the repository (`rides/` and
  `imu.csv.gz` are already git-ignored; the corpus defaults to the home directory).
* Only exported fixtures are committed: IMU only, with no GPS and no date.

## Testing

* **Kotlin:**
  * `MarkerTest`: label field, defaulting to JUMP, flight choice for both labels
  * FIT field write
  * `JumpFixtureTest` with per-preset `expect`
  * `CorpusPrecisionTest` (skipped without a corpus)
* **Python (`tools/tests`):**
  * label reading: `wall_ms` and `HH:MM:SS`, precedence, FIT and `events.jsonl` labels
  * spot grouping
  * review `--dump` round trip
  * corpus idempotence
  * fit: the guard, a synthetic corpus whose best thresholds are known, margin tie-break,
    leave-one-ride-out
  * fixture export manifest
* `test_parity.py` keeps the Python detector in step with Kotlin.
