from whippletree import pricing


def test_local_models_are_free():
    assert pricing.estimate("ollama:llama3.1:8b", 1000, 1000) == 0.0


def test_unknown_model_is_none():
    assert pricing.estimate("openrouter:some/model", 1000, 1000) is None


def test_table_entry_is_used(monkeypatch):
    monkeypatch.setitem(pricing.PRICES, "openrouter:x/y", (2.0, 10.0))
    assert pricing.estimate("openrouter:x/y", 1_000_000, 100_000) == 3.0
