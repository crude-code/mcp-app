"""Spec validation helpers for the briefing spec — stdlib only (no pydantic).

The single source of truth for briefing-spec shape, used by the server's
``run_data_analysis`` tool (and, until Plan 3, the legacy persist endpoint)
to validate Claude-authored specs before hydration. Moved here from
``crude_analyst._models`` in the agents→tools collapse; the package copy
survives until Plan 3 deletes the package.

If you change a field here, the renderer's TypeScript widget types
(`renderer/src/widgets.tsx`) may also need an update.
"""

from typing import Callable

# ---------------------------------------------------------------------------
# Allowed literal sets
# ---------------------------------------------------------------------------
_TONE_VALUES = {"neutral", "bullish", "bearish", "warning", None}
_LAYOUT_VALUES = {"full-width", "3-col", "2-col"}
_ORIENTATION_VALUES = {"vertical", "horizontal", None}
_ALIGN_VALUES = {"left", "right", "center", None}
_KIND_VALUES = {"briefing", "error"}


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _require_str(d: dict, key: str, label: str) -> str:
    """Assert key is present, value is a non-empty str. Raises ValueError."""
    if key not in d:
        raise ValueError(f"{label}: '{key}' is required")
    val = d[key]
    if not isinstance(val, str):
        raise ValueError(
            f"{label}: '{key}' must be a string, got {type(val).__name__!r}"
        )
    if len(val) < 1:
        raise ValueError(f"{label}: '{key}' must be non-empty")
    return val


def _optional_str(d: dict, key: str, label: str):
    """Return str value or None. If present, must be a non-empty str."""
    val = d.get(key)
    if val is None:
        return None
    if not isinstance(val, str):
        raise ValueError(
            f"{label}: '{key}' must be a string, got {type(val).__name__!r}"
        )
    if len(val) < 1:
        raise ValueError(f"{label}: '{key}' must be non-empty")
    return val


# ---------------------------------------------------------------------------
# Widget validators — each returns a cleaned dict (no None values)
# ---------------------------------------------------------------------------

def validate_commentary(w: dict) -> dict:
    label = "commentary widget"
    text = _require_str(w, "text", label)
    tone = _optional_str(w, "tone", label)
    if tone is not None and tone not in _TONE_VALUES:
        raise ValueError(f"{label}: 'tone' must be one of {_TONE_VALUES!r}, got {tone!r}")
    out = {"type": "commentary", "text": text}
    if tone is not None:
        out["tone"] = tone
    return out


def validate_callout(w: dict) -> dict:
    label = "callout widget"
    callout_label = _require_str(w, "label", label)
    code = _optional_str(w, "code", label)
    query = _optional_str(w, "query", label)
    value_template = _optional_str(w, "value_template", label)
    if not code and not query:
        raise ValueError(f"{label}: must have 'code' or 'query'")
    out = {"type": "callout", "label": callout_label}
    if code is not None:
        out["code"] = code
    if query is not None:
        out["query"] = query
    if value_template is not None:
        out["value_template"] = value_template
    return out


_SERIES_ALLOWED_KEYS = {"key", "label", "color", "dashed"}


def _validate_series(series, label: str) -> list[dict]:
    """Validate the ``series`` array on a line/bar chart widget.

    Each entry must be an object (dict) with at least ``key: str`` (the column
    name to plot from the hydrated row data). Optional fields: ``label: str``,
    ``color: str``, ``dashed: bool``. Raising on bad shape — rather than
    silently coercing — is intentional: the persist endpoint surfaces the
    error to the inner agent so it can correct the spec on retry.
    """
    if not isinstance(series, list):
        raise ValueError(
            f"{label}: 'series' must be a list of objects, got {type(series).__name__!r}"
        )
    if len(series) == 0:
        raise ValueError(f"{label}: 'series' must be non-empty if provided")
    cleaned: list[dict] = []
    for i, s in enumerate(series):
        entry_label = f"{label}: series[{i}]"
        if not isinstance(s, dict):
            raise ValueError(
                f"{entry_label}: must be an object with a 'key' field, "
                f"got {type(s).__name__!r}. Use [{{'key': '<col>', 'label': '<text>'}}]."
            )
        unknown = set(s.keys()) - _SERIES_ALLOWED_KEYS
        if unknown:
            raise ValueError(
                f"{entry_label}: unknown fields {sorted(unknown)!r}; "
                f"allowed: {sorted(_SERIES_ALLOWED_KEYS)!r}"
            )
        out: dict = {"key": _require_str(s, "key", entry_label)}
        lbl = _optional_str(s, "label", entry_label)
        if lbl is not None:
            out["label"] = lbl
        color = _optional_str(s, "color", entry_label)
        if color is not None:
            out["color"] = color
        if "dashed" in s:
            if not isinstance(s["dashed"], bool):
                raise ValueError(
                    f"{entry_label}: 'dashed' must be a bool, "
                    f"got {type(s['dashed']).__name__!r}"
                )
            out["dashed"] = s["dashed"]
        cleaned.append(out)
    return cleaned


def _validate_chart_base(w: dict, label: str) -> dict:
    chart_label = _require_str(w, "label", label)
    query = _require_str(w, "query", label)
    out = {"label": chart_label, "query": query}
    if w.get("series") is not None:
        out["series"] = _validate_series(w["series"], label)
    return out


def validate_line_chart(w: dict) -> dict:
    out = _validate_chart_base(w, "line_chart widget")
    out["type"] = "line_chart"
    return out


def validate_bar_chart(w: dict) -> dict:
    out = _validate_chart_base(w, "bar_chart widget")
    out["type"] = "bar_chart"
    orientation = w.get("orientation")
    if orientation not in _ORIENTATION_VALUES:
        raise ValueError(
            f"bar_chart widget: 'orientation' must be one of {_ORIENTATION_VALUES!r}"
        )
    if orientation is not None:
        out["orientation"] = orientation
    return out


def validate_table_column(col: dict) -> dict:
    key = _require_str(col, "key", "table column")
    col_label = _require_str(col, "label", "table column")
    align = col.get("align")
    if align not in _ALIGN_VALUES:
        raise ValueError(f"table column: 'align' must be one of {_ALIGN_VALUES!r}")
    out = {"key": key, "label": col_label}
    if align is not None:
        out["align"] = align
    return out


def validate_table(w: dict) -> dict:
    label = "table widget"
    cols_raw = w.get("columns")
    if not cols_raw:
        raise ValueError(f"{label}: 'columns' is required and must be non-empty")
    query = _require_str(w, "query", label)
    out: dict = {
        "type": "table",
        "columns": [validate_table_column(c) for c in cols_raw],
        "query": query,
    }
    tbl_label = _optional_str(w, "label", label)
    if tbl_label is not None:
        out["label"] = tbl_label
    footnote = _optional_str(w, "footnote", label)
    if footnote is not None:
        out["footnote"] = footnote
    return out


# ---------------------------------------------------------------------------
# Widget registry
# ---------------------------------------------------------------------------
#
# Maps widget `type` string → validator function. Seeded below with the
# platform's own widget validators; domain packages (e.g. crude_valuation)
# call `register_widget()` at import time to add their own.

_WIDGET_REGISTRY: dict[str, Callable[[dict], dict]] = {}


def register_widget(name: str, validator: Callable[[dict], dict]) -> None:
    """Register a widget type and its validator.

    Idempotent: re-registering ``name`` with the *same* ``validator`` is a
    no-op. Re-registering ``name`` with a *different* validator raises
    ``ValueError`` — catches accidental name collisions across domain
    packages that both register widgets at import time.
    """
    existing = _WIDGET_REGISTRY.get(name)
    if existing is not None and existing is not validator:
        raise ValueError(
            f"widget type {name!r} is already registered to a different "
            f"validator (existing: {existing!r}, new: {validator!r})"
        )
    _WIDGET_REGISTRY[name] = validator


def validate_widget(w: dict) -> dict:
    wtype = w.get("type")
    validator = _WIDGET_REGISTRY.get(wtype)
    if validator is None:
        known = sorted(_WIDGET_REGISTRY.keys())
        raise ValueError(
            f"widget: unknown type {wtype!r} (known: {known})"
        )
    return validator(w)


# Seed the registry with the platform's built-in widget validators.
register_widget("commentary", validate_commentary)
register_widget("callout", validate_callout)
register_widget("line_chart", validate_line_chart)
register_widget("bar_chart", validate_bar_chart)
register_widget("table", validate_table)


# ---------------------------------------------------------------------------
# Section validator
# ---------------------------------------------------------------------------

def validate_section(s: dict) -> dict:
    label_val = _require_str(s, "label", "section")
    layout = s.get("layout")
    if layout not in _LAYOUT_VALUES:
        raise ValueError(f"section: 'layout' must be one of {_LAYOUT_VALUES!r}, got {layout!r}")
    widgets_raw = s.get("widgets")
    if not widgets_raw:
        raise ValueError("section: 'widgets' is required and must be non-empty")
    return {
        "label": label_val,
        "layout": layout,
        "widgets": [validate_widget(w) for w in widgets_raw],
    }


# ---------------------------------------------------------------------------
# Top-level spec validators
# ---------------------------------------------------------------------------

def validate_briefing_spec(spec: dict) -> dict:
    if spec.get("kind") != "briefing":
        raise ValueError("BriefingSpec: 'kind' must be 'briefing'")
    headline = _require_str(spec, "headline", "BriefingSpec")
    tldr = _require_str(spec, "tldr", "BriefingSpec")
    sections_raw = spec.get("sections")
    if not sections_raw:
        raise ValueError("BriefingSpec: 'sections' is required and must be non-empty")
    return {
        "kind": "briefing",
        "headline": headline,
        "tldr": tldr,
        "sections": [validate_section(s) for s in sections_raw],
    }


def validate_error_spec(spec: dict) -> dict:
    if spec.get("kind") != "error":
        raise ValueError("ErrorSpec: 'kind' must be 'error'")
    reason = _require_str(spec, "reason", "ErrorSpec")
    out: dict = {"kind": "error", "reason": reason}
    clarify_ask = _optional_str(spec, "clarify_ask", "ErrorSpec")
    if clarify_ask is not None:
        out["clarify_ask"] = clarify_ask
    return out
