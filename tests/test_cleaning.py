import unittest
from datetime import date

from nyc311_factory.cleaning import RecordProcessor, clean_zip
from nyc311_factory.config import Window
from nyc311_factory.contract import Reason
from nyc311_factory.population import Population
from tests.helpers import make_config

WINDOW = Window(date(2023, 1, 1), date(2024, 1, 1))
PLACEHOLDERS = {"00000", "N/A", "A/N"}


def processor():
    cfg = make_config("/tmp/unused")
    pop = Population({"10001": 5000, "11201": 9000}, cfg.zip_prefix_borough)
    return RecordProcessor(cfg, pop)


def record(**over):
    base = {"unique_key": "1", "created_date": "2023-05-01T10:00:00.000", "closed_date": "2023-05-01T12:30:00.000",
            "agency": "HPD", "complaint_type": "PLUMBING", "descriptor": "X", "status": "Closed",
            "incident_zip": "10001", "borough": "MANHATTAN"}
    base.update(over)
    return {k: v for k, v in base.items() if v is not None}


class CleaningTests(unittest.TestCase):
    def test_valid_record_gets_derived_columns(self):
        row, code, _ = processor().process(record(), WINDOW)
        self.assertIsNone(code)
        self.assertEqual(row["resolution_hours"], 2.5)
        self.assertEqual(row["created_month"], "2023-05")
        self.assertEqual(row["created_dow"], 0)  # Monday
        self.assertEqual(row["population_zip"], 5000)

    def test_closed_before_created_is_quarantined(self):
        _, code, _ = processor().process(record(closed_date="2023-04-30T10:00:00.000"), WINDOW)
        self.assertEqual(code, Reason.CLOSED_BEFORE_CREATED)

    def test_boundary_closed_equals_created_is_valid_zero_duration(self):
        p = processor()
        row, code, _ = p.process(record(closed_date="2023-05-01T10:00:00.000"), WINDOW)
        self.assertIsNone(code)
        self.assertEqual(row["resolution_hours"], 0.0)
        self.assertEqual(p.stats["zero_duration_cases"], 1)

    def test_open_case_has_null_duration(self):
        row, code, _ = processor().process(record(closed_date=None, status="Open"), WINDOW)
        self.assertIsNone(code)
        self.assertIsNone(row["resolution_hours"])
        self.assertEqual(row["is_closed"], 0)

    def test_closed_status_without_date_is_quarantined(self):
        _, code, _ = processor().process(record(closed_date=None), WINDOW)
        self.assertEqual(code, Reason.CLOSED_WITHOUT_DATE)

    def test_window_end_is_exclusive_and_start_inclusive(self):
        p = processor()
        self.assertEqual(p.process(record(created_date="2024-01-01T00:00:00.000", closed_date=None, status="Open"),
                                   WINDOW)[1], Reason.OUT_OF_WINDOW)
        row, code, _ = p.process(record(unique_key="2", created_date="2023-01-01T00:00:00.000",
                                        closed_date=None, status="Open"), WINDOW)
        self.assertIsNone(code)

    def test_missing_required_and_invalid_date_and_bad_type(self):
        p = processor()
        self.assertEqual(p.process(record(complaint_type=None), WINDOW)[1], Reason.MISSING_REQUIRED)
        self.assertEqual(p.process(record(created_date="garbage"), WINDOW)[1], Reason.INVALID_CREATED_DATE)
        self.assertEqual(p.process(record(closed_date="garbage"), WINDOW)[1], Reason.INVALID_CLOSED_DATE)
        self.assertEqual(p.process(record(unique_key=123), WINDOW)[1], Reason.BAD_TYPE)

    def test_complaint_type_outside_configured_scope_is_quarantined(self):
        from dataclasses import replace
        cfg = replace(make_config("/tmp/unused"), complaint_types=("PLUMBING",))
        p = RecordProcessor(cfg, Population({}, cfg.zip_prefix_borough))
        self.assertIsNone(p.process(record(), WINDOW)[1])
        self.assertEqual(p.process(record(unique_key="2", complaint_type="NOISE"), WINDOW)[1],
                         Reason.COMPLAINT_TYPE_OUT_OF_SCOPE)

    def test_complaint_type_case_variants_are_unified(self):
        p = processor()
        row, _, _ = p.process(record(complaint_type="Water Leak"), WINDOW)
        self.assertEqual(row["complaint_type"], "WATER LEAK")
        self.assertEqual(p.stats["complaint_type_case_normalized"], 1)

    def test_duplicate_key_second_occurrence_is_quarantined(self):
        p = processor()
        self.assertIsNone(p.process(record(), WINDOW)[1])
        self.assertEqual(p.process(record(), WINDOW)[1], Reason.DUPLICATE_KEY)

    def test_zip_cleaning_rules(self):
        self.assertEqual(clean_zip(" 10001 ", PLACEHOLDERS), ("10001", False))
        self.assertEqual(clean_zip("10001-1234", PLACEHOLDERS), ("10001", False))
        self.assertEqual(clean_zip("00000", PLACEHOLDERS), (None, True))
        self.assertEqual(clean_zip("n/a", PLACEHOLDERS), (None, True))
        self.assertEqual(clean_zip("ABCDE", PLACEHOLDERS), (None, True))
        self.assertEqual(clean_zip(None, PLACEHOLDERS), (None, False))

    def test_unspecified_borough_is_imputed_from_zip_and_mismatch_flagged(self):
        p = processor()
        row, _, _ = p.process(record(borough="Unspecified"), WINDOW)
        self.assertEqual((row["borough"], row["borough_mismatch"]), ("MANHATTAN", 0))
        row, _, _ = p.process(record(unique_key="9", borough="BRONX"), WINDOW)
        self.assertEqual((row["borough"], row["borough_mismatch"]), ("BRONX", 1))
        self.assertEqual(p.process(record(unique_key="8", borough="ATLANTIS"), WINDOW)[1], Reason.BAD_BOROUGH)

    def test_unknown_zip_keeps_row_with_null_population(self):
        row, code, _ = processor().process(record(incident_zip="10099"), WINDOW)
        self.assertIsNone(code)
        self.assertIsNone(row["population_zip"])


if __name__ == "__main__":
    unittest.main()
