# Jump Ground Truth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the jump count trustworthy. Add a "Not a jump" Karoo button, post-ride review, a cross-ride label corpus, a threshold fit with per-preset precision targets, and a two-layer regression gate. Then ship a test build to the rider's Karoo.

**Architecture:**
* On the Karoo, `Marker` gains a `label`, and a second bonus action records `nojump`.
* On the computer, `tools/mtbdyn` gains:
  * `groundtruth.py`: labels file, candidates, spots, review
  * `tune.py`: corpus, fit, fixture export
* `imu.find_flights` is generalised to arbitrary thresholds.
* Kotlin tests replay the exported fixtures (CI) and the private corpus (local, `-Pcorpus`) through the real detector.

**Tech Stack:** Kotlin and JUnit 4 (Android app, karoo-ext), Python 3 stdlib `unittest` (tools), Gradle with JDK 17.

**Spec:** `docs/superpowers/specs/2026-10-06-jump-ground-truth-design.md`

## Global Constraints

* Precision targets: MEDIUM **≥ 0.95**, LOW **≥ 0.99**, HIGH **≥ 0.85**, measured with leave-one-ride-out validation.
* Fit guard: **≥ 20 jump, ≥ 20 nojump labels, ≥ 3 rides**. Below that, report only and propose nothing.
* Search grid:
  * `takeoffG` 0.30–0.65 step 0.05
  * `minAirSec` 0.12–0.45 step 0.02
  * `minLandingG` 1.0–1.6 step 0.05
  * `jumpMaxMeanAirG` 0.45–0.70 step 0.05
* `jumpMaxMeanAirG` is a single global value, chosen by MEDIUM's fit.
* Candidates: air **≥ 0.12 s** and take-off speed ≥ `MIN_JUMP_SPEED` (2.2 m/s).
* Spot radius **15 m**. Marker window **15 s** (unchanged).
* No positions in `labels.csv`, the corpus or fixtures. Fixtures are IMU only with relative time.
* Corpus default `~/karoo-mtb-corpus/`, never inside the repo.
* Existing FIT developer field numbers must not shift: new fields are appended after the last `field(...)` declaration.
* Old ride files (marker without `label`) read as `jump`.
* Build with `JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home`, `GPR_USER=angkyria GPR_KEY=$(gh auth token)`.
* Python tests: `cd tools && python3 -m unittest discover -s tests`. Kotlin: `./gradlew testDebugUnitTest`. Lint: `./gradlew ktlintCheck lint` (whatever CI runs) and `ruff check tools`.

## Review Focus

1. **A ride with no `imu.csv.gz`** (debug logging off) given to `--review` or `--corpus` should print a clear "enable Debug: save raw sensor data" message and exit 0, not crash. Test in Task 5.
2. **Pressing "Not a jump" when no flight is in the window** should still store the marker (label `nojump`, no flight). The toast says "No flight in the last 15 s", and Python ignores it for fitting. Test in Task 1 and Task 3.
3. **Re-running `--review` after a crash halfway**: already-labelled flights are skipped and a half-written `labels.csv` (missing final newline) still parses. Test in Task 5.
4. **A corpus with only one ride** must hit the guard. Leave-one-ride-out must not divide by zero, and a fold with no positives must not crash. Test in Task 7.
5. **`labels.csv` with the old `HH:MM:SS,label` lines mixed with `wall_ms` lines** must parse both. Test in Task 3.

---

## File Structure

| File | Responsibility |
|---|---|
| `app/.../engine/Models.kt` | `MarkLabel` enum, `Marker.label` |
| `app/.../engine/MtbEngine.kt` | `markMoment(wallMs, elapsedMs, label)` |
| `app/.../karoo/MtbExtension.kt` | route `mark` and `nojump` actions |
| `app/.../karoo/RideController.kt` | `markMoment(label)`, toast title and FIT event |
| `app/.../notify/SummaryFormatter.kt` | `markerTitle`, `markerDetail` |
| `app/.../fit/MtbFitFields.kt` | `MARKER_LABEL` dev field (appended last), `marker(n, label)` |
| `app/src/main/res/xml/extension_info.xml`, `values/strings.xml` | `nojump` BonusAction |
| `tools/mtbdyn/imu.py` | `Thresholds`, `find_flights(accel, preset_or_thresholds)`, marker labels in `labels_for` |
| `tools/mtbdyn/loaders.py` | marker `label` from `events.jsonl` and FIT |
| `tools/mtbdyn/groundtruth.py` (new) | `labels.csv` I/O, resolution, candidates, spots, review |
| `tools/mtbdyn/tune.py` (new) | corpus add, fit, LORO, fit-result, fixture export |
| `tools/mtbdyn/cli.py` | `--review`, `--dump`, `--corpus`, `--fit`, `--export-fixtures` |
| `app/src/test/.../engine/ImuReplay.kt` (new) | shared snippet replay used by the two tests below |
| `app/src/test/.../engine/JumpFixtureTest.kt` | per-preset `expect` |
| `app/src/test/.../engine/CorpusPrecisionTest.kt` (new) | private corpus gate |
| `app/build.gradle.kts` | `mtb.corpus` system property, version `0.4.0-dev` |
| `README.md` | Tuning section, button, workflow |

---

### Task 1: Marker label in the engine

**Files:**
- Modify: `app/src/main/kotlin/io/github/angkyria/karoomtb/engine/Models.kt` (Marker, ~line 33)
- Modify: `app/src/main/kotlin/io/github/angkyria/karoomtb/engine/MtbEngine.kt:347`
- Test: `app/src/test/kotlin/io/github/angkyria/karoomtb/engine/MarkerTest.kt`

**Interfaces:**
- Produces: `enum class MarkLabel { JUMP, NOJUMP }` (`@Serializable`, serial names `jump` / `nojump`), `Marker.label: MarkLabel = MarkLabel.JUMP`, `MtbEngine.markMoment(wallMs: Long, elapsedMs: Long, label: MarkLabel = MarkLabel.JUMP): Marker?`

- [ ] **Step 1: Write the failing tests** (append to `MarkerTest`)

```kotlin
    @Test
    fun `not-a-jump marker keeps the label and the flight it refers to`() {
        val sim = RideSim().apply { start() }
        sim.ride(10, speed = { 6.0 })
        sim.jumpIn(1.0, 0.6)
        sim.ride(4, speed = { 6.0 })
        val m = sim.engine.markMoment(sim.wallMs(), sim.elapsedMs, MarkLabel.NOJUMP)!!
        assertEquals(MarkLabel.NOJUMP, m.label)
        assertEquals(0.6, m.flightAirSec!!, 0.05)
    }

    @Test
    fun `not-a-jump with no recent flight is still stored`() {
        val sim = RideSim().apply { start() }
        sim.ride(30, speed = { 6.0 })
        val m = sim.engine.markMoment(sim.wallMs(), sim.elapsedMs, MarkLabel.NOJUMP)!!
        assertNull(m.flightAirSec)
        assertEquals(1, sim.finish().markers.size)
    }

    @Test
    fun `old marker json without a label reads as jump`() {
        val m = kotlinx.serialization.json.Json { ignoreUnknownKeys = true }
            .decodeFromString(Marker.serializer(), """{"n":1,"wallMs":5,"offsetSec":1.0}""")
        assertEquals(MarkLabel.JUMP, m.label)
        val json = kotlinx.serialization.json.Json.encodeToString(Marker.serializer(), m.copy(label = MarkLabel.NOJUMP))
        assertTrue(json, json.contains("\"label\":\"nojump\""))
    }
```

- [ ] **Step 2: Run them and check they fail**

Run: `./gradlew testDebugUnitTest --tests '*MarkerTest*'`
Expected: compilation error, `MarkLabel` unresolved.

- [ ] **Step 3: Implement**

In `Models.kt`, above `Marker`:

```kotlin
/** What the rider said about the flight before a "mark" press. */
@Serializable
enum class MarkLabel {
    @SerialName("jump") JUMP,
    @SerialName("nojump") NOJUMP,
}
```

(Add `import kotlinx.serialization.SerialName` if missing.) Add the last property of `Marker`:

```kotlin
    /** JUMP from "Mark moment", NOJUMP from "Not a jump". Files without the field read as JUMP. */
    val label: MarkLabel = MarkLabel.JUMP,
```

The project's `Json` must encode defaults for `label` to appear. If the RideStore `Json` has `encodeDefaults = false`, annotate the property with `@EncodeDefault` (`@OptIn(ExperimentalSerializationApi::class)`) so `"label"` is always written.

In `MtbEngine.markMoment`, change the signature to `fun markMoment(wallMs: Long, elapsedMs: Long, label: MarkLabel = MarkLabel.JUMP): Marker?` and pass `label = label` into the `Marker(...)` constructor.

- [ ] **Step 4: Run the tests and check they pass**

Run: `./gradlew testDebugUnitTest --tests '*MarkerTest*'`
Expected: PASS (all 7).

- [ ] **Step 5: Commit**

```bash
git add app/src/main/kotlin/io/github/angkyria/karoomtb/engine/Models.kt app/src/main/kotlin/io/github/angkyria/karoomtb/engine/MtbEngine.kt app/src/test/kotlin/io/github/angkyria/karoomtb/engine/MarkerTest.kt
git commit -m "Marker label: jump or nojump"
```

---

### Task 2: "Not a jump" button, toast and FIT field

**Files:**
- Modify: `app/src/main/res/xml/extension_info.xml:144-146`, `app/src/main/res/values/strings.xml:12`
- Modify: `app/src/main/kotlin/io/github/angkyria/karoomtb/karoo/MtbExtension.kt:48-54,90`
- Modify: `app/src/main/kotlin/io/github/angkyria/karoomtb/karoo/RideController.kt:112-128`
- Modify: `app/src/main/kotlin/io/github/angkyria/karoomtb/notify/SummaryFormatter.kt:97-102`
- Modify: `app/src/main/kotlin/io/github/angkyria/karoomtb/fit/MtbFitFields.kt` (append field after the last `field(` declaration, change `marker()`)
- Test: `app/src/test/kotlin/io/github/angkyria/karoomtb/engine/MarkerTest.kt`

**Interfaces:**
- Consumes: `MarkLabel`, `Marker.label` (Task 1)
- Produces: `SummaryFormatter.markerTitle(m: Marker): String`, `MtbFitFields.MARKER_LABEL`, `MtbFitFields.marker(n: Int, label: MarkLabel): WriteEventMesg`, `MtbExtension.ACTION_NOJUMP = "nojump"`

- [ ] **Step 1: Write the failing tests** (append to `MarkerTest`)

```kotlin
    @Test
    fun `toast title names the label and detail the verdict`() {
        val sim = RideSim().apply { start() }
        sim.ride(10, speed = { 6.0 })
        sim.jumpIn(1.0, 0.6)
        sim.ride(4, speed = { 6.0 })
        val m = sim.engine.markMoment(sim.wallMs(), sim.elapsedMs, MarkLabel.NOJUMP)!!
        assertEquals("Not a jump #1", SummaryFormatter.markerTitle(m))
        assertTrue(SummaryFormatter.markerDetail(m).endsWith("counted"))
        assertEquals("Jump #2", SummaryFormatter.markerTitle(sim.mark()))
    }

    @Test
    fun `marker label FIT field comes after every existing field`() {
        val all = io.github.angkyria.karoomtb.fit.MtbFitFields.all()
        assertEquals("mtb_marker_label", all.last().fieldName)
        assertEquals(all.size - 1, all.last().fieldDefinitionNumber.toInt())
    }
```

If `MtbFitFields` has no `all()` list, add `fun all(): List<DeveloperField>`, returning every declared field in declaration order (collect them in `field()` into a private `mutableListOf`).

- [ ] **Step 2: Run them and check they fail**

Run: `./gradlew testDebugUnitTest --tests '*MarkerTest*'`
Expected: compilation error, `markerTitle` unresolved.

- [ ] **Step 3: Implement**

`SummaryFormatter.kt`, next to `markerDetail`:

```kotlin
    /** "Jump #3" / "Not a jump #3": the in-ride toast title after a mark press. */
    fun markerTitle(m: Marker): String = (if (m.label == MarkLabel.NOJUMP) "Not a jump #" else "Jump #") + m.n
```

`MtbFitFields.kt`: keep `MARKER` where it is and append, as the **last** `field(...)` declaration in the object:

```kotlin
    /** 0 = jump ("Mark moment"), 1 = not a jump. Appended last so earlier field numbers never move. */
    val MARKER_LABEL = field("mtb_marker_label", "label", UINT8)
```

and replace `marker(n)`:

```kotlin
    fun marker(n: Int, label: MarkLabel): WriteEventMesg = WriteEventMesg(
        EVENT_USER_MARKER, EVENT_TYPE_MARKER,
        listOf(FieldValue(MARKER, n.toDouble()), FieldValue(MARKER_LABEL, if (label == MarkLabel.NOJUMP) 1.0 else 0.0)),
    )
```

`RideController.kt`: change `fun markMoment()` to `fun markMoment(label: MarkLabel)`. Pass `label` to `engine.markMoment(..., label)`, emit `MtbFitFields.marker(marker.n, marker.label)`, use `title = SummaryFormatter.markerTitle(marker)`, and log the label.

`MtbExtension.kt`:

```kotlin
        when (actionId) {
            ACTION_MARK -> controller?.markMoment(MarkLabel.JUMP)
            ACTION_NOJUMP -> controller?.markMoment(MarkLabel.NOJUMP)
        }
...
        const val ACTION_NOJUMP = "nojump"
```

`strings.xml`: `<string name="action_nojump">Not a jump (MTB Dynamics)</string>`

`extension_info.xml`, after the `mark` BonusAction:

```xml
    <BonusAction
        actionId="nojump"
        displayName="@string/action_nojump" />
```

- [ ] **Step 4: Run all Kotlin tests**

Run: `./gradlew testDebugUnitTest`
Expected: PASS. Fix any other caller of `markMoment()` or `marker(n)` the compiler reports, e.g. in tests.

- [ ] **Step 5: Commit**

```bash
git add app/src/main app/src/test
git commit -m "Not a jump button: bonus action, toast title, FIT mtb_marker_label"
```

---

### Task 3: Labels in the analyser (`labels.csv`, marker labels, precedence)

**Files:**
- Create: `tools/mtbdyn/groundtruth.py`
- Modify: `tools/mtbdyn/loaders.py:283-286` (events.jsonl marker) and `:170-179` (`_markers_from_fit`, pass `dev`)
- Modify: `tools/mtbdyn/imu.py:153-180` (`read_labels`, `labels_for`)
- Test: `tools/tests/test_groundtruth.py` (new)

**Interfaces:**
- Produces:
  - `groundtruth.LABELS_FILE = "labels.csv"`
  - `groundtruth.append_label(ride_dir: str, wall_ms: int, label: str, source: str) -> None`
  - `groundtruth.resolve(flights: list[dict], labels: list[dict]) -> list[tuple[dict, dict]]`: (flight, winning label) pairs; review beats button and file beats marker
  - `imu.read_labels(path, day_start)` now accepts `wall_ms,label[,source]`, epoch seconds and `HH:MM:SS`. It skips a `wall_ms,...` header. Each label dict is `{"t", "label", "kind": "file", "source"}`.
  - `imu.labels_for(ride, labels_path, day_start)`: markers become `{"t", "label": m.get("label", "jump"), "kind": "marker", "source": "button", "n"}`. When `labels_path` is None and the ride came from a folder that has `labels.csv`, that file is read.
  - Ride markers carry `"label"`.

- [ ] **Step 1: Write the failing tests** in `tools/tests/test_groundtruth.py`

```python
"""labels.csv, marker labels and label precedence."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from mtbdyn import groundtruth, imu  # noqa: E402
from mtbdyn.model import Ride  # noqa: E402

WALL0 = 1_790_000_000.0


class LabelsFileTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_append_then_read_back_with_mixed_formats(self):
        groundtruth.append_label(self.dir, int((WALL0 + 3.0) * 1000), "jump", "review")
        groundtruth.append_label(self.dir, int((WALL0 + 23.0) * 1000), "nojump", "review")
        path = os.path.join(self.dir, groundtruth.LABELS_FILE)
        with open(path, "a") as f:
            f.write("13:33:25,nojump")          # old format, no trailing newline (crash mid-write)
        labels = imu.read_labels(path, day_start=WALL0 - (WALL0 % 86400))
        self.assertEqual(["jump", "nojump", "nojump"], [x["label"] for x in labels])
        self.assertAlmostEqual(WALL0 + 3.0, labels[0]["t"], places=3)
        self.assertEqual("review", labels[0]["source"])
        with open(path) as f:
            self.assertEqual("wall_ms,label,source\n", f.readline())

    def test_review_beats_button_on_the_same_flight(self):
        flights = [{"t": WALL0 + 3.0, "air": 0.25}]
        labels = [
            {"t": WALL0 + 8.0, "label": "jump", "kind": "marker", "source": "button"},
            {"t": WALL0 + 3.1, "label": "nojump", "kind": "file", "source": "review"},
        ]
        pairs = groundtruth.resolve(flights, labels)
        self.assertEqual(1, len(pairs))
        self.assertEqual("nojump", pairs[0][1]["label"])

    def test_nojump_marker_without_flight_is_dropped(self):
        pairs = groundtruth.resolve([], [{"t": WALL0, "label": "nojump", "kind": "marker", "source": "button"}])
        self.assertEqual([], pairs)


class MarkerLabelLoadTest(unittest.TestCase):
    def test_events_jsonl_marker_label_and_default(self):
        from mtbdyn.loaders import load_karoo_dir
        d = tempfile.mkdtemp()
        _write_min_ride(d, [
            {"marker": {"n": 1, "wallMs": int(WALL0 * 1000), "offsetSec": 1.0}},
            {"marker": {"n": 2, "wallMs": int(WALL0 * 1000) + 5000, "offsetSec": 6.0, "label": "nojump"}},
        ])
        ride = load_karoo_dir(d)
        self.assertEqual(["jump", "nojump"], [m["label"] for m in ride.markers])
        labels = imu.labels_for(ride, None, 0)
        self.assertEqual(["button", "button"], [x["source"] for x in labels])


def _write_min_ride(d, events):
    """meta.json + a 10-row samples.csv + events.jsonl, the columns load_karoo_dir needs."""
    with open(os.path.join(d, "meta.json"), "w") as f:
        json.dump({"startWallMs": int(WALL0 * 1000), "appVersion": "test"}, f)
    cols = ["wall_ms", "dt", "distance_m", "d_dist_m", "speed_ms", "grade_pct", "altitude_m", "lat", "lon"]
    with open(os.path.join(d, "samples.csv"), "w") as f:
        f.write(",".join(cols) + "\n")
        for i in range(10):
            f.write(f"{int((WALL0 + i) * 1000)},1,{6 * i},6,6,0,100,35.0,33.0\n")
    with open(os.path.join(d, "events.jsonl"), "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


if __name__ == "__main__":
    unittest.main()
```

(Drop the unused `src` line if ruff complains. If `load_karoo_dir` needs more columns, copy the header used by `tools/tests/test_analyze.py`'s ride-folder helper instead of guessing.)

- [ ] **Step 2: Run them and check they fail**

Run: `cd tools && python3 -m unittest tests.test_groundtruth -v`
Expected: `ImportError: cannot import name 'groundtruth'`.

- [ ] **Step 3: Implement**

`tools/mtbdyn/groundtruth.py`:

```python
"""Jump ground truth: labels.csv in the ride folder, label precedence, review candidates and spots."""
from __future__ import annotations

import os

LABELS_FILE = "labels.csv"
HEADER = "wall_ms,label,source\n"
# Which label wins when two refer to the same flight: a calm post-ride review beats a mid-trail press.
_RANK = {"review": 3, "file": 2, "button": 1}


def append_label(ride_dir: str, wall_ms: int, label: str, source: str) -> None:
    """Appends one label (written immediately, so a crash loses nothing). No positions are stored."""
    if label not in ("jump", "nojump"):
        raise ValueError(f"label must be jump or nojump, got {label!r}")
    path = os.path.join(ride_dir, LABELS_FILE)
    new = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a+") as f:
        if not new:
            f.seek(0, os.SEEK_END)
            f.seek(f.tell() - 1)
            if f.read(1) != "\n":
                f.write("\n")
        else:
            f.write(HEADER)
        f.write(f"{wall_ms},{label},{source}\n")


def resolve(flights: list[dict], labels: list[dict]) -> list[tuple[dict, dict]]:
    """(flight, label) with one label per flight; labels that match no flight are dropped."""
    from .imu import match_label

    best: dict[int, tuple[dict, dict]] = {}
    for lab in labels:
        fl = match_label(flights, lab)
        if fl is None:
            continue
        cur = best.get(id(fl))
        if cur is None or _RANK.get(lab.get("source", "file"), 0) >= _RANK.get(cur[1].get("source", "file"), 0):
            best[id(fl)] = (fl, lab)
    return sorted(best.values(), key=lambda p: p[0]["t"])
```

`imu.read_labels`: replace the body loop with:

```python
    out = []
    with open(path) as f:
        for line in f:
            line = line.split("#")[0].strip()
            if not line or line.startswith("wall_ms"):
                continue
            parts = [p.strip() for p in line.split(",")]
            when, label = parts[0], parts[1]
            source = parts[2] if len(parts) > 2 and parts[2] else "file"
            if ":" in when:
                h, m, s = when.split(":")
                t = day_start + int(h) * 3600 + int(m) * 60 + float(s)
            else:
                t = float(when)
                if t > 1e11:          # wall_ms
                    t /= 1000.0
            if label not in ("jump", "nojump"):
                raise ValueError(f"{path}: label must be jump or nojump, got {label!r}")
            out.append({"t": t, "label": label, "kind": "file", "source": source})
    return out
```

`imu.labels_for`:

```python
def labels_for(ride: Ride | None, labels_path: str | None, day_start: float) -> list[dict]:
    labels = [{"t": m["t"], "label": m.get("label", "jump"), "kind": "marker", "source": "button", "n": m["n"]}
              for m in (ride.markers if ride else [])]
    if labels_path is None and ride is not None and getattr(ride, "folder", None):
        auto = os.path.join(ride.folder, "labels.csv")
        labels_path = auto if os.path.exists(auto) else None
    if labels_path:
        labels += read_labels(labels_path, day_start)
    return sorted(labels, key=lambda x: x["t"])
```

`model.py` `Ride`: add `folder: str | None = None`. `load_karoo_dir` sets `ride.folder = path`. In `loaders.py` events.jsonl parsing add `"label": m.get("label", "jump")` to the marker dict. In `_markers_from_fit`, take the `dev` helper as a second argument, read `dev(e).get("mtb_marker_label")` and set `"label": "nojump" if that == 1 else "jump"`. Update the call site (`_markers_from_fit(messages.get("event_mesgs", []), dev)`).

`evaluate_labels` and `export_snippets` keep working. `evaluate_labels` now uses `groundtruth.resolve(accepted, labels)` instead of matching each label independently, so a review overrides a button press.

- [ ] **Step 4: Run all Python tests**

Run: `cd tools && python3 -m unittest discover -s tests -v`
Expected: PASS, including the existing `test_labels.py`.

- [ ] **Step 5: Commit**

```bash
git add tools/mtbdyn tools/tests/test_groundtruth.py
git commit -m "Analyser: labels.csv, nojump markers, review beats button"
```

---

### Task 4: Parameterised detector, candidates and spots

**Files:**
- Modify: `tools/mtbdyn/imu.py:18-77` (`PRESETS`, `find_flights`)
- Modify: `tools/mtbdyn/groundtruth.py` (add candidates and spots)
- Test: `tools/tests/test_groundtruth.py`

**Interfaces:**
- Produces:
  - `imu.Thresholds(takeoff_g: float, min_air: float, min_landing_g: float, max_mean_air_g: float = MAX_MEAN_AIR_G)`: a frozen dataclass
  - `imu.preset_thresholds(name: str) -> Thresholds`
  - `imu.find_flights(accel, preset: str | Thresholds) -> list[dict]`: same dict keys as today
  - `imu.verdict(fl: dict, th: Thresholds, speed: float | None) -> str`: an empty string means accepted. Checks in order: airtime, longer than MAX_AIR, mean g, landing, speed.
  - `groundtruth.CANDIDATE = Thresholds(0.65, 0.12, 0.0, 9.0)`
  - `groundtruth.candidates(ride, accel) -> list[dict]`: each dict has `t, air, mean_g, landing_g, speed, lap, lat, lon` plus `verdicts: {"LOW": str, "MEDIUM": str, "HIGH": str}`
  - `groundtruth.spots(cands, radius_m=15.0) -> list[list[dict]]`

- [ ] **Step 1: Write the failing tests** (append to `test_groundtruth.py`; reuse `write_imu` from `test_labels.py` by importing it: `from test_labels import write_imu`)

```python
class CandidatesTest(unittest.TestCase):
    def test_thresholds_match_presets_and_verdict_order(self):
        th = imu.preset_thresholds("MEDIUM")
        self.assertEqual((0.45, 0.28, 1.15, imu.MAX_MEAN_AIR_G), (th.takeoff_g, th.min_air, th.min_landing_g, th.max_mean_air_g))
        fl = {"air": 0.25, "mean_g": 0.3, "landing_g": 3.0}
        self.assertTrue(imu.verdict(fl, th, 6.0).startswith("airtime"))
        self.assertEqual("", imu.verdict(fl, imu.preset_thresholds("HIGH"), 6.0))
        self.assertTrue(imu.verdict(fl, imu.preset_thresholds("HIGH"), 1.0).startswith("speed"))

    def test_candidates_include_short_flights_and_per_preset_verdicts(self):
        from test_labels import write_imu
        d = tempfile.mkdtemp()
        p = os.path.join(d, "imu.csv.gz")
        write_imu(p)                                     # 0.6 s jump at 3 s, 0.25 s hop at 23 s
        accel, _ = imu.load_imu(p)
        from mtbdyn.model import Sample
        ride = Ride(samples=[Sample(t=WALL0 + i, speed=6.0, lat=35.0, lon=33.0) for i in range(30)])
        cands = groundtruth.candidates(ride, accel)
        self.assertEqual(2, len(cands))
        hop = cands[1]
        self.assertEqual("", hop["verdicts"]["HIGH"])
        self.assertTrue(hop["verdicts"]["MEDIUM"].startswith("airtime"))

    def test_spots_group_passes_within_15_m(self):
        a = {"t": 1, "lat": 35.0, "lon": 33.0}
        b = {"t": 2, "lat": 35.00005, "lon": 33.0}       # ~5.5 m north
        c = {"t": 3, "lat": 35.001, "lon": 33.0}         # ~111 m north
        groups = groundtruth.spots([a, b, c])
        self.assertEqual([[1, 2], [3]], [[x["t"] for x in g] for g in groups])
        self.assertEqual([[1], [2]], [[x["t"] for x in g] for g in groundtruth.spots([{"t": 1, "lat": None, "lon": None}, {"t": 2, "lat": None, "lon": None}])])
```

- [ ] **Step 2: Run them and check they fail**

Run: `cd tools && python3 -m unittest tests.test_groundtruth -v`
Expected: `AttributeError: module 'mtbdyn.imu' has no attribute 'preset_thresholds'`.

- [ ] **Step 3: Implement**

In `imu.py`, below `PRESETS` and the constants:

```python
@dataclass(frozen=True)
class Thresholds:
    takeoff_g: float
    min_air: float
    min_landing_g: float
    max_mean_air_g: float = MAX_MEAN_AIR_G


def preset_thresholds(name: str) -> Thresholds:
    t, a, land = PRESETS[name]
    return Thresholds(t, a, land, MAX_MEAN_AIR_G)


def verdict(fl: dict, th: Thresholds, speed: float | None) -> str:
    """Same checks, same order as JumpDetector.validate + MtbEngine's take-off speed check."""
    air, mean_g, peak = fl["air"], fl["mean_g"], fl["landing_g"]
    if air < th.min_air:
        return "airtime %.2f s < %.2f" % (air, th.min_air)
    if air > MAX_AIR:
        return "longer than %.1f s" % MAX_AIR
    if mean_g > th.max_mean_air_g:
        return "mean %.2f g in flight" % mean_g
    if peak < th.min_landing_g:
        return "landing %.2f g < %.2f" % (peak, th.min_landing_g)
    if speed is not None and speed < MIN_JUMP_SPEED:
        return "speed %.1f km/h" % (speed * 3.6)
    return ""
```

(`from dataclasses import dataclass` at the top.) In `find_flights`, change the signature to `find_flights(accel, preset: "str | Thresholds")`. Start with `th = preset_thresholds(preset) if isinstance(preset, str) else preset`, use `th.takeoff_g` for the state machine, and replace the inline `reason = (...)` with `reason = verdict({"air": air, "mean_g": mean_g, "landing_g": peak}, th, None)`. Callers that pass preset names are unchanged.

In `groundtruth.py`:

```python
import math

from .imu import PRESETS, Thresholds, find_flights, verdict
from .loaders import _index_at

CANDIDATE = Thresholds(0.65, 0.12, 0.0, 9.0)   # widest take-off threshold of the fit grid, no other gate
MIN_CANDIDATE_AIR = 0.12
SPOT_RADIUS_M = 15.0


def _at(ride, t):
    if not ride or not ride.samples:
        return None
    return ride.samples[_index_at(ride.samples, t)]


def _speed(ride, t):
    if not ride or not ride.samples:
        return None
    i = _index_at(ride.samples, t)
    w = sorted(s.speed for s in ride.samples[max(0, i - 3):i + 1])
    return w[len(w) // 2] if w else None


def candidates(ride, accel) -> list[dict]:
    """Every flight the fit could ever count (≥ 0.12 s air, take-off speed ≥ 2.2 m/s), with each preset's verdict."""
    from .imu import MIN_JUMP_SPEED
    per_preset = {name: find_flights(accel, name) for name in PRESETS}
    out = []
    for fl in find_flights(accel, CANDIDATE):
        if fl["air"] < MIN_CANDIDATE_AIR:
            continue
        v = _speed(ride, fl["t"])
        if v is not None and v < MIN_JUMP_SPEED:
            continue
        s = _at(ride, fl["t"])
        verdicts = {}
        for name, flights in per_preset.items():
            near = [f for f in flights if abs(f["t"] - fl["t"]) <= 0.3]
            verdicts[name] = verdict(min(near, key=lambda f: abs(f["t"] - fl["t"])), _preset(name), v) if near else "not a flight"
        out.append({**fl, "speed": v, "lap": getattr(s, "lap", None), "lat": getattr(s, "lat", None),
                    "lon": getattr(s, "lon", None), "verdicts": verdicts})
    return out


def _preset(name):
    from .imu import preset_thresholds
    return preset_thresholds(name)


def _dist_m(a, b) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp, dl = p2 - p1, math.radians(b["lon"] - a["lon"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def spots(cands: list[dict], radius_m: float = SPOT_RADIUS_M) -> list[list[dict]]:
    """Groups passes over the same feature (take-offs within radius_m). No position → its own spot."""
    groups: list[list[dict]] = []
    for c in sorted(cands, key=lambda x: x["t"]):
        if c.get("lat") is None or c.get("lon") is None:
            groups.append([c])
            continue
        home = next((g for g in groups if g[0].get("lat") is not None and _dist_m(g[0], c) <= radius_m), None)
        if home is None:
            groups.append([c])
        else:
            home.append(c)
    return groups
```

(If `Sample` has no `lap` attribute, take the lap from `ride.lap_starts` the way `report.py` does, or leave it `None`.)

- [ ] **Step 4: Run all Python tests, including parity**

Run: `cd tools && python3 -m unittest discover -s tests -v`
Expected: PASS. `test_parity` still sees `imu.PRESETS` unchanged.

- [ ] **Step 5: Commit**

```bash
git add tools/mtbdyn tools/tests
git commit -m "Analyser: threshold-parameterised detector, review candidates and spots"
```

---

### Task 5: Review mode (`--review`, `--dump`)

**Files:**
- Modify: `tools/mtbdyn/groundtruth.py` (add `review`, `dump_candidates`)
- Modify: `tools/mtbdyn/cli.py` (args + dispatch before the console report)
- Test: `tools/tests/test_groundtruth.py`

**Interfaces:**
- Consumes: `candidates`, `spots`, `append_label`, `imu.labels_for`, `imu.load_imu`
- Produces:
  - `groundtruth.review(ride, ride_dir: str, accel, ask=input, out=print) -> int`: number of labels written. `ask(prompt) -> str` is injectable for tests.
  - `groundtruth.dump_candidates(ride, accel, path: str) -> int`: rows written
  - CLI `--review` and `--dump PATH` (only with `--karoo-dir`)

- [ ] **Step 1: Write the failing tests**

```python
class ReviewTest(unittest.TestCase):
    def _ride(self):
        from test_labels import write_imu
        from mtbdyn.model import Sample
        d = tempfile.mkdtemp()
        write_imu(os.path.join(d, "imu.csv.gz"))
        ride = Ride(samples=[Sample(t=WALL0 + i, speed=6.0, lat=35.0 + i * 0.001, lon=33.0) for i in range(30)])
        ride.folder = d
        accel, _ = imu.load_imu(os.path.join(d, "imu.csv.gz"))
        return ride, d, accel

    def test_review_writes_each_answer_and_skips_labelled_on_rerun(self):
        ride, d, accel = self._ride()
        answers = iter(["J", "q"])
        n = groundtruth.review(ride, d, accel, ask=lambda _p: next(answers), out=lambda *_a: None)
        self.assertEqual(1, n)
        answers = iter(["N"])
        n = groundtruth.review(ride, d, accel, ask=lambda _p: next(answers), out=lambda *_a: None)
        self.assertEqual(1, n)                         # only the second flight was left
        labels = imu.read_labels(os.path.join(d, "labels.csv"), 0)
        self.assertEqual(["jump", "nojump"], [x["label"] for x in labels])
        self.assertEqual({"review"}, {x["source"] for x in labels})

    def test_dump_has_an_empty_label_column_and_no_positions(self):
        ride, d, accel = self._ride()
        path = os.path.join(d, "candidates.csv")
        self.assertEqual(2, groundtruth.dump_candidates(ride, accel, path))
        with open(path) as f:
            head = f.readline().strip().split(",")
            row = f.readline().strip().split(",")
        self.assertEqual("label", head[1])
        self.assertEqual("", row[1])
        self.assertNotIn("lat", head)

    def test_cli_review_without_imu_log_exits_cleanly(self):
        from mtbdyn.cli import main
        from test_groundtruth import _write_min_ride
        d = tempfile.mkdtemp()
        _write_min_ride(d, [])
        self.assertEqual(0, main(["--karoo-dir", d, "--review", "--quiet"]))
```

- [ ] **Step 2: Run them and check they fail**

Run: `cd tools && python3 -m unittest tests.test_groundtruth.ReviewTest -v`
Expected: `AttributeError: ... 'review'`.

- [ ] **Step 3: Implement** in `groundtruth.py`

```python
import datetime as dt


def _hms(t: float) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%H:%M:%S")


def _labelled_times(ride, ride_dir) -> tuple[dict[float, dict], list[dict]]:
    from .imu import labels_for
    labels = labels_for(ride, None, 0)
    return {round(x["t"], 1): x for x in labels if x.get("source") == "review"}, labels


def review(ride, ride_dir: str, accel, ask=input, out=print) -> int:
    """Interactive pass over every candidate flight, one spot at a time. Returns labels written."""
    cands = candidates(ride, accel)
    _, labels = _labelled_times(ride, ride_dir)
    done = {id(fl) for fl, lab in resolve(cands, labels) if lab.get("source") == "review"}
    button = {id(fl): lab["label"] for fl, lab in resolve(cands, [x for x in labels if x.get("source") == "button"])}
    written = 0
    groups = [[c for c in g if id(c) not in done] for g in spots(cands)]
    groups = [g for g in groups if g]
    out(f"{sum(len(g) for g in groups)} unlabelled flights at {len(groups)} spots")
    for k, g in enumerate(groups, 1):
        speeds = [c["speed"] for c in g if c["speed"] is not None]
        out(f"\nSpot {k} · {len(g)} pass{'es' if len(g) > 1 else ''}"
            + (f" · ~{sum(speeds) / len(speeds) * 3.6:.0f} km/h" if speeds else ""))
        for c in g:
            marks = "  ".join(f"{p[:3]} {'✓' if not v else '✗'}" for p, v in c["verdicts"].items())
            out(f"  {_hms(c['t'])}  {c['air']:.2f} s air · mean {c['mean_g']:.2f} g · landing {c['landing_g']:.1f} g"
                f"   {marks}   [button: {button.get(id(c), '—')}]")
        while True:
            a = ask("[J]ump all · [N]ot a jump all · [e]ach · [s]kip · [q]uit > ").strip()
            if a in ("J", "N"):
                for c in g:
                    append_label(ride_dir, int(round(c["t"] * 1000)), "jump" if a == "J" else "nojump", "review")
                    written += 1
                break
            if a == "e":
                for c in g:
                    b = ask(f"  {_hms(c['t'])} [j/n/s] > ").strip().lower()
                    if b in ("j", "n"):
                        append_label(ride_dir, int(round(c["t"] * 1000)), "jump" if b == "j" else "nojump", "review")
                        written += 1
                break
            if a == "s":
                break
            if a == "q":
                return written
    return written


def dump_candidates(ride, accel, path: str) -> int:
    """The review list as CSV with an empty label column, for filling in by hand and passing back with --labels."""
    cands = candidates(ride, accel)
    with open(path, "w") as f:
        f.write("wall_ms,label,air_s,mean_g,landing_g,speed_kmh,spot,LOW,MEDIUM,HIGH\n")
        for k, g in enumerate(spots(cands), 1):
            for c in g:
                sp = "" if c["speed"] is None else f"{c['speed'] * 3.6:.0f}"
                v = c["verdicts"]
                f.write(f"{int(round(c['t'] * 1000))},,{c['air']:.2f},{c['mean_g']:.2f},{c['landing_g']:.2f},{sp},{k},"
                        f"{'yes' if not v['LOW'] else 'no'},{'yes' if not v['MEDIUM'] else 'no'},{'yes' if not v['HIGH'] else 'no'}\n")
    return len(cands)
```

`read_labels` must skip `--dump` rows whose label column is still empty. In the loop, after splitting, add `if label == "": continue`.

In `cli.py`, add the args:

```python
    p.add_argument("--review", action="store_true",
                   help="with --karoo-dir: label every candidate flight jump / not a jump (saved to labels.csv in the ride folder)")
    p.add_argument("--dump", metavar="CSV", help="with --review: write the candidates to CSV instead of asking")
```

and, right after `ride = load_karoo_dir(a.karoo_dir)` handling and before `summary = summarize(...)`:

```python
    if a.review:
        if not a.karoo_dir:
            p.error("--review needs --karoo-dir")
        imu_path = os.path.join(a.karoo_dir, "imu.csv.gz")
        if not os.path.exists(imu_path):
            print(f"no raw sensor log at {imu_path} (enable 'Debug: save raw sensor data' on the Karoo)")
            return 0
        from .groundtruth import dump_candidates, review
        accel, _ = load_imu(imu_path)
        if a.dump:
            print(f"wrote {dump_candidates(ride, accel, a.dump)} candidates to {a.dump}")
        else:
            print(f"{review(ride, a.karoo_dir, accel)} labels saved to {os.path.join(a.karoo_dir, 'labels.csv')}")
        return 0
```

(Import `load_imu` from `.imu` at the top of cli.py.)

- [ ] **Step 4: Run all Python tests**

Run: `cd tools && python3 -m unittest discover -s tests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/mtbdyn tools/tests
git commit -m "Analyser: --review / --dump to label candidate flights"
```

---

### Task 6: Corpus (`--corpus`)

**Files:**
- Create: `tools/mtbdyn/tune.py`
- Modify: `tools/mtbdyn/cli.py`
- Test: `tools/tests/test_tune.py` (new)

**Interfaces:**
- Consumes: `candidates`, `spots`, `resolve`, `imu.labels_for`, `imu.load_imu_all`, `imu.write_snippet`, `imu.SNIPPET_MARGIN_S`
- Produces:
  - `tune.DEFAULT_CORPUS = os.path.expanduser("~/karoo-mtb-corpus")`
  - `tune.add_ride(ride, imu_path: str, corpus: str) -> int`: labelled flights written
  - `tune.load_corpus(corpus: str) -> list[dict]`: each clip is `{"file", "label", "source", "speed", "rate_hz", "ride", "spot", "air"}`
  - Clip names: `<ride>_<takeoffMs>.csv` and `.json`, where `ride` = `int(ride.start * 1000)`. `spot` = `"<ride>:<k>"`.

- [ ] **Step 1: Write the failing tests** in `tools/tests/test_tune.py`

```python
"""Corpus, fit and fixture export."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from mtbdyn import groundtruth, imu, tune  # noqa: E402
from mtbdyn.model import Ride, Sample  # noqa: E402
from test_labels import WALL0, write_imu  # noqa: E402


def labelled_ride(d, jump_label="jump", hop_label="nojump"):
    write_imu(os.path.join(d, "imu.csv.gz"))
    ride = Ride(samples=[Sample(t=WALL0 + i, speed=6.0, lat=35.0 + i * 0.001, lon=33.0) for i in range(30)])
    ride.folder, ride.start = d, WALL0
    groundtruth.append_label(d, int((WALL0 + 3.0) * 1000), jump_label, "review")
    groundtruth.append_label(d, int((WALL0 + 23.0) * 1000), hop_label, "review")
    return ride


class CorpusTest(unittest.TestCase):
    def test_add_is_idempotent_and_label_changes_replace(self):
        d, corpus = tempfile.mkdtemp(), tempfile.mkdtemp()
        ride = labelled_ride(d)
        self.assertEqual(2, tune.add_ride(ride, os.path.join(d, "imu.csv.gz"), corpus))
        self.assertEqual(2, tune.add_ride(ride, os.path.join(d, "imu.csv.gz"), corpus))
        clips = tune.load_corpus(corpus)
        self.assertEqual(2, len(clips))
        self.assertEqual({"jump", "nojump"}, {c["label"] for c in clips})
        groundtruth.append_label(d, int((WALL0 + 23.0) * 1000), "jump", "review")   # changed my mind
        tune.add_ride(ride, os.path.join(d, "imu.csv.gz"), corpus)
        self.assertEqual({"jump"}, {c["label"] for c in tune.load_corpus(corpus)})

    def test_clips_carry_no_position_or_date(self):
        d, corpus = tempfile.mkdtemp(), tempfile.mkdtemp()
        tune.add_ride(labelled_ride(d), os.path.join(d, "imu.csv.gz"), corpus)
        for name in os.listdir(corpus):
            with open(os.path.join(corpus, name)) as f:
                text = f.read()
            self.assertNotIn("35.0", text)
            self.assertNotIn("lat", text)
```

- [ ] **Step 2: Run them and check they fail**

Run: `cd tools && python3 -m unittest tests.test_tune -v`
Expected: `ImportError: cannot import name 'tune'`.

- [ ] **Step 3: Implement** `tools/mtbdyn/tune.py` (corpus part)

```python
"""Jump threshold tuning: a private corpus of labelled flights, the fit, and fixture export."""
from __future__ import annotations

import json
import os

from .groundtruth import candidates, resolve, spots
from .imu import SNIPPET_MARGIN_S, labels_for, load_imu, load_imu_all, write_snippet

DEFAULT_CORPUS = os.path.expanduser("~/karoo-mtb-corpus")


def add_ride(ride, imu_path: str, corpus: str) -> int:
    """Writes one ±3 s IMU clip + JSON per labelled flight of this ride (no GPS, no date). Idempotent."""
    os.makedirs(corpus, exist_ok=True)
    accel, _ = load_imu(imu_path)
    cands = candidates(ride, accel)
    spot_of = {id(c): k for k, g in enumerate(spots(cands), 1) for c in g}
    pairs = resolve(cands, labels_for(ride, None, 0))
    rows = load_imu_all(imu_path)
    rate = len(accel) / max(1e-9, accel[-1][0] - accel[0][0]) if len(accel) > 1 else 0.0
    rid = int(round(ride.start * 1000))
    for name in os.listdir(corpus):                      # replace this ride's clips wholesale
        if name.startswith(f"{rid}_"):
            os.remove(os.path.join(corpus, name))
    for fl, lab in pairs:
        t0, t1 = fl["t"] - SNIPPET_MARGIN_S, fl["t"] + fl["air"] + SNIPPET_MARGIN_S
        window = [r for r in rows if t0 <= r[1] <= t1]
        if not window:
            continue
        base = f"{rid}_{int(round(fl['t'] * 1000))}"
        write_snippet(os.path.join(corpus, base + ".csv"), window, {"label": lab["label"], "source": lab.get("source", "file")})
        meta = {"file": base + ".csv", "label": lab["label"], "source": lab.get("source", "file"),
                "speed": fl.get("speed"), "rate_hz": round(rate, 1), "ride": str(rid),
                "spot": f"{rid}:{spot_of.get(id(fl), 0)}", "air": round(fl["air"], 3)}
        with open(os.path.join(corpus, base + ".json"), "w") as f:
            json.dump(meta, f, indent=1)
    return len(pairs)


def load_corpus(corpus: str) -> list[dict]:
    clips = []
    for name in sorted(os.listdir(corpus)):
        if name.endswith(".json") and name != "fit-result.json":
            with open(os.path.join(corpus, name)) as f:
                clips.append(json.load(f))
    return clips
```

CLI: `p.add_argument("--corpus", nargs="?", const=tune.DEFAULT_CORPUS, metavar="DIR", help="with --karoo-dir: add this ride's labelled flights to the private corpus (default ~/karoo-mtb-corpus)")`. Dispatch next to `--review`: check `imu.csv.gz` exists (same message as Task 5), then `print(f"{tune.add_ride(ride, imu_path, a.corpus)} labelled flights in {a.corpus}")` and `return 0`.

- [ ] **Step 4: Run all Python tests**

Run: `cd tools && python3 -m unittest discover -s tests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/mtbdyn tools/tests/test_tune.py
git commit -m "Analyser: private corpus of labelled flights (--corpus)"
```

---

### Task 7: The fit (`--fit`)

**Files:**
- Modify: `tools/mtbdyn/tune.py`
- Modify: `tools/mtbdyn/cli.py`
- Test: `tools/tests/test_tune.py`

**Interfaces:**
- Consumes: `load_corpus`, `imu.find_flights`, `imu.verdict`, `imu.Thresholds`, `imu.preset_thresholds`
- Produces:
  - `tune.TARGETS = {"MEDIUM": 0.95, "LOW": 0.99, "HIGH": 0.85}`
  - `tune.MIN_JUMPS = 20`, `tune.MIN_NOJUMPS = 20`, `tune.MIN_RIDES = 3`
  - `tune.grid() -> dict[str, list[float]]`
  - `tune.clip_flights(corpus, clip, takeoff_g) -> list[dict]`: flights in the clip
  - `tune.detected(flights, th, speed) -> bool`
  - `tune.fit(corpus: str, out=print) -> dict | None`: the result, or None when guarded. It also writes `<corpus>/fit-result.json` with `{"proposed": {"LOW": {"takeoffG", "minAirSec", "minLandingG"}, ...}, "jumpMaxMeanAirG": float, "targets": TARGETS, "clips": [{"file", "label", "speed", "weight", "verdicts": {"LOW": bool, ...}}]}`
- Weighting: each clip's weight is `1 / (number of clips with the same spot)`.
- Precision = Σw(TP) / Σw(TP+FP). Recall = Σw(TP) / Σw(jumps). With no detections, precision counts as 1.0 and recall as 0.

- [ ] **Step 1: Write the failing tests**

```python
def synthetic_corpus(corpus, rides=3, per_ride=8):
    """Jumps of 0.40-0.60 s air vs 0.18-0.26 s rollers: a separable corpus whose right minAirSec lies in (0.26, 0.40)."""
    import make_imu_fixtures
    os.makedirs(corpus, exist_ok=True)
    for r in range(rides):
        for k in range(per_ride):
            for label, air in (("jump", 0.40 + 0.2 * k / per_ride), ("nojump", 0.18 + 0.08 * k / per_ride)):
                rows = make_imu_fixtures.ride(7.0, (3.0, air), 3.0 if label == "jump" else 1.8, 0.05, seed=r * 100 + k)
                base = f"{r}_{k}_{label}"
                imu.write_snippet(os.path.join(corpus, base + ".csv"), rows, {"label": label})
                with open(os.path.join(corpus, base + ".json"), "w") as f:
                    json.dump({"file": base + ".csv", "label": label, "source": "review", "speed": 6.0,
                               "rate_hz": 100, "ride": str(r), "spot": f"{r}:{k}:{label}", "air": air}, f)


class FitTest(unittest.TestCase):
    def test_guard_with_too_few_labels_proposes_nothing(self):
        corpus = tempfile.mkdtemp()
        synthetic_corpus(corpus, rides=1, per_ride=3)
        lines = []
        self.assertIsNone(tune.fit(corpus, out=lines.append))
        self.assertTrue(any("need" in x for x in lines), lines)
        self.assertFalse(os.path.exists(os.path.join(corpus, "fit-result.json")))

    def test_fit_finds_the_gap_and_meets_targets(self):
        corpus = tempfile.mkdtemp()
        synthetic_corpus(corpus)
        res = tune.fit(corpus, out=lambda *_a: None)
        med = res["proposed"]["MEDIUM"]
        self.assertTrue(0.26 < med["minAirSec"] < 0.40, med)
        self.assertGreaterEqual(res["validation"]["MEDIUM"]["precision"], 0.95)
        self.assertGreaterEqual(res["validation"]["MEDIUM"]["recall"], 0.9)
        with open(os.path.join(corpus, "fit-result.json")) as f:
            saved = json.load(f)
        self.assertEqual(48, len(saved["clips"]))
        self.assertEqual({"LOW", "MEDIUM", "HIGH"}, set(saved["clips"][0]["verdicts"]))

    def test_margin_tie_break_picks_the_middle_of_the_gap(self):
        corpus = tempfile.mkdtemp()
        synthetic_corpus(corpus)
        med = tune.fit(corpus, out=lambda *_a: None)["proposed"]["MEDIUM"]["minAirSec"]
        self.assertAlmostEqual(0.33, med, delta=0.035)      # gap (0.26, 0.40): the centre, not an edge

    def test_spot_weights_share_one_feature(self):
        clips = [{"spot": "a"}, {"spot": "a"}, {"spot": "b"}]
        self.assertEqual([0.5, 0.5, 1.0], tune.weights(clips))
```

- [ ] **Step 2: Run them and check they fail**

Run: `cd tools && python3 -m unittest tests.test_tune.FitTest -v`
Expected: `AttributeError: module 'mtbdyn.tune' has no attribute 'fit'`.

- [ ] **Step 3: Implement** (append to `tune.py`)

```python
from .imu import MAX_AIR, Thresholds, find_flights, preset_thresholds, verdict

TARGETS = {"MEDIUM": 0.95, "LOW": 0.99, "HIGH": 0.85}
MIN_JUMPS, MIN_NOJUMPS, MIN_RIDES = 20, 20, 3


def _frange(lo, hi, step):
    n = int(round((hi - lo) / step))
    return [round(lo + i * step, 4) for i in range(n + 1)]


def grid() -> dict[str, list[float]]:
    return {"takeoff_g": _frange(0.30, 0.65, 0.05), "min_air": _frange(0.12, 0.45, 0.02),
            "min_landing_g": _frange(1.0, 1.6, 0.05), "max_mean_air_g": _frange(0.45, 0.70, 0.05)}


def _read_clip(corpus, clip):
    accel = []
    with open(os.path.join(corpus, clip["file"])) as f:
        for line in f:
            if line.startswith("a,"):
                _, t, x, y, z = line.rstrip().split(",")
                accel.append((float(t) / 1000.0, float(x), float(y), float(z)))
    return accel


def clip_flights(corpus, clip, takeoff_g) -> list[dict]:
    # Only the take-off threshold changes the segmentation; the other gates are applied by detected().
    return find_flights(_read_clip(corpus, clip), Thresholds(takeoff_g, 0.0, 0.0, 99.0))


def detected(flights, th: Thresholds, speed) -> bool:
    return any(not verdict(fl, th, speed) for fl in flights)


def weights(clips) -> list[float]:
    count: dict[str, int] = {}
    for c in clips:
        count[c["spot"]] = count.get(c["spot"], 0) + 1
    return [1.0 / count[c["spot"]] for c in clips]


def _score(rows, th, w):
    """rows: [(clip, flights_at_this_takeoff)] → (precision, recall, margin)."""
    tp = fp = pos = 0.0
    margin = float("inf")
    g = grid()
    span = {"min_air": g["min_air"][-1] - g["min_air"][0], "min_landing_g": g["min_landing_g"][-1] - g["min_landing_g"][0],
            "max_mean_air_g": g["max_mean_air_g"][-1] - g["max_mean_air_g"][0]}
    for (clip, flights), wi in zip(rows, w):
        hit = detected(flights, th, clip.get("speed"))
        if clip["label"] == "jump":
            pos += wi
            tp += wi if hit else 0.0
        elif hit:
            fp += wi
        for fl in flights:
            if fl["air"] > MAX_AIR:
                continue
            margin = min(margin, abs(fl["air"] - th.min_air) / span["min_air"],
                         abs(fl["landing_g"] - th.min_landing_g) / span["min_landing_g"],
                         abs(fl["mean_g"] - th.max_mean_air_g) / span["max_mean_air_g"])
    precision = tp / (tp + fp) if tp + fp > 0 else 1.0
    recall = tp / pos if pos > 0 else 0.0
    return precision, recall, margin


def _search(by_takeoff, clips, w, target, fixed_mean=None):
    """Best Thresholds meeting the precision target: highest recall, then largest margin."""
    g = grid()
    best, best_key = None, None
    means = [fixed_mean] if fixed_mean is not None else g["max_mean_air_g"]
    for tg in g["takeoff_g"]:
        rows = list(zip(clips, by_takeoff[tg]))
        for ma in g["min_air"]:
            for ml in g["min_landing_g"]:
                for mm in means:
                    th = Thresholds(tg, ma, ml, mm)
                    p, r, m = _score(rows, th, w)
                    if p + 1e-9 < target:
                        continue
                    key = (round(r, 6), m)
                    if best_key is None or key > best_key:
                        best, best_key = th, key
    return best


def _fit_all(corpus, clips, by_takeoff):
    w = weights(clips)
    med = _search(by_takeoff, clips, w, TARGETS["MEDIUM"])
    if med is None:
        return None
    out = {"MEDIUM": med}
    for name in ("LOW", "HIGH"):
        out[name] = _search(by_takeoff, clips, w, TARGETS[name], fixed_mean=med.max_mean_air_g) or med
    return out


def fit(corpus: str, out=print) -> dict | None:
    clips = load_corpus(corpus)
    jumps = sum(1 for c in clips if c["label"] == "jump")
    nojumps = len(clips) - jumps
    rides = sorted({c["ride"] for c in clips})
    out(f"Corpus: {jumps} jumps, {nojumps} not-a-jump, {len(rides)} rides")
    by_takeoff = {tg: [clip_flights(corpus, c, tg) for c in clips] for tg in grid()["takeoff_g"]}
    w = weights(clips)
    for name in ("LOW", "MEDIUM", "HIGH"):
        p, r, _ = _score(list(zip(clips, by_takeoff[min(grid()["takeoff_g"], key=lambda t: abs(t - preset_thresholds(name).takeoff_g))])),
                         preset_thresholds(name), w)
        out(f"  current {name:<6} precision {p:.0%} · recall {r:.0%}")
    if jumps < MIN_JUMPS or nojumps < MIN_NOJUMPS or len(rides) < MIN_RIDES:
        out(f"need ≥ {MIN_JUMPS} jumps, ≥ {MIN_NOJUMPS} not-a-jump and ≥ {MIN_RIDES} rides before proposing presets "
            f"(missing: {max(0, MIN_JUMPS - jumps)} jumps, {max(0, MIN_NOJUMPS - nojumps)} not-a-jump, {max(0, MIN_RIDES - len(rides))} rides)")
        return None
    proposed = _fit_all(corpus, clips, by_takeoff)
    if proposed is None:
        out("no threshold combination reaches MEDIUM's 95 % precision: label more, or check the not-a-jump clips")
        return None
    validation = _loro(corpus, clips, by_takeoff, rides)
    result = {
        "proposed": {n: {"takeoffG": th.takeoff_g, "minAirSec": th.min_air, "minLandingG": th.min_landing_g} for n, th in proposed.items()},
        "jumpMaxMeanAirG": proposed["MEDIUM"].max_mean_air_g,
        "targets": TARGETS,
        "validation": validation,
        "clips": [{"file": c["file"], "label": c["label"], "speed": c.get("speed"), "weight": wi,
                   "verdicts": {n: detected(by_takeoff[th.takeoff_g][i], th, c.get("speed")) for n, th in proposed.items()}}
                  for i, (c, wi) in enumerate(zip(clips, w))],
    }
    with open(os.path.join(corpus, "fit-result.json"), "w") as f:
        json.dump(result, f, indent=1)
    out("\nProposed (leave-one-ride-out precision / recall):")
    for n in ("LOW", "MEDIUM", "HIGH"):
        th, v = proposed[n], validation[n]
        out(f"  {n:<6} takeoffG {th.takeoff_g:.2f} · minAirSec {th.min_air:.2f} · minLandingG {th.min_landing_g:.2f}"
            f"   precision {v['precision']:.0%} · recall {v['recall']:.0%}")
    out(f"  jumpMaxMeanAirG {proposed['MEDIUM'].max_mean_air_g:.2f}\n\nMtbConfig.kt:")
    for n in ("LOW", "MEDIUM", "HIGH"):
        th = proposed[n]
        out(f"    {n}(takeoffG = {th.takeoff_g:.2f}, minAirSec = {th.min_air:.2f}, minLandingG = {th.min_landing_g:.2f}),")
    wrong = [c for c in result["clips"] if c["verdicts"]["MEDIUM"] != (c["label"] == "jump")]
    if wrong:
        out("\nStill wrong at MEDIUM:")
        for c in wrong:
            out(f"  {c['file']}  labelled {c['label']}")
    return result


def _loro(corpus, clips, by_takeoff, rides) -> dict:
    """Fit on all rides but one, score the held-out ride; sums over folds."""
    acc = {n: [0.0, 0.0, 0.0] for n in TARGETS}   # tp, fp, positives
    for held in rides:
        train = [i for i, c in enumerate(clips) if c["ride"] != held]
        test = [i for i, c in enumerate(clips) if c["ride"] == held]
        tr_clips = [clips[i] for i in train]
        proposed = _fit_all(corpus, tr_clips, {tg: [v[i] for i in train] for tg, v in by_takeoff.items()})
        if proposed is None:
            continue
        te_clips = [clips[i] for i in test]
        w = weights(te_clips)
        for n, th in proposed.items():
            for i, wi in zip(test, w):
                hit = detected(by_takeoff[th.takeoff_g][i], th, clips[i].get("speed"))
                if clips[i]["label"] == "jump":
                    acc[n][2] += wi
                    acc[n][0] += wi if hit else 0.0
                elif hit:
                    acc[n][1] += wi
    return {n: {"precision": (tp / (tp + fp)) if tp + fp > 0 else 1.0, "recall": (tp / pos) if pos > 0 else 0.0}
            for n, (tp, fp, pos) in acc.items()}
```

Performance note: the grid has 8×17×13×6 ≈ 10.6 k combinations and `_score` loops over clips. With ~100 clips that is about 1 M cheap checks per search. LORO repeats it once per ride, which is acceptable at this size. If a run takes over ~2 min, precompute `(air, mean_g, landing_g)` tuples per clip once and skip `verdict()` string formatting in `_score`.

CLI: `p.add_argument("--fit", nargs="?", const=tune.DEFAULT_CORPUS, metavar="CORPUS", help="propose jump presets from the labelled corpus")`. Dispatch at the top of `main` (before ride loading): `if a.fit: tune.fit(a.fit); return 0`. `--fit` needs no FIT or ride argument, so move the `p.error("give a FIT file ...")` check below it.

- [ ] **Step 4: Run all Python tests**

Run: `cd tools && python3 -m unittest discover -s tests -v`
Expected: PASS. If `test_margin_tie_break` lands on an edge, check the margin uses flights from **both** labels (it does, via `rows`) and that `key` compares recall before margin.

- [ ] **Step 5: Commit**

```bash
git add tools/mtbdyn tools/tests
git commit -m "Analyser: --fit proposes presets under precision targets, leave-one-ride-out"
```

---

### Task 8: Fixture export and per-preset expectations

**Files:**
- Modify: `tools/mtbdyn/tune.py` (add `export_fixtures`)
- Modify: `tools/mtbdyn/imu.py` (`update_manifest` comment string)
- Modify: `tools/mtbdyn/cli.py` (`--export-fixtures DIR` with `--fit`)
- Create: `app/src/test/kotlin/io/github/angkyria/karoomtb/engine/ImuReplay.kt`
- Modify: `app/src/test/kotlin/io/github/angkyria/karoomtb/engine/JumpFixtureTest.kt`
- Test: `tools/tests/test_tune.py`, `JumpFixtureTest.kt`

**Interfaces:**
- Consumes: `fit-result.json` (Task 7)
- Produces:
  - `tune.export_fixtures(corpus: str, result: dict, out_dir: str, limit: int = 30) -> list[str]`
  - manifest entries `{"file", "expect": {"LOW": bool, "MEDIUM": bool, "HIGH": bool}, "source": "real", "airSec", "note"}`
  - Kotlin `object ImuReplay { fun flights(text: String, config: MtbConfig): List<RawJump> }`

- [ ] **Step 1: Write the failing tests**

Python (append to `FitTest`):

```python
    def test_export_picks_boundary_clips_with_per_preset_expect(self):
        corpus, out = tempfile.mkdtemp(), tempfile.mkdtemp()
        synthetic_corpus(corpus)
        res = tune.fit(corpus, out=lambda *_a: None)
        written = tune.export_fixtures(corpus, res, out, limit=6)
        with open(os.path.join(out, "manifest.json")) as f:
            fx = json.load(f)["fixtures"]
        self.assertLessEqual(len(fx), 6)
        self.assertIn("manifest.json", written)
        self.assertEqual({"LOW", "MEDIUM", "HIGH"}, set(fx[0]["expect"]))
        airs = sorted(x["airSec"] for x in fx)
        self.assertTrue(any(a < 0.30 for a in airs) and any(a > 0.38 for a in airs), airs)   # both sides of the boundary
```

Kotlin (add to `JumpFixtureTest`, which gains an `expect` map):

```kotlin
    @Test
    fun `manifest expect map overrides expectJump per preset`() {
        val f = parseFixture("""{"file":"x.csv","expect":{"LOW":false,"MEDIUM":false,"HIGH":true}}""")
        assertEquals(mapOf(Sensitivity.LOW to false, Sensitivity.MEDIUM to false, Sensitivity.HIGH to true), f.expect)
        val old = parseFixture("""{"file":"y.csv","expectJump":true}""")
        assertEquals(mapOf(Sensitivity.MEDIUM to true), old.expect)
    }
```

- [ ] **Step 2: Run them and check they fail**

Run: `cd tools && python3 -m unittest tests.test_tune -v` and `./gradlew testDebugUnitTest --tests '*JumpFixtureTest*'`
Expected: `AttributeError ... export_fixtures` and `unresolved reference: parseFixture`.

- [ ] **Step 3: Implement**

`tune.export_fixtures`:

```python
def export_fixtures(corpus: str, result: dict, out_dir: str, limit: int = 30) -> list[str]:
    """Copies the clips nearest each preset's minAirSec (both sides) plus clear examples into out_dir."""
    from .imu import update_manifest
    clips = {c["file"]: c for c in load_corpus(corpus)}
    rows = [{**clips[r["file"]], **r} for r in result["clips"] if r["file"] in clips]
    picked: list[dict] = []

    def take(c):
        if c not in picked and len(picked) < limit:
            picked.append(c)

    for name, th in result["proposed"].items():
        below = sorted((c for c in rows if c["air"] < th["minAirSec"]), key=lambda c: th["minAirSec"] - c["air"])[:3]
        above = sorted((c for c in rows if c["air"] >= th["minAirSec"]), key=lambda c: c["air"] - th["minAirSec"])[:3]
        for c in below + above:
            take(c)
    for label in ("jump", "nojump"):
        clear = sorted((c for c in rows if c["label"] == label), key=lambda c: -c["air"] if label == "jump" else c["air"])
        if clear:
            take(clear[0])
    os.makedirs(out_dir, exist_ok=True)
    entries, written = [], []
    k = len([n for n in os.listdir(out_dir) if n.startswith("real_")])
    for c in picked:
        k += 1
        name = f"real_{k:03d}_{c['label']}.csv"             # no ride id or take-off time: nothing dates the ride
        with open(os.path.join(corpus, c["file"])) as src, open(os.path.join(out_dir, name), "w") as dst:
            for line in src:
                dst.write(line if not line.startswith("#") else f"# label={c['label']} source=real\n")
        entries.append({"file": name, "expect": c["verdicts"], "source": "real", "airSec": c["air"],
                        "note": f"labelled {c['label']} ({c['source']})"})
        written.append(name)
    if entries:
        written.append(os.path.basename(update_manifest(out_dir, entries)))
    return written
```

`update_manifest`: change the comment to "IMU snippets replayed by JumpFixtureTest.kt: 'expect' per preset, or 'expectJump' at MEDIUM (or 'preset'). Write real ones with mtb_analyze.py --fit CORPUS --export-fixtures DIR."

`ImuReplay.kt` (move the loop out of `JumpFixtureTest.replay`):

```kotlin
package io.github.angkyria.karoomtb.engine

/** Replays a snippet CSV (sensor,t_ms,x,y,z) through ImuProcessor + JumpDetector, as the Karoo runs them. */
object ImuReplay {
    fun flights(text: String, config: MtbConfig): List<RawJump> {
        val imu = ImuProcessor()
        val detector = JumpDetector(config)
        val jumps = ArrayList<RawJump>()
        for (line in text.lineSequence()) {
            if (line.isBlank() || line.startsWith("#") || line.startsWith("sensor")) continue
            val c = line.split(',')
            val t = c[1].toDouble() / 1000.0
            when (c[0]) {
                "a" -> {
                    val air = detector.airborne
                    imu.onAccel(t, c[2].toDouble(), c[3].toDouble(), c[4].toDouble(), freezeGravity = air, countRoughness = !air)
                    detector.onAccel(t, imu.magLpG, imu.magG)?.let { jumps += it }
                }
                "g" -> detector.onGyro(t, c[2].toDouble(), c[3].toDouble(), c[4].toDouble())
            }
        }
        return jumps
    }
}
```

`JumpFixtureTest`: `Fixture(val file: String, val expect: Map<Sensitivity, Boolean>, val knownFailure: Boolean)`. Add `internal fun parseFixture(json: String): Fixture` (and a `JsonObject` overload used by `fixtures()`):

```kotlin
    internal fun parseFixture(o: JsonObject): Fixture {
        val expect = o["expect"]?.jsonObject?.mapKeys { Sensitivity.valueOf(it.key) }?.mapValues { it.value.jsonPrimitive.boolean }
            ?: mapOf((o["preset"]?.jsonPrimitive?.content?.let { Sensitivity.valueOf(it) } ?: Sensitivity.MEDIUM) to o.getValue("expectJump").jsonPrimitive.boolean)
        return Fixture(o.getValue("file").jsonPrimitive.content, expect, o["knownFailure"]?.jsonPrimitive?.booleanOrNull ?: false)
    }
    internal fun parseFixture(json: String): Fixture = parseFixture(Json.parseToJsonElement(json).jsonObject)
```

The main test loops `for (f in all) for ((preset, expectJump) in f.expect)`, replays with `ImuReplay.flights(text, MtbConfig(sensitivity = preset))` and counts as before. The failure message includes the preset.

CLI: `p.add_argument("--export-fixtures", metavar="DIR", help="with --fit: copy boundary clips to DIR (app/src/test/resources/imu) with per-preset expectations")`. In the `--fit` branch, `res = tune.fit(a.fit)`, and if `res` and `a.export_fixtures`, print each written file.

- [ ] **Step 4: Run all tests**

Run: `cd tools && python3 -m unittest discover -s tests -v && cd .. && ./gradlew testDebugUnitTest`
Expected: PASS. The four synthetic fixtures still pass via `expectJump`.

- [ ] **Step 5: Commit**

```bash
git add tools app/src/test
git commit -m "Fixture export with per-preset expectations; shared ImuReplay"
```

---

### Task 9: Private corpus gate (`CorpusPrecisionTest`)

**Files:**
- Create: `app/src/test/kotlin/io/github/angkyria/karoomtb/engine/CorpusPrecisionTest.kt`
- Modify: `app/build.gradle.kts` (`testOptions`)

**Interfaces:**
- Consumes: `ImuReplay.flights`, `<corpus>/fit-result.json` (Task 7 schema), `MtbConfig.jumpMinSpeed`
- Produces: a test that is skipped (JUnit `Assume`) unless `-Pcorpus=DIR` is set

- [ ] **Step 1: Write the test**

```kotlin
package io.github.angkyria.karoomtb.engine

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File

/**
 * The private label corpus (`./gradlew testDebugUnitTest -Pcorpus=~/karoo-mtb-corpus`) through the real detector:
 * the presets in MtbConfig must be the ones `mtb_analyze.py --fit` proposed, every clip must get the
 * verdict the Python fit computed, and each preset must meet its precision target. Skipped without -Pcorpus.
 */
class CorpusPrecisionTest {
    @Test
    fun `presets meet their precision targets on the corpus and match the Python fit`() {
        val dir = System.getProperty("mtb.corpus").orEmpty().replaceFirst("~", System.getProperty("user.home"))
        assumeTrue("no -Pcorpus", dir.isNotBlank() && File(dir, "fit-result.json").exists())
        val result = Json.parseToJsonElement(File(dir, "fit-result.json").readText()).jsonObject
        val problems = ArrayList<String>()
        val proposed = result.getValue("proposed").jsonObject
        for (s in Sensitivity.entries) {
            val p = proposed.getValue(s.name).jsonObject
            val want = Triple(p.getValue("takeoffG").jsonPrimitive.double, p.getValue("minAirSec").jsonPrimitive.double, p.getValue("minLandingG").jsonPrimitive.double)
            if (want != Triple(s.takeoffG, s.minAirSec, s.minLandingG)) problems += "$s in MtbConfig is ${Triple(s.takeoffG, s.minAirSec, s.minLandingG)}, fit proposed $want"
        }
        val mean = result.getValue("jumpMaxMeanAirG").jsonPrimitive.double
        if (mean != MtbConfig().jumpMaxMeanAirG) problems += "jumpMaxMeanAirG is ${MtbConfig().jumpMaxMeanAirG}, fit proposed $mean"
        assertTrue(problems.joinToString("\n"), problems.isEmpty())

        val targets = result.getValue("targets").jsonObject
        for (s in Sensitivity.entries) {
            var tp = 0.0
            var fp = 0.0
            for (e in result.getValue("clips").jsonArray) {
                val c = e.jsonObject
                val file = c.getValue("file").jsonPrimitive.content
                val speed = c["speed"]?.jsonPrimitive?.doubleOrNull
                val config = MtbConfig(sensitivity = s)
                val hit = ImuReplay.flights(File(dir, file).readText(), config).isNotEmpty() && (speed == null || speed >= config.jumpMinSpeed)
                val python = c.getValue("verdicts").jsonObject.getValue(s.name).jsonPrimitive.boolean
                if (hit != python) problems += "$file at $s: Kotlin ${if (hit) "jump" else "no jump"}, Python ${if (python) "jump" else "no jump"}"
                val w = c.getValue("weight").jsonPrimitive.double
                if (hit && c.getValue("label").jsonPrimitive.content == "jump") tp += w else if (hit) fp += w
            }
            val precision = if (tp + fp > 0) tp / (tp + fp) else 1.0
            val target = targets.getValue(s.name).jsonPrimitive.double
            if (precision + 1e-9 < target) problems += "$s precision ${"%.3f".format(precision)} < $target"
        }
        assertTrue(problems.joinToString("\n"), problems.isEmpty())
    }
}
```

Note: the target check here uses in-sample precision on the whole corpus. The leave-one-ride-out numbers are what the fit reports. In-sample precision is at least as high, so this check catches drift without ever being stricter than the fit.

- [ ] **Step 2: Wire the property**

In `app/build.gradle.kts`, inside `android { testOptions { ... } }`:

```kotlin
        unitTests.all { test ->
            test.systemProperty("mtb.corpus", (project.findProperty("corpus") as String?) ?: "")
        }
```

- [ ] **Step 3: Run with and without a corpus**

Run: `./gradlew testDebugUnitTest --tests '*CorpusPrecisionTest*'`
Expected: test skipped.

Run:

```bash
python3 - <<'EOF'
import sys, tempfile; sys.path[:0] = ["tools", "tools/tests"]
from test_tune import synthetic_corpus
from mtbdyn import tune
d = "/private/tmp/claude-corpus-check"; synthetic_corpus(d); tune.fit(d)
EOF
./gradlew testDebugUnitTest --tests '*CorpusPrecisionTest*' -Pcorpus=/private/tmp/claude-corpus-check
```

Expected: FAIL listing "MEDIUM in MtbConfig is (0.45, 0.28, 1.15), fit proposed (...)". That proves the gate bites. Do **not** paste the synthetic values into `MtbConfig.kt`.

- [ ] **Step 4: Commit**

```bash
git add app/build.gradle.kts app/src/test/kotlin/io/github/angkyria/karoomtb/engine/CorpusPrecisionTest.kt
git commit -m "CorpusPrecisionTest: private corpus gate behind -Pcorpus"
```

---

### Task 10: Docs, version, push, install the test build on the Karoo

**Files:**
- Modify: `README.md` (Tuning section, Testing status line, test counts)
- Modify: `app/build.gradle.kts:10` (default version `0.4.0-dev`)

- [ ] **Step 1: README**

In **Tuning**, add a "Jump ground truth" subsection:
1. Assign **Not a jump (MTB Dynamics)** to a controller button next to Mark moment, and turn on *Debug: save raw sensor data*.
2. Ride. Press Mark moment after real jumps and Not a jump after rollers or bumps.
3. `adb pull …/files/rides`, then `python3 tools/mtb_analyze.py --karoo-dir rides/<ride> --review` (or `--review --dump c.csv`).
4. `--karoo-dir rides/<ride> --corpus` (default `~/karoo-mtb-corpus`).
5. Once there are ≥ 20 + 20 labels from ≥ 3 rides: `--fit`, paste the presets into `MtbConfig.kt` and `imu.PRESETS`, run `python3 tools/make_scoring_vectors.py`, then `--fit --export-fixtures app/src/test/resources/imu`, `./gradlew testDebugUnitTest -Pcorpus=~/karoo-mtb-corpus`.

Update the "N Kotlin, N Python ... tests" line with the real counts from the test output.

- [ ] **Step 2: Version**

`val releaseVersion: String = System.getenv("RELEASE_VERSION")?.removePrefix("v") ?: "0.4.0-dev"`

- [ ] **Step 3: Full verification**

Run: `cd tools && python3 -m unittest discover -s tests && cd .. && ruff check tools && ./gradlew testDebugUnitTest lint ktlintCheck assembleRelease`
Expected: all green. Use whatever lint task names `.github/workflows/build.yml` runs, if they differ.

- [ ] **Step 4: Commit and push the branch**

```bash
git add README.md app/build.gradle.kts
git commit -m "Jump ground truth: README, version 0.4.0-dev"
git push -u origin claude/jump-ground-truth
```

- [ ] **Step 5: Install the CI build on the Karoo**

CI builds every branch push and signs it with the release key, so it installs over the current app and keeps the settings.

```bash
gh run watch $(gh run list -b claude/jump-ground-truth -w Build -L 1 --json databaseId -q '.[0].databaseId') --exit-status
D=$SCRATCH/ci-gt; rm -rf $D; mkdir -p $D
gh run download $(gh run list -b claude/jump-ground-truth -w Build -L 1 --json databaseId -q '.[0].databaseId') -n karoo-mtb -D $D
apksigner verify --print-certs $D/karoo-mtb.apk | grep 45af0f1e   # release key
adb pull /sdcard/Android/data/io.github.angkyria.karoomtb/files/rides $SCRATCH/backup-rides   # backup first
adb install -r $D/karoo-mtb.apk
adb shell dumpsys package io.github.angkyria.karoomtb | grep -E "versionName|versionCode"
```

Expected: `versionName=0.4.0-dev`, the versionCode above 121, rides still present. Then check the new action appears: in the Karoo profile's controller/remote settings, **Not a jump (MTB Dynamics)** is listed under MTB Dynamics. Ask the rider to confirm on the device, since it can't be read over adb.
