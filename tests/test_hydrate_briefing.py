"""hydrate_spec — fills briefing widget data via database queries."""
from unittest.mock import patch

from utils.hydrate import hydrate_spec


@patch("utils.hydrate.run_guarded")
def test_line_chart_query_runs_and_attaches_data(mock_run_guarded):
    mock_run_guarded.return_value = {"rows": [{"x": "Mar 21", "y": 78.1}]}
    spec = {
        "kind": "briefing",
        "headline": "h", "tldr": "t",
        "sections": [{
            "label": "Trend", "layout": "full-width",
            "widgets": [{
                "type": "line_chart", "label": "WTI",
                "query": "SELECT date::text x, wti_price y FROM market.spot_prices",
            }],
        }],
    }
    out = hydrate_spec(spec)
    w = out["sections"][0]["widgets"][0]
    assert w["data"] == [{"x": "Mar 21", "y": 78.1}]
    # Hydration is additive — `query` is preserved so the spec can be
    # round-tripped back to the DB and re-hydrated on the next read.
    assert w["query"] == "SELECT date::text x, wti_price y FROM market.spot_prices"


@patch("utils.hydrate.run_guarded")
def test_table_query_runs_and_attaches_rows(mock_run_guarded):
    mock_run_guarded.return_value = {"rows": [
        {"operator": "Diamondback", "wells": 1248},
    ]}
    spec = {
        "kind": "briefing",
        "headline": "h", "tldr": "t",
        "sections": [{
            "label": "Top operators", "layout": "full-width",
            "widgets": [{
                "type": "table",
                "columns": [
                    {"key": "operator", "label": "Operator"},
                    {"key": "wells", "label": "Wells", "align": "right"},
                ],
                "query": "SELECT ...",
            }],
        }],
    }
    out = hydrate_spec(spec)
    w = out["sections"][0]["widgets"][0]
    assert w["rows"] == [{"operator": "Diamondback", "wells": 1248}]
    assert w["query"] == "SELECT ..."
    # Columns preserved verbatim — server does NOT infer them.
    assert w["columns"][1]["align"] == "right"


@patch("utils.hydrate.run_guarded")
def test_callout_with_query_and_template(mock_run_guarded):
    mock_run_guarded.return_value = {"rows": [{"count": 287}]}
    spec = {
        "kind": "briefing",
        "headline": "h", "tldr": "t",
        "sections": [{
            "label": "x", "layout": "3-col",
            "widgets": [{
                "type": "callout", "label": "Permian rigs",
                "query": "SELECT count(*) AS count FROM rigs WHERE basin IN ('MIDLAND','DELAWARE')",
                "value_template": "{count} rigs",
            }],
        }],
    }
    out = hydrate_spec(spec)
    w = out["sections"][0]["widgets"][0]
    assert w["value"] == "287 rigs"
    # Inputs survive hydration so the spec round-trips.
    assert "query" in w and w["query"].startswith("SELECT count(*)")
    assert w["value_template"] == "{count} rigs"


@patch("utils.hydrate.run_guarded")
def test_widget_query_failure_isolated(mock_run_guarded):
    mock_run_guarded.side_effect = Exception("boom")
    spec = {
        "kind": "briefing",
        "headline": "h", "tldr": "t",
        "sections": [{
            "label": "x", "layout": "full-width",
            "widgets": [{"type": "line_chart", "label": "x", "query": "SELECT 1"}],
        }],
    }
    out = hydrate_spec(spec)
    w = out["sections"][0]["widgets"][0]
    assert w["data"] == []
    assert "boom" in w["_error"]


def test_commentary_passthrough():
    spec = {
        "kind": "briefing",
        "headline": "h", "tldr": "t",
        "sections": [{
            "label": "x", "layout": "full-width",
            "widgets": [{"type": "commentary", "text": "ok"}],
        }],
    }
    out = hydrate_spec(spec)
    assert out["sections"][0]["widgets"][0] == {"type": "commentary", "text": "ok"}


def test_error_spec_passthrough():
    spec = {"kind": "error", "reason": "Cannot answer.", "clarify_ask": None}
    assert hydrate_spec(spec) == spec


def test_callout_query_path():
    """Query-callouts (with value_template) can hydrate without a kind field.
    Confirm the path works end-to-end."""
    with patch("utils.hydrate.run_guarded") as mock_run:
        mock_run.return_value = {"rows": [{"count": 14}]}
        spec = {
            "sections": [{
                "layout": "3-col",
                "widgets": [{
                    "type": "callout",
                    "label": "Permian rigs",
                    "query": "SELECT count(*) AS count FROM rigs",
                    "value_template": "{count} rigs",
                }],
            }],
        }
        out = hydrate_spec(spec)
        w = out["sections"][0]["widgets"][0]
        assert w["value"] == "14 rigs"
        # Inputs preserved on the hydrated widget.
        assert w["query"].startswith("SELECT count(*)")
        assert w["value_template"] == "{count} rigs"


def test_hydrate_spec_scrubs_nan_and_inf():
    """JS JSON.parse rejects NaN/Infinity; the spec must round-trip via dumps→parse."""
    import json

    from utils.hydrate import hydrate_spec

    # Build a spec with a chart whose data row hardcodes NaN + Inf — bypasses
    # hydration's SQL path so we don't need a DB. The non-section path
    # (passthrough) should also scrub.
    spec = {
        "kind": "briefing",
        "headline": "x",
        "tldr": "t",
        "sections": [
            {
                "label": "S",
                "layout": "full-width",
                "widgets": [
                    {
                        "type": "callout",
                        "label": "Futures",
                        "value": {"m1": float("nan"), "m12": 1.5, "m24": float("inf")},
                    },
                ],
            },
        ],
    }
    out = hydrate_spec(spec)
    widget = out["sections"][0]["widgets"][0]
    assert widget["value"]["m1"] is None
    assert widget["value"]["m12"] == 1.5
    assert widget["value"]["m24"] is None

    # Must JSON-encode without allow_nan AND parse back equivalently.
    text = json.dumps(out, allow_nan=False)
    round_trip = json.loads(text)
    assert round_trip["sections"][0]["widgets"][0]["value"]["m1"] is None


def test_hydrate_spec_scrubs_nan_in_sectionless_spec():
    """Specs without 'sections' (e.g. kind=error) still get scrubbed."""
    import json

    from utils.hydrate import hydrate_spec

    spec = {"kind": "error", "reason": "bad", "extra": float("nan")}
    out = hydrate_spec(spec)
    assert out["extra"] is None
    json.dumps(out, allow_nan=False)  # must not raise
