import pytest

from server.extraction_transport import (
    PRODUCTION_HEADER, REVENUE_HEADER, TransportError,
    entity_counts, unpack_extraction,
)


_PROD_HEADER_LINE = ",".join(PRODUCTION_HEADER)
_SOURCES = {"1": ["Production/prod.xlsx", "sheet:Monthly;row:{n}"]}


def _prod_csv(*rows):
    return "\n".join([_PROD_HEADER_LINE, *rows]) + "\n"


def test_production_csv_round_trips_with_provenance():
    csv_text = _prod_csv("05-123-45678,2024-03-01,512,1490.2,88,,31,1,247,")
    out = unpack_extraction({}, production_csv=csv_text, sources=_SOURCES)
    (row,) = out["production_history"]
    assert row["well_api"] == "05-123-45678"
    assert row["month"] == "2024-03-01"
    assert row["oil_bbl"] == 512.0
    assert row["gas_mcf"] == 1490.2
    assert row["ngl_bbl"] is None
    assert row["days_on"] == 31.0
    assert row["provenance"] == {
        "source_file": "Production/prod.xlsx",
        "source_locator": "sheet:Monthly;row:247",
        "notes": None,
    }


def test_quoted_notes_survive():
    csv_text = _prod_csv('05-123-45678,2024-03-01,512,,,,31,1,247,"summed, per stub"')
    out = unpack_extraction({}, production_csv=csv_text, sources=_SOURCES)
    assert out["production_history"][0]["provenance"]["notes"] == "summed, per stub"


def test_blank_lines_skipped():
    csv_text = _prod_csv("05-123-45678,2024-03-01,512,,,,31,1,247,", "", "  ")
    out = unpack_extraction({}, production_csv=csv_text, sources=_SOURCES)
    assert len(out["production_history"]) == 1


def test_template_without_n_is_constant_locator():
    sources = {"1": ["Check Stubs/feb.pdf", "page:1"]}
    csv_text = _prod_csv("05-123-45678,2024-03-01,512,,,,31,1,,")
    out = unpack_extraction({}, production_csv=csv_text, sources=sources)
    assert out["production_history"][0]["provenance"]["source_locator"] == "page:1"


def test_no_template_means_null_locator():
    sources = {"1": ["Production/prod.xlsx"]}
    csv_text = _prod_csv("05-123-45678,2024-03-01,512,,,,31,1,,")
    out = unpack_extraction({}, production_csv=csv_text, sources=sources)
    assert out["production_history"][0]["provenance"]["source_locator"] is None


def test_wrong_header_rejected():
    with pytest.raises(TransportError, match="header line must be exactly"):
        unpack_extraction({}, production_csv="api,month\n1,2\n", sources=_SOURCES)


def test_field_count_mismatch_names_line():
    csv_text = _prod_csv("05-123-45678,2024-03-01,512")
    with pytest.raises(TransportError, match="line 2: expected 10 fields, got 3"):
        unpack_extraction({}, production_csv=csv_text, sources=_SOURCES)


def test_bad_number_names_line_and_column():
    csv_text = _prod_csv("05-123-45678,2024-03-01,512,abc,,,31,1,247,")
    with pytest.raises(TransportError, match="line 2: gas_mcf 'abc' is not a number"):
        unpack_extraction({}, production_csv=csv_text, sources=_SOURCES)


def test_unknown_src_rejected():
    csv_text = _prod_csv("05-123-45678,2024-03-01,512,,,,31,9,247,")
    with pytest.raises(TransportError, match="src '9' not in sources legend"):
        unpack_extraction({}, production_csv=csv_text, sources=_SOURCES)


def test_missing_src_rejected():
    csv_text = _prod_csv("05-123-45678,2024-03-01,512,,,,31,,247,")
    with pytest.raises(TransportError, match="src is required"):
        unpack_extraction({}, production_csv=csv_text, sources=_SOURCES)


def test_row_required_when_template_has_n():
    csv_text = _prod_csv("05-123-45678,2024-03-01,512,,,,31,1,,")
    with pytest.raises(TransportError, match="row is required"):
        unpack_extraction({}, production_csv=csv_text, sources=_SOURCES)


def test_csv_plus_json_array_is_ambiguous():
    csv_text = _prod_csv("05-123-45678,2024-03-01,512,,,,31,1,247,")
    with pytest.raises(TransportError, match="not both"):
        unpack_extraction({"production_history": [{"well_api": "x"}]},
                          production_csv=csv_text, sources=_SOURCES)


def test_bad_sources_shape_rejected():
    with pytest.raises(TransportError, match="non-empty source_file"):
        unpack_extraction({}, production_csv=_prod_csv(), sources={"1": []})
    with pytest.raises(TransportError, match="sources must be an object"):
        unpack_extraction({}, production_csv=_prod_csv(), sources=[1, 2])


def test_plain_json_path_is_untouched():
    ext = {"wells": [{"api": "x"}], "production_history": [{"well_api": "y"}]}
    assert unpack_extraction(ext) == ext


def test_revenue_header_is_the_contract():
    line = ",".join(REVENUE_HEADER)
    csv_text = line + "\n" + "05-1,,2025-10-01,2025-12-25,OIL,oil,3605,bbl,68.4,246582,11346,4190,231046,0.656,W,Falcon,1,1,\n"
    out = unpack_extraction({}, revenue_csv=csv_text,
                            sources={"1": ["Check Stubs/x.pdf", "page:{n}"]})
    (row,) = out["revenue_observations"]
    assert row["gross_revenue"] == 246582.0
    assert row["taxes"] == 11346.0
    assert row["deductions"] == 4190.0
    assert row["owner_decimal"] == 0.656
    assert row["provenance"]["source_locator"] == "page:1"


def test_entity_counts():
    ext = {"wells": [1, 2], "interests": [1], "revenue_observations": None}
    counts = entity_counts(ext)
    assert counts["wells"] == 2
    assert counts["interests"] == 1
    assert counts["revenue_observations"] == 0
    assert counts["documents"] == 0
