"""Unit tests for the pure (no-Fabric-connection) logic in
src/matching/fabric_matching.py -- shape building, rules A-D, and the
credit substring-matching/duplicate-detection helpers. Does not exercise
run_fabric_matching() itself, which requires a live Fabric connection and
is gated by _fabric_configured()."""
from src.matching.fabric_matching import (
    _amounts_tie_out,
    _build_invoice_shapes,
    _Candidates,
    _earliest_of_type,
    _keystone_credit_record,
    _match_credit,
    _pick_credit,
    _shape_target,
)


def _line(invoice_number, line_type, charge_amount=None, payment_amount=None,
          ro_number=None, line_date=None):
    return {
        "invoice_number": invoice_number,
        "line_type": line_type,
        "charge_amount": charge_amount,
        "payment_amount": payment_amount,
        "ro_number": ro_number,
        "line_date": line_date,
    }


def test_rule_a_single_charge_targets_vendorbill():
    shapes = _build_invoice_shapes([_line("INV1", "CHARGE", charge_amount=100.0)])
    stmt_amount, table = _shape_target(shapes["INV1"])
    assert stmt_amount == 100.0
    assert table == "netsuite_vendorbill"


def test_rule_b_single_credit_targets_vendorcredit():
    shapes = _build_invoice_shapes([_line("INV2", "CREDIT", charge_amount=-50.0)])
    stmt_amount, table = _shape_target(shapes["INV2"])
    assert stmt_amount == 50.0
    assert table == "netsuite_vendorcredit"


def test_rule_c_charge_plus_credit_tying_out_targets_vendorbill():
    shapes = _build_invoice_shapes([
        _line("INV3", "CHARGE", charge_amount=75.0),
        _line("INV3", "CREDIT", charge_amount=-75.0),
    ])
    stmt_amount, table = _shape_target(shapes["INV3"])
    assert stmt_amount == 75.0
    assert table == "netsuite_vendorbill"


def test_rule_d_non_tying_charge_and_credit_falls_through_to_earliest_charge():
    shapes = _build_invoice_shapes([
        _line("INV4", "CHARGE", charge_amount=200.0, line_date="2026-01-01"),
        _line("INV4", "CREDIT", charge_amount=-40.0, line_date="2026-02-01"),
    ])
    stmt_amount, table = _shape_target(shapes["INV4"])
    assert stmt_amount == 200.0
    assert table == "netsuite_vendorbill"


def test_rule_d_picks_earliest_charge_among_multiple():
    shapes = _build_invoice_shapes([
        _line("INV5", "CHARGE", charge_amount=300.0, line_date="2026-03-01"),
        _line("INV5", "CHARGE", charge_amount=300.0, line_date="2026-01-15"),
        _line("INV5", "CREDIT", charge_amount=-10.0, line_date="2026-02-01"),
    ])
    stmt_amount, table = _shape_target(shapes["INV5"])
    assert stmt_amount == 300.0
    assert table == "netsuite_vendorbill"
    earliest = _earliest_of_type(shapes["INV5"]["lines"], "CHARGE")
    assert earliest["line_date"] == "2026-01-15"


def test_rule_d_falls_back_to_earliest_credit_when_no_charge():
    shapes = _build_invoice_shapes([
        _line("INV6", "CREDIT", charge_amount=-20.0, line_date="2026-02-01"),
        _line("INV6", "CREDIT", charge_amount=-30.0, line_date="2026-01-01"),
    ])
    stmt_amount, table = _shape_target(shapes["INV6"])
    assert stmt_amount == 30.0
    assert table == "netsuite_vendorcredit"


def test_earliest_of_type_missing_date_sorts_last():
    lines = [
        _line("INV7", "CHARGE", charge_amount=1.0, line_date=None),
        _line("INV7", "CHARGE", charge_amount=2.0, line_date="2026-01-01"),
    ]
    earliest = _earliest_of_type(lines, "CHARGE")
    assert earliest["charge_amount"] == 2.0


def test_payment_line_without_invoice_number_is_dropped():
    shapes = _build_invoice_shapes([
        _line(None, "PAYMENT", payment_amount=99.0),
        _line("INV8", "PAYMENT", payment_amount=99.0),
    ])
    assert list(shapes.keys()) == ["INV8"]


def test_match_credit_single_substring_match():
    total, count = _match_credit("435584", 100.0, [("CMA435584-1", 100.0)])
    assert total == 100.0
    assert count == 1


def test_match_credit_no_match():
    total, count = _match_credit("999999", 100.0, [("CMA435584-1", 100.0)])
    assert total is None
    assert count == 0


def test_match_credit_multiple_candidates_disambiguated_by_amount():
    candidates = [("CMA435584-1", 50.0), ("CMA435584-2", 100.0)]
    total, count = _match_credit("435584", 100.0, candidates)
    assert total == 100.0
    assert count == 2


def test_match_credit_multiple_candidates_ambiguous_reports_none():
    candidates = [("CMA435584-1", 100.0), ("CMA435584-2", 100.0)]
    total, count = _match_credit("435584", 999.0, candidates)
    assert total is None
    assert count == 2


def test_two_credits_that_tie_out_the_one_numbered_exactly_as_the_invoice_wins():
    # Keystone BANC7740: credit BANC7740 (9/2) and BANC7740-1 (9/4), both $99.00.
    candidates = [("banc7740-1", 99.0), ("banc7740", 99.0)]
    assert _pick_credit("banc7740", 99.0, candidates) == ("banc7740", 99.0, 2)
    assert _match_credit("banc7740", 99.0, candidates) == (99.0, 2)


def test_two_tying_credits_neither_numbered_as_the_invoice_stay_ambiguous():
    candidates = [("banc7740-1", 99.0), ("cmbanc7740", 99.0)]
    assert _pick_credit("banc7740", 99.0, candidates) == (None, None, 2)


def test_two_identical_credits_stay_ambiguous():
    assert _pick_credit("banc7740", 99.0, [("banc7740", 99.0), ("banc7740", 99.0)]) == (None, None, 2)


def test_the_credit_record_is_the_chosen_one_not_the_first_of_that_amount():
    credits = _Candidates()
    credits.records[("banc7740-1", 99.0)] = [{"tranid": "BANC7740-1", "id": 1}]
    credits.records[("banc7740", 99.0)] = [{"tranid": "BANC7740", "id": 2}]
    candidates = [("banc7740-1", 99.0), ("banc7740", 99.0)]
    chosen, total, _ = _pick_credit("banc7740", 99.0, candidates)
    assert _keystone_credit_record(credits, candidates, "BANC7740", total, chosen)["id"] == 2


def test_amounts_tie_out_within_epsilon():
    assert _amounts_tie_out(100.0, 100.004)
    assert not _amounts_tie_out(100.0, 100.01)
