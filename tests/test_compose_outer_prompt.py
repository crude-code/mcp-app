from utils.prompts import compose_outer_system_prompt, load


def test_compose_outer_system_prompt_includes_outer_prompt_and_schema():
    composed = compose_outer_system_prompt()
    outer = load("outer/system_prompt.md")
    schema = load("inner/shared_schema.md")
    assert outer.strip() in composed
    assert schema.strip() in composed
    # outer comes first, schema appended
    assert composed.index(outer.strip()) < composed.index(schema.strip())


def test_compose_outer_system_prompt_has_schema_section_header():
    composed = compose_outer_system_prompt()
    assert "## Database schema" in composed


def test_outer_prompt_includes_palette_and_no_inner_agent():
    from utils.prompts import compose_outer_system_prompt
    p = compose_outer_system_prompt()
    assert "## Widget palette" in p
    assert "run_data_analysis" in p          # new authoring tool framed
    assert "delegate" not in p.lower() or "data_analyst" not in p  # no inner-agent delegation
