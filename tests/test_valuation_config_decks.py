from server.valuation import config


def test_deck_labels_strip_mode():
    labels, base = config.deck_labels("strip")
    assert labels == ["Strip", "$70", "$75", "$80"]
    assert base == "Strip"


def test_deck_labels_flat_mode():
    labels, base = config.deck_labels("flat")
    assert labels == ["Flat", "$70", "$75", "$80"]
    assert base == "Flat"


def test_default_deck_label_is_base():
    assert config.default_deck_label("strip") == "Strip"
    assert config.default_deck_label("flat") == "Flat"


def test_base_deck_is_first_then_flat_reference_decks():
    labels, base = config.deck_labels("strip")
    assert labels[0] == base                      # base (strip) leads
    assert labels[1:] == ["$70", "$75", "$80"]    # then the flat reference decks
    assert config.ECON.deck_oil_flat == (70.0, 75.0, 80.0)
