"""utils.briefing_spec — the moved spec-shape contract (was crude_analyst._models)."""
import pytest

from utils.briefing_spec import (
    validate_briefing_spec,
    validate_error_spec,
    validate_widget,
)


def _min_spec():
    return {
        "kind": "briefing",
        "headline": "Permian gas takeaway tightens",
        "tldr": "Three plants at capacity through Q3.",
        "sections": [{
            "label": "Summary",
            "layout": "full-width",
            "widgets": [{"type": "commentary", "text": "Capacity is binding."}],
        }],
    }


def test_valid_briefing_spec_round_trips():
    out = validate_briefing_spec(_min_spec())
    assert out["kind"] == "briefing"
    assert out["headline"].startswith("Permian")
    assert out["sections"][0]["widgets"][0]["type"] == "commentary"


def test_missing_headline_raises():
    spec = _min_spec()
    del spec["headline"]
    with pytest.raises(ValueError, match="headline"):
        validate_briefing_spec(spec)


def test_unknown_widget_type_raises():
    with pytest.raises(ValueError, match="unknown type"):
        validate_widget({"type": "sankey", "text": "x"})


def test_error_spec_round_trips():
    out = validate_error_spec({"kind": "error", "reason": "no data for that county"})
    assert out == {"kind": "error", "reason": "no data for that county"}
