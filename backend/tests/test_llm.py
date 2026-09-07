from app.services.llm import extract_json_object


def test_extract_plain_json():
    parsed = extract_json_object('{"taxon": {"q": "jaguars"}, "place": {"q": "Costa Rica"}}')
    assert parsed is not None
    assert parsed["taxon"]["q"] == "jaguars"


def test_extract_fenced_and_think_blocks():
    text = """<think>planning</think>
```json
{"query": {"taxon": {"q": "amphibians", "rankHint": "class"}, "place": {"q": "Costa Rica"}}}
```
"""
    parsed = extract_json_object(text)
    assert parsed is not None
    assert parsed["taxon"]["q"] == "amphibians"
    assert parsed["place"]["q"] == "Costa Rica"


def test_extract_embedded_object():
    parsed = extract_json_object('Here you go: {"taxon": {"q": "Panthera onca"}} thanks')
    assert parsed is not None
    assert parsed["taxon"]["q"] == "Panthera onca"


def test_extract_rejects_empty():
    assert extract_json_object("") is None
    assert extract_json_object("no json here") is None
