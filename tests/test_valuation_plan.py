import pytest
from server.valuation.orchestrator import validate_plan


def test_validate_plan_empty_ok():
    plan = validate_plan({})
    assert plan == {}


def test_validate_plan_none_ok():
    """None plan is equivalent to empty dict — server uses defaults."""
    assert validate_plan(None) == {}


def test_validate_plan_b_override():
    plan = validate_plan({"b": 0.9})
    assert plan == {"b": 0.9}


def test_validate_plan_b_cohort_median():
    plan = validate_plan({"b": "cohort_median"})
    assert plan == {"b": "cohort_median"}


def test_validate_plan_cohort_override():
    plan = validate_plan({"cohort": {"filter_sql": "basin='X'"}})
    assert plan["cohort"]["filter_sql"] == "basin='X'"


def test_validate_plan_both_fields():
    plan = validate_plan({"cohort": {"filter_sql": "x"}, "b": 0.85})
    assert plan == {"cohort": {"filter_sql": "x"}, "b": 0.85}


def test_validate_plan_rejects_unknown_field():
    with pytest.raises(ValueError, match="unknown plan field"):
        validate_plan({"strategy": "auto"})


def test_validate_plan_rejects_multiple_unknown_fields():
    with pytest.raises(ValueError, match=r"unknown plan field"):
        validate_plan({"x": 1, "y": 2})


def test_validate_plan_rejects_b_out_of_range_high():
    with pytest.raises(ValueError, match="b must be"):
        validate_plan({"b": 5.0})


def test_validate_plan_rejects_b_out_of_range_low():
    with pytest.raises(ValueError, match="b must be"):
        validate_plan({"b": -0.1})


def test_validate_plan_rejects_b_wrong_type():
    with pytest.raises(ValueError, match="b must be"):
        validate_plan({"b": "median"})            # wrong string value


def test_validate_plan_rejects_non_dict_plan():
    with pytest.raises(ValueError, match="object"):
        validate_plan("not-a-plan")


def test_validate_plan_rejects_non_dict_cohort():
    with pytest.raises(ValueError, match="object"):
        validate_plan({"cohort": "filter_sql_string"})
