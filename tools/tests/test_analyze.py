"""Tests for mtb_analyze.py.   Run:  cd tools && python3 -m unittest discover -s tests -v"""
import csv
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import make_sample_fit  # noqa: E402
import mtb_analyze as mtb  # noqa: E402


class SampleFiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.paths = {}
        for mode in ("karoo", "garmin", "plain"):
            path = os.path.join(cls.tmp.name, f"{mode}.fit")
            make_sample_fit.build(path, mode)
            cls.paths[mode] = path
        cls.rows = make_sample_fit.simulate()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def load(self, mode):
        with open(self.paths[mode], "rb") as f:
            return mtb.load_fit(f.read(), mode)

    def test_karoo_fit(self):
        ride = self.load("karoo")
        self.assertEqual(len(ride.samples), 2400)
        self.assertTrue(ride.has_imu)
        self.assertEqual(ride.flow_lag, 3)
        s = mtb.summarize(ride)
        self.assertEqual(s["jumps"]["count"], 5)
        self.assertAlmostEqual(s["jumps"]["longest"]["air"], 0.95, places=3)
        self.assertEqual([seg["type"] for seg in s["segments"]], ["CLIMB", "DESCENT", "FLAT", "DESCENT", "FLAT"])
        self.assertEqual(len(s["laps"]), 2)
        self.assertEqual(s["cornering"]["source"], "Karoo gyroscope")
        self.assertIn("mtb_total_grit", s["fit_session"])
        self.assertAlmostEqual(s["grit"]["total_k"], sum(r["grit"] for r in self.rows) / 1000, places=1)

    def test_sram_analytics(self):
        ride = self.load("karoo")
        ride.weight = 75.0
        sram = mtb.summarize(ride)["sram"]
        su, dr, pw = sram["suspension"], sram["drivetrain"], sram["power"]
        self.assertGreater(su["by_terrain"]["DESCENT"]["Open"], 85)
        self.assertEqual(su["by_terrain"]["FLAT"]["Lock"], 100.0)
        self.assertEqual(su["locked_rough_s"], 20)          # the 20 s locked on 1.1 g ground
        self.assertEqual(su["bias"], 2)
        self.assertEqual(su["descents_reaching_open"], 2)
        self.assertEqual(dr["shifts"], 5)
        self.assertEqual(dr["by_terrain"]["CLIMB"]["median"], 32)
        self.assertEqual(dr["used"], [18, 21, 32])
        self.assertAlmostEqual(pw["terrain"]["CLIMB"]["avg_w"], 230, delta=3)
        self.assertAlmostEqual(pw["terrain"]["CLIMB"]["w_kg"], 230 / 75, delta=0.05)
        self.assertLess(pw["terrain"]["DESCENT"]["pedalling_pct"], 40)
        kinds = {b["kind"]: b for b in sram["batteries"]}
        self.assertEqual(kinds["Flight Attendant"]["battery_pct"], 95)
        self.assertIn("AXS shifting", kinds)
        report = "\n".join(mtb.sram_text(sram, mtb.Units()))
        self.assertIn("Suspension (Flight Attendant, bias +2)", report)
        self.assertIn("Drivetrain (AXS): 5 shifts", report)

    def test_plain_fit_has_no_sram_sections(self):
        sram = mtb.summarize(self.load("plain"))["sram"]
        self.assertIsNone(sram["suspension"])
        self.assertIsNone(sram["drivetrain"])
        self.assertIsNotNone(sram["power"])  # plain rides still carry power

    def test_flow_is_realigned(self):
        ride = self.load("karoo")
        flows = [x.flow or 0.0 for x in ride.samples]
        # The FIT stores flow 3 s late; after realignment it matches the simulation second by second.
        for i, row in enumerate(self.rows[:-3]):
            self.assertAlmostEqual(flows[i], row["flow"], places=3, msg=f"second {i}")

    def test_garmin_fit(self):
        ride = self.load("garmin")
        s = mtb.summarize(ride)
        self.assertEqual(s["jumps"]["count"], 5)
        self.assertFalse(s["estimated"])
        self.assertGreater(s["grit"]["total_k"], 5)  # native grit was read
        self.assertGreater(s["descending"]["braking_pct"], 0)

    def test_plain_fit_is_estimated(self):
        ride = self.load("plain")
        s = mtb.summarize(ride)
        self.assertTrue(s["estimated"])
        self.assertEqual(s["jumps"]["count"], 0)
        self.assertGreater(s["grit"]["total_k"], 1)
        self.assertGreaterEqual(s["cornering"]["count"], 30)

    def test_outputs(self):
        ride = self.load("karoo")
        s = mtb.summarize(ride)
        html = os.path.join(self.tmp.name, "r.html")
        mtb.write_html(ride, s, html, mtb.Units())
        with open(html) as f:
            text = f.read()
        self.assertIn('"summary"', text)
        self.assertNotIn("__DATA__", text)
        files = mtb.write_csv(ride, s, os.path.join(self.tmp.name, "out", "ride"))
        self.assertEqual(len(files), 5)
        report = mtb.report_text(s, mtb.Units(imperial=True))
        self.assertIn("mph", report)
        self.assertIn("Trail segments", report)

    def test_cli(self):
        out = os.path.join(self.tmp.name, "cli.json")
        self.assertEqual(mtb.main([self.paths["karoo"], "--json", out, "--quiet"]), 0)
        with open(out) as f:
            self.assertEqual(json.load(f)["jumps"]["count"], 5)


class KarooDir(unittest.TestCase):
    HEADER = ("wall_ms,dt,distance_m,d_dist_m,speed_ms,grade_pct,altitude_m,lat,lon,rough_g,yaw_rate,curvature,"
              "lat_g,grit,moving,lap,airborne,brake_ms2,brake_weight,necessity,flow_m")

    def test_ride_folder(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "samples.csv"), "w", newline="") as f:
                f.write(self.HEADER + "\n")
                w = csv.writer(f)
                for i in range(600):
                    climbing = i < 300
                    w.writerow([1_790_000_000_000 + i * 1000, 1, i * 5, 5, 5, 8 if climbing else -10,
                                300 + (i * 0.4 if climbing else 120 - (i - 300) * 0.5), 37.9 + i * 1e-5, 23.7, 0.3,
                                0, 0, 0.1, 3.0, 1, 0 if i < 400 else 1, 0, 0.8 if i % 50 == 0 else 0, 0, 0,
                                0.5 if i % 50 == 0 else 0])
            with open(os.path.join(d, "events.jsonl"), "w") as f:
                f.write(json.dumps({"jump": {"n": 1, "takeoffWallMs": 1_790_000_400_000, "airSec": 0.7, "distanceM": 4.2,
                                             "heightM": 0.6, "speedMs": 6.0, "landingG": 2.4, "rotations": 0}}) + "\n")
            ride = mtb.load_karoo_dir(d)
            s = mtb.summarize(ride)
            self.assertEqual(s["jumps"]["count"], 1)
            self.assertEqual(len(s["laps"]), 2)
            self.assertEqual([seg["type"] for seg in s["segments"]], ["CLIMB", "DESCENT"])
            self.assertAlmostEqual(s["grit"]["total_k"], 1.8, places=6)


class RawImu(unittest.TestCase):
    def test_flight_in_raw_log(self):
        import gzip
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "imu.csv.gz")
            with gzip.open(path, "wt") as f:
                f.write("# wall_ms=1790000000000 elapsed_ms=5000\nsensor,elapsed_ms,x,y,z\n")
                for i in range(400):  # 4 s at 100 Hz, 0.6 s flight from 2.0 s
                    t = 5000 + i * 10
                    z = 0.05 * 9.81 if 200 <= i < 260 else 3.0 * 9.81 if 260 <= i < 266 else 9.81
                    f.write(f"a,{t},0.0,0.0,{z:.4f}\n")
                    f.write(f"g,{t},0.0,0.0,0.0\n")
            accel, offset = mtb.load_imu(path)
            self.assertEqual(len(accel), 400)
            self.assertAlmostEqual(offset, 1790000000000 / 1000 - 5, places=3)
            for preset in ("LOW", "MEDIUM", "HIGH"):
                flights = [f for f in mtb.find_flights(accel, preset) if not f["reason"]]
                self.assertEqual(len(flights), 1, preset)
                self.assertAlmostEqual(flights[0]["air"], 0.6, delta=0.05)
            report = mtb.imu_report(None, path)
            self.assertIn("MEDIUM: 1 jumps", report)


class KarooDirEvents(unittest.TestCase):
    def test_corners_and_summary_jump_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "samples.csv"), "w") as f:
                f.write(KarooDir.HEADER + "\n")
                for i in range(120):
                    f.write(f"{1_790_000_000_000 + i * 1000},1,{i * 6},6,6,0,300,37.9,23.7,0.4,0,0,0.2,2.0,1,0,0,0,0,0,0\n")
            with open(os.path.join(d, "meta.json"), "w") as f:
                json.dump({"startWallMs": 1_790_000_000_000, "appVersion": "0.1.0"}, f)
            with open(os.path.join(d, "events.jsonl"), "w") as f:
                f.write(json.dumps({"jump": None, "corner": {"n": 1, "offsetSec": 30.0, "durationSec": 3.0, "angleDeg": 90.0,
                                                             "entrySpeedMs": 6.0, "minSpeedMs": 5.0, "exitSpeedMs": 6.0,
                                                             "maxLateralG": 2.5, "radiusM": 10.0}}) + "\n")
            # app 0.1.0 wrote jumps only into summary.json
            with open(os.path.join(d, "summary.json"), "w") as f:
                json.dump({"jumps": {"list": [{"n": 1, "takeoffWallMs": 1_790_000_060_000, "airSec": 0.4, "distanceM": 2.4,
                                               "heightM": 0.2, "speedMs": 6.0}]}}, f)
            ride = mtb.load_karoo_dir(d)
            s = mtb.summarize(ride)
            self.assertEqual(s["jumps"]["count"], 1)
            self.assertEqual(s["cornering"]["count"], 1)
            self.assertEqual(s["cornering"]["source"], "Karoo gyroscope")
            self.assertLessEqual(s["cornering"]["list"][0]["max_lat_g"], mtb.MAX_LATERAL_G)


class History(unittest.TestCase):
    @staticmethod
    def row(start, km=10.0, hours=1.0, on_bike=True, pct=None, fork_h=None):
        return {"start": start, "source": "t", "moving_h": hours, "distance_km": km, "on_bike": on_bike,
                "fork_h": hours if fork_h is None else fork_h, "shock_h": hours, "rough_h": 0.1, "fa_changes": 10,
                "fa_open_desc": 50.0, "locked_rough_s": 0.0, "shifts": 100, "shifts_km": 10.0, "drivetrain_km": km,
                "cog_h": {21: hours}, "climb_w": 200.0, "climb_wkg": 2.7,
                "batteries": [] if pct is None else [{"kind": "Flight Attendant", "pct": pct, "status": None}]}

    def test_same_ride_from_fit_and_karoo_folder_counts_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            karoo, plain = os.path.join(tmp, "karoo.fit"), os.path.join(tmp, "plain.fit")
            make_sample_fit.build(karoo, "karoo")
            make_sample_fit.build(plain, "plain")  # same start and distance, no bike data
            h = mtb.history([(p, (lambda p=p: mtb.load_any(p))) for p in mtb.ride_paths([tmp])], quiet=True)
        self.assertEqual(len(h["rides"]), 1)
        self.assertEqual(h["totals"]["duplicates_skipped"], 1)
        r = h["rides"][0]
        self.assertTrue(r["on_bike"])            # the version with Flight Attendant / AXS data was kept
        self.assertEqual(r["shifts"], 5)
        self.assertAlmostEqual(r["fork_h"], r["moving_h"], delta=0.01)
        self.assertAlmostEqual(r["drivetrain_km"], r["distance_km"], delta=0.2)
        self.assertEqual(sorted(r["cog_h"]), [18, 21, 32])
        self.assertEqual(h["batteries"][0]["kind"], "Flight Attendant")
        self.assertEqual(h["service_source"], "these rides")
        text = mtb.history_text(h, mtb.Units())
        self.assertIn("Fork lower-leg service", text)
        self.assertIn("1 duplicate skipped", text)

    def test_dedupe_keeps_separate_rides(self):
        rows = [self.row("2026-10-03T08:00:00+00:00"), self.row("2026-10-03T08:01:00+00:00", on_bike=False, fork_h=0.0),
                self.row("2026-10-03T08:20:00+00:00"), self.row("2026-10-03T08:20:30+00:00", km=20.0)]
        out, skipped = mtb.dedupe_rides(rows)
        self.assertEqual(skipped, 1)
        self.assertEqual(len(out), 3)
        self.assertTrue(out[0]["on_bike"])

    def test_battery_drain_since_the_last_charge(self):
        rows = [self.row(f"2026-10-0{i + 1}T08:00:00+00:00", pct=p) for i, p in enumerate([40, 95, 90, 85, 80])]
        b = mtb.battery_trends(rows)[0]
        self.assertAlmostEqual(b["per_ride"], 5.0)
        self.assertAlmostEqual(b["per_hour"], 5.0)
        self.assertAlmostEqual(b["rides_left"], 13.0)
        self.assertEqual(b["since_charge"], "2026-10-02T08:00:00+00:00")
        steady = mtb.battery_trends([self.row(f"2026-10-0{i + 1}T08:00:00+00:00", pct=90) for i in range(3)])[0]
        self.assertEqual(steady["per_ride"], 0.0)
        self.assertNotIn("rides_left", steady)
        # Too little data (two readings, a 1-minute ride in between): levels only, no rate.
        short = mtb.battery_trends([self.row("2026-10-01T08:00:00+00:00", pct=95),
                                    self.row("2026-10-02T08:00:00+00:00", pct=85, hours=0.02)])[0]
        self.assertNotIn("per_hour", short)
        self.assertNotIn("rides_left", short)
        self.assertEqual(short["last_pct"], 85)

    def test_service_status_from_the_karoo_tracker(self):
        state = {"totals": {"forkHours": 60.0, "shockHours": 10.0, "drivetrainKm": 100.0},
                 "marks": {"fork_lowers": {"atValue": 20.0, "wallMs": 1_790_000_000_000}},
                 "intervals": {"chain": 2000.0}}
        st = {s["id"]: s for s in mtb.service_status({"fork_h": 0, "shock_h": 0, "drivetrain_km": 0}, state)}
        self.assertAlmostEqual(st["fork_lowers"]["used"], 40.0)
        self.assertAlmostEqual(st["fork_lowers"]["progress"], 0.8)
        self.assertEqual(st["fork_lowers"]["last_service_ms"], 1_790_000_000_000)
        self.assertAlmostEqual(st["fork_damper"]["used"], 60.0)
        self.assertAlmostEqual(st["chain"]["interval"], 2000.0)
        self.assertIsNone(st["shock_damper"]["last_service_ms"])
        # The defaults match ServiceTracker.kt.
        self.assertEqual([(i, d) for i, _, _, d in mtb.SERVICE_ITEMS],
                         [("fork_lowers", 50.0), ("fork_damper", 200.0), ("shock_aircan", 50.0), ("shock_damper", 200.0), ("chain", 1500.0)])

    def test_history_cli_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_sample_fit.build(os.path.join(tmp, "karoo.fit"), "karoo")
            service = os.path.join(tmp, "service.json")
            with open(service, "w") as f:
                json.dump({"totals": {"forkHours": 49.9}, "marks": {}, "intervals": {}}, f)
            out = os.path.join(tmp, "out")
            rc = mtb.main(["--history", tmp, "--service-json", service, "--quiet",
                           "--json", out + ".json", "--csv", out, "--html", out + ".html"])
            self.assertEqual(rc, 0)
            with open(out + ".json") as f:
                h = json.load(f)
            self.assertEqual(h["service_source"], "Karoo service.json")
            self.assertGreaterEqual(h["service"][0]["progress"], 0.99)
            with open(out + "_history.csv") as f:
                header = next(csv.reader(f))
            self.assertIn("fork_h", header)
            with open(out + ".html") as f:
                html = f.read()
            self.assertIn("MTB Dynamics history", html)
            self.assertNotIn("__DATA__", html)


class IntervalsHelpers(unittest.TestCase):
    def test_description_is_idempotent(self):
        s = {"score": {"total": 70}, "grit": {"total_k": 12.0}, "flow": {"score": 1.5},
             "jumps": {"count": 2, "longest": {"air": 0.8, "distance": 5.0}},
             "cornering": {"count": 10, "max_lat_g": 0.6}, "descending": {"time_s": 600, "braking_pct": 20}}
        block = mtb.description_block(s, mtb.Units())
        once = mtb.merged_description("Great ride with friends", block)
        twice = mtb.merged_description(once, block)
        self.assertEqual(once, twice)
        self.assertTrue(once.startswith("Great ride with friends"))

    def test_field_map(self):
        m = mtb.parse_field_map("MtbGrit=grit.total_k, MtbFlow=flow.score")
        self.assertEqual(m, {"MtbGrit": "grit.total_k", "MtbFlow": "flow.score"})
        self.assertEqual(mtb.summary_value({"grit": {"total_k": 3.2}}, "grit.total_k"), 3.2)
        self.assertIsNone(mtb.summary_value({}, "x.y"))

    def test_formulas_match_kotlin(self):
        # Spot values from ScoringTest.kt
        self.assertAlmostEqual(mtb.grit_per_second(0, 0, None), mtb.GRIT_SCALE)
        self.assertEqual(mtb.braking_decel(0.0, 7.0, -12.0), 0.0)
        self.assertAlmostEqual(mtb.braking_decel(-1.5, 7.0, -12.0), 1.5)
        self.assertAlmostEqual(mtb.jump_height(0.8), 9.80665 * 0.64 / 8)
        self.assertEqual(mtb.braking_necessity(6.0, 1 / 6.0, 0, 0.1), 1.0)


if __name__ == "__main__":
    unittest.main()
