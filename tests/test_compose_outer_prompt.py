from utils.prompts import compose_outer_system_prompt, compose_run_sql_doc, load


def test_compose_outer_system_prompt_includes_outer_prompt():
    composed = compose_outer_system_prompt()
    outer = load("outer/system_prompt.md")
    assert outer.strip() in composed


def test_compose_outer_system_prompt_excludes_schema():
    # Clients truncate MCP server instructions; the schema rides in the
    # run_sql tool description instead, where it demonstrably arrives.
    composed = compose_outer_system_prompt()
    assert "## public.wells" not in composed
    assert "## Database schema" not in composed


def test_compose_run_sql_doc_includes_tool_doc_then_schema():
    doc = compose_run_sql_doc()
    tool = load("outer/tool_run_sql.md")
    schema = load("outer/shared_schema.md")
    assert tool.strip() in doc
    assert schema.strip() in doc
    # usage guidance first, schema reference appended
    assert doc.index(tool.strip()) < doc.index(schema.strip())


def test_outer_prompt_has_no_briefing_vocabulary():
    p = compose_outer_system_prompt()
    assert "## Widget palette" not in p
    assert "run_data_analysis" not in p
    assert "run_valuation" in p          # valuation flow still framed
