from ankihelper import render
from ankihelper.agents import extract_json, prompt


def test_fenced_code_is_highlighted_with_inline_styles():
    html = render.to_html("Run:\n\n```ruby\ndef hi\n  puts 1\nend\n```")
    assert html.startswith("<p>Run:</p>")
    assert 'style="color: #66D9EF">def</span>' in html
    assert "class=\"highlight\"" in html


def test_unknown_language_falls_back_to_plain_code():
    html = render.to_html("```klingon\nqapla'\n```")
    assert "qapla&#x27;" in html or "qapla'" in html


def test_prose_is_escaped_and_supports_inline_code_bold_and_lists():
    html = render.to_html("Use `<%= x %>` for **output**\n\n- one\n- two")
    assert "<code>&lt;%= x %&gt;</code>" in html
    assert "<strong>output</strong>" in html
    assert "<ul><li>one</li><li>two</li></ul>" in html


def test_extract_json_handles_fences_and_surrounding_prose():
    assert extract_json('Sure!\n```json\n{"cards": []}\n```\nDone.') == {"cards": []}
    assert extract_json('noise {"a": {"b": 1}} trailing') == {"a": {"b": 1}}
    assert extract_json('Sure {see below}: {"cards": []}') == {"cards": []}


def test_fence_with_info_string_and_inner_backticks():
    html = render.to_html("```python title=x.py\nprint('```')\n```")
    assert "```python" not in html
    assert "print" in html and "highlight" in html


def test_prompt_values_are_not_substituted_twice():
    text = prompt("repair", card='{"question": "what does {error} mean"}', error="boom")
    assert "what does {error} mean" in text
