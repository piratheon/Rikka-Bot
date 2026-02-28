from src.utils.parse_keys import parse_keys


def test_parse_simple():
    text = 'openrouter:"sk-abc123" groq:gsk_456 google=AIzaXYZ'
    keys = parse_keys(text)
    assert keys["openrouter"] == "sk-abc123"
    assert keys["groq"] == "gsk_456"
    assert keys["google"] == "AIzaXYZ"


def test_parse_unquoted():
    text = "openrouter:sk-abc groq:gsk_1"
    keys = parse_keys(text)
    assert keys["openrouter"] == "sk-abc"
    assert keys["groq"] == "gsk_1"
