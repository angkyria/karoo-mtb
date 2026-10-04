"""tools/icu_setup.py: item payloads, create / update planning, reprocessing, and the codes."""
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import icu_setup  # noqa: E402
import make_site_guide as guide  # noqa: E402

from mtbdyn.icu import IcuError  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))
# Standard intervals.icu streams the scripts may read besides the custom ones.
BUILT_IN_STREAMS = {"time", "distance", "altitude", "fixed_altitude", "velocity_smooth", "grade_smooth", "watts", "cadence", "heartrate"}


def to_field_code(text: str) -> str:
    """intervals.icu's toFieldCode(): its editors only accept a code that this leaves unchanged."""
    text = re.sub(r"^[0-9]+", "", re.sub(r"[^\w_]", "", text))
    text = re.sub(r"[-_\s.]+(.)?", lambda m: m.group(1).upper() if m.group(1) else "", text)
    return text[:1].upper() + text[1:]


class FakeIcu:
    def __init__(self, items=None, activities=None, files=None):
        self.items = [dict(i) for i in items or []]
        self.acts = activities or []
        self.files = files or {}
        self.created, self.updated, self.reprocessed = [], [], []

    def custom_items(self):
        return self.items

    def create_custom_item(self, item):
        self.created.append(item)
        return {**item, "id": 1000 + len(self.created)}

    def update_custom_item(self, item_id, item):
        if item_id == 666:
            raise IcuError("PUT", "/x", 400, b"bad")
        self.updated.append((item_id, item))
        return item

    def activities(self, oldest, newest):
        return self.acts

    def call(self, method, path, body=None, timeout=60):
        if method != "GET":
            self.reprocessed.append(path)
        rid = path.split("/")[4]
        if rid not in self.files:
            raise IcuError(method, path, 404, b"")
        return self.files[rid]


class CodesTest(unittest.TestCase):
    def test_codes_are_camel_case_and_unique_per_type(self):
        groups = {"stream": [s.code for s in guide.STREAMS], "activity": [a.code for a in guide.ACTIVITY_FIELDS],
                  "interval": [i.code for i in guide.INTERVAL_FIELDS]}
        for kind, codes in groups.items():
            for code in codes:
                self.assertEqual(to_field_code(code), code, f"{kind} code {code} is rejected by intervals.icu")
            self.assertEqual(len(codes), len(set(codes)), kind)

    def test_to_field_code_matches_intervals_icu(self):
        self.assertEqual(to_field_code("MTB Grit"), "MTBGrit")
        self.assertEqual(to_field_code("mtb_grit"), "MtbGrit")
        self.assertEqual(to_field_code("MtbGrit"), "MtbGrit")

    def test_scripts_only_read_streams_that_the_setup_creates(self):
        streams = {s.code for s in guide.STREAMS}
        for item in [*guide.INTERVAL_FIELDS, *guide.CHARTS]:
            src = guide.read_script(item.script)
            used = set(re.findall(r"stream\('(\w+)'\)", src)) | set(re.findall(r"icu\.streams\.get\('(\w+)'\)", src))
            custom = used - BUILT_IN_STREAMS
            self.assertTrue(custom <= streams, f"{item.script} reads unknown streams {custom - streams}")
            self.assertEqual(custom, set(item.needs), f"{item.script}: 'needs' in make_site_guide.py")


class ItemsTest(unittest.TestCase):
    def setUp(self):
        self.items = {icu_setup.key_of(i): i for i in icu_setup.wanted_items()}

    def test_every_guide_item_once(self):
        n = len(guide.STREAMS) + len(guide.ACTIVITY_FIELDS) + len(guide.INTERVAL_FIELDS) + len(guide.CHARTS)
        self.assertEqual(len(self.items), n)

    def test_script_streams_come_first(self):
        streams = [i for i in icu_setup.wanted_items() if i["type"] == "ACTIVITY_STREAM"]
        flags = [i["content"]["processes_fit_messages"] for i in streams]
        self.assertEqual(flags, sorted(flags, reverse=True))

    def test_stream_sources(self):
        grit = self.items[("ACTIVITY_STREAM", "MtbGrit")]["content"]
        self.assertTrue(grit["processes_fit_messages"])
        self.assertIn("m.mtb_grit || m.grit", grit["script"])
        self.assertEqual(grit["fit_record_field"], "")
        fork = self.items[("ACTIVITY_STREAM", "FaFront")]["content"]
        self.assertEqual((fork["fit_record_field"], fork["script"], fork["processes_fit_messages"]), ("front_suspension", "", False))
        self.assertEqual(fork["units"], "state")

    def test_fields_use_their_scripts(self):
        grit = self.items[("ACTIVITY_FIELD", "MtbGrit")]["content"]
        self.assertTrue(grit["processes_fit_messages"])
        self.assertIn("mtb_total_grit", grit["script"])
        self.assertEqual((grit["aggregate"], grit["suffix"], grit["type"]), ("SUM", "kGrit", "numeric"))
        self.assertEqual(self.items[("ACTIVITY_FIELD", "MtbJumps")]["content"]["suffix"], "")
        lap = self.items[("INTERVAL_FIELD", "IntMtbGrit")]["content"]
        self.assertFalse(lap["processes_fit_messages"])
        self.assertTrue(lap["total"] and lap["average"])
        self.assertIn("stream('MtbGrit')", lap["script"])

    def test_chart(self):
        chart = self.items[("ACTIVITY_CHART", "name:MTB Dynamics")]
        self.assertEqual(set(chart["content"]), {"link", "script", "width", "height"})
        self.assertTrue(chart["content"]["script"].startswith("// intervals.icu custom activity chart"))


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.wanted = icu_setup.wanted_items()

    def existing(self, key, **content):
        item = next(i for i in self.wanted if icu_setup.key_of(i) == key)
        return {**item, "id": 7, "index": 3, "content": {**item["content"], **content}}

    def test_create_all_on_an_empty_account(self):
        steps = icu_setup.plan([], self.wanted)
        self.assertEqual({s[0] for s in steps}, {"create"})

    def test_unchanged_item_is_ok_and_display_settings_are_kept(self):
        old = self.existing(("ACTIVITY_STREAM", "MtbGrit"), color="#000000")
        step = next(s for s in icu_setup.plan([old], self.wanted) if icu_setup.key_of(s[1]) == ("ACTIVITY_STREAM", "MtbGrit"))
        self.assertEqual(step[0], "ok")
        self.assertEqual(step[1]["content"]["color"], "#000000")

    def test_changed_script_is_updated(self):
        old = self.existing(("ACTIVITY_FIELD", "MtbFlow"), script="{ 1 }", fit_session_field="mtb_flow_score",
                            processes_fit_messages=False)
        step = next(s for s in icu_setup.plan([old], self.wanted) if s[2] is not None)
        self.assertEqual(step[0], "update")
        self.assertEqual(set(step[3]), {"script", "fit_session_field", "processes_fit_messages"})

    def test_apply_creates_after_the_existing_index_and_updates_by_id(self):
        old = self.existing(("ACTIVITY_FIELD", "MtbFlow"), script="{ 1 }")
        icu = FakeIcu(items=[old])
        failed = icu_setup.apply(icu, icu_setup.plan(icu.items, self.wanted), dry_run=False, log=lambda s: None)
        self.assertEqual(failed, 0)
        self.assertEqual(len(icu.created), len(self.wanted) - 1)
        fields = [c for c in icu.created if c["type"] == "ACTIVITY_FIELD"]
        self.assertEqual(fields[0]["index"], 4)
        streams = [c for c in icu.created if c["type"] == "ACTIVITY_STREAM"]
        self.assertEqual([s["index"] for s in streams], list(range(1, 13)))
        (item_id, body), = icu.updated
        self.assertEqual((item_id, body["id"], body["index"]), (7, 7, 3))

    def test_dry_run_changes_nothing_and_failures_are_counted(self):
        icu = FakeIcu()
        self.assertEqual(icu_setup.apply(icu, icu_setup.plan([], self.wanted), dry_run=True, log=lambda s: None), 0)
        self.assertEqual(icu.created, [])
        bad = {**self.existing(("ACTIVITY_FIELD", "MtbFlow"), script="{ 1 }"), "id": 666}
        icu = FakeIcu(items=[bad])
        self.assertEqual(icu_setup.apply(icu, icu_setup.plan(icu.items, self.wanted), dry_run=False, log=lambda s: None), 1)

    def test_lookalike_made_by_hand_is_reported_not_touched(self):
        manual = {"id": 9, "type": "ACTIVITY_STREAM", "name": "MTB Grit", "content": {"code": "MTBGrit"}}
        steps = icu_setup.plan([manual], self.wanted)
        self.assertTrue(all(s[2] is None for s in steps))
        notes = icu_setup.lookalikes([manual], self.wanted)
        self.assertEqual(len(notes), 1)
        self.assertIn("MTBGrit", notes[0])


class ReprocessTest(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "docs", "sample", "mtb-dynamics-sample.fit"), "rb") as f:
            self.karoo_fit = f.read()
        self.acts = [
            {"id": "i1", "type": "MountainBikeRide", "source": "OAUTH_CLIENT", "start_date_local": "2026-10-03T12:00:00"},
            {"id": "i2", "type": "Ride", "source": "OAUTH_CLIENT", "start_date_local": "2026-10-01T12:00:00"},
            {"id": "i3", "type": "Run", "source": "OAUTH_CLIENT", "start_date_local": "2026-10-02T12:00:00"},
            {"id": "i4", "type": "Ride", "source": "STRAVA", "start_date_local": "2026-09-30T12:00:00"},
            {"id": "i5", "type": "Ride", "source": "UPLOAD", "start_date_local": "2026-09-29T12:00:00"},
            {"id": "i6", "type": "Ride", "source": "UPLOAD", "start_date_local": "2026-09-28T12:00:00"},
        ]
        self.files = {"i1": self.karoo_fit, "i2": b".FIT plain ride without developer fields", "i3": self.karoo_fit,
                      "i6": self.karoo_fit}

    def test_marker_detection(self):
        self.assertTrue(icu_setup.has_mtb_data(self.karoo_fit))
        self.assertFalse(icu_setup.has_mtb_data(self.files["i2"]))

    def test_only_rides_with_mtb_data_are_listed_oldest_first(self):
        icu = FakeIcu(activities=self.acts, files=self.files)
        lines = []
        rides = icu_setup.rides_with_data(icu, 30, log=lines.append)
        self.assertEqual([a["id"] for a in rides], ["i6", "i1"])      # no run, no Strava import, no plain ride
        self.assertTrue(any("i5" in s and "no file" in s for s in lines))
        self.assertEqual(icu.reprocessed, [])

    def test_snippet_reprocesses_the_listed_rides(self):
        path = os.path.join(tempfile.mkdtemp(), "reprocess.js")
        icu_setup.write_snippet(path, [{"id": "i6"}, {"id": "i1"}])
        with open(path) as f:
            js = f.read()
        self.assertIn('const ids = ["i6", "i1"]', js)
        self.assertIn("/api/activity/${id}/reprocess-file", js)
        self.assertIn("keepIntervals: true, keepCustomFields: true", js)
        self.assertNotIn("{{", js)


if __name__ == "__main__":
    unittest.main()
