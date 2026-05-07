"""Tests for el/nodes/error_formatter.py."""
from __future__ import annotations

from el.nodes import error_formatter as ef


def test_formats_full_error_dict():
    ctx = {
        "workflow_error": {
            "error": {
                "node": {"name": "browserbase_fetch"},
                "message": "Connection timeout",
            }
        }
    }
    ef.run(ctx)
    text = ctx["formatted_error"][0]["text"]
    assert "⚠️ *EL Node Failed*" in text
    assert "`browserbase_fetch`" in text
    assert "Connection timeout" in text
    assert "IST" in text


def test_handles_missing_node_name_fallback():
    ctx = {
        "workflow_error": {
            "error": {
                "message": "Generic error"
            }
        }
    }
    ef.run(ctx)
    text = ctx["formatted_error"][0]["text"]
    assert "Unknown Node" in text


def test_truncates_message():
    long_msg = "A" * 500
    ctx = {
        "workflow_error": {
            "error": {
                "node": {"name": "test_node"},
                "message": long_msg,
            }
        }
    }
    ef.run(ctx)
    text = ctx["formatted_error"][0]["text"]
    # Message should be truncated to 300 chars
    assert len(text) < len(long_msg)
    assert "A" * 250 in text


def test_includes_ist_timestamp():
    ctx = {
        "workflow_error": {
            "error": {
                "node": {"name": "test_node"},
                "message": "Test error",
            }
        }
    }
    ef.run(ctx)
    text = ctx["formatted_error"][0]["text"]
    assert "🕐 *Time (IST):*" in text
    # Should include year (2026) and IST timezone
    assert "2026" in text or "202" in text
    assert "IST" in text


def test_handles_empty_error():
    ctx = {"workflow_error": None}
    ef.run(ctx)
    assert len(ctx["formatted_error"]) == 0


def test_ist_timestamp_works_without_tzdata():
    """IST formatting must not depend on the IANA tz database.

    Regression: ZoneInfo("Asia/Kolkata") raises ZoneInfoNotFoundError on
    Windows when the `tzdata` package is missing. IST is a fixed offset
    (UTC+5:30, no DST), so we use a fixed-offset timezone instead.
    """
    ctx = {"workflow_error": {"error": {"node": {"name": "x"}, "message": "y"}}}
    ef.run(ctx)
    text = ctx["formatted_error"][0]["text"]
    assert "IST" in text
    # Format is "YYYY-MM-DD HH:MM:SS IST"
    import re as _re
    assert _re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} IST", text)


def test_handles_none_nested_fields():
    """A workflow_error with None where dicts are expected must not crash."""
    ctx = {
        "workflow_error": {
            "error": {"node": None, "context": None, "message": "boom"}
        }
    }
    ef.run(ctx)
    text = ctx["formatted_error"][0]["text"]
    assert "Unknown Node" in text
    assert "boom" in text


def test_handles_non_string_message():
    """Non-string error message (e.g. dict) must be coerced safely."""
    ctx = {"workflow_error": {"error": {"node": {"name": "n"}, "message": {"code": 500}}}}
    ef.run(ctx)
    text = ctx["formatted_error"][0]["text"]
    assert "n" in text
    assert "500" in text or "code" in text
