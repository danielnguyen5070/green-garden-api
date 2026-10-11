"""Unit tests for DeepSeek tool-call markup detection, parsing, and stream guarding."""

from __future__ import annotations

import json

import pytest

from app.features.chat.dsml import (
    DsmlStreamGuard,
    contains_tool_markup,
    parse_dsml_tool_calls,
    strip_tool_markup,
)

# Exact payload reported leaking to users.
REPORTED_LEAK = (
    "<｜｜DSML｜｜ calls> <｜｜DSML｜｜ invoke name=\"search_shop_faq\"> "
    "<｜｜DSML｜｜ parameter name=\"locale\" string=\"true\">vi</｜｜DSML｜｜ parameter> "
    "<｜｜DSML｜｜ parameter name=\"query\" string=\"true\">thanh toán COD trả tiền mặt "
    "khi nhận hàng chuyển khoản</｜｜DSML｜｜ parameter> </｜｜DSML｜｜ invoke> "
    "</｜｜DSML｜｜ calls>"
)

CANONICAL_DSML = (
    "<｜DSML｜function_calls>\n"
    "<｜DSML｜invoke name=\"get_plant_price\">\n"
    "<｜DSML｜parameter name=\"plant_query\" string=\"true\">Cây Chùm Ngây</｜DSML｜parameter>\n"
    "</｜DSML｜invoke>\n"
    "<｜DSML｜invoke name=\"check_stock\">\n"
    "<｜DSML｜parameter name=\"plant_query\" string=\"true\">moringa-tree</｜DSML｜parameter>\n"
    "<｜DSML｜parameter name=\"limit\" string=\"false\">3</｜DSML｜parameter>\n"
    "</｜DSML｜invoke>\n"
    "</｜DSML｜function_calls>"
)


def test_parse_reported_leak() -> None:
    calls = parse_dsml_tool_calls(REPORTED_LEAK)
    assert len(calls) == 1
    assert calls[0].name == "search_shop_faq"
    assert json.loads(calls[0].arguments) == {
        "locale": "vi",
        "query": "thanh toán COD trả tiền mặt khi nhận hàng chuyển khoản",
    }
    assert calls[0].id


def test_parse_canonical_multiple_invokes_and_typed_params() -> None:
    calls = parse_dsml_tool_calls(CANONICAL_DSML)
    assert [c.name for c in calls] == ["get_plant_price", "check_stock"]
    assert json.loads(calls[0].arguments) == {"plant_query": "Cây Chùm Ngây"}
    assert json.loads(calls[1].arguments) == {"plant_query": "moringa-tree", "limit": 3}
    assert calls[0].id != calls[1].id


def test_parse_legacy_tool_call_format() -> None:
    text = (
        "<｜tool▁calls▁begin｜><｜tool▁call▁begin｜>function<｜tool▁sep｜>search_shop_faq\n"
        "```json\n{\"query\": \"phí ship\", \"locale\": \"vi\"}\n```<｜tool▁call▁end｜>"
        "<｜tool▁calls▁end｜>"
    )
    calls = parse_dsml_tool_calls(text)
    assert len(calls) == 1
    assert calls[0].name == "search_shop_faq"
    assert json.loads(calls[0].arguments) == {"query": "phí ship", "locale": "vi"}


def test_parse_plain_text_returns_nothing() -> None:
    assert parse_dsml_tool_calls("Shop giao hàng toàn quốc.") == []
    assert parse_dsml_tool_calls("") == []
    assert parse_dsml_tool_calls(None) == []


def test_strip_and_contains_tool_markup() -> None:
    assert contains_tool_markup(REPORTED_LEAK)
    assert contains_tool_markup(CANONICAL_DSML)
    assert not contains_tool_markup("Giá < 200.000đ, ship <3 ngày")
    assert strip_tool_markup("Dạ, để mình kiểm tra. " + REPORTED_LEAK) == (
        "Dạ, để mình kiểm tra. "
    )
    assert strip_tool_markup("Không có markup") == "Không có markup"
    assert strip_tool_markup(None) == ""


def _run_guard(chunks: list[str]) -> tuple[str, DsmlStreamGuard]:
    guard = DsmlStreamGuard()
    out = "".join(guard.feed(c) for c in chunks) + guard.finish()
    return out, guard


@pytest.mark.parametrize("split_at", range(1, 20))
def test_guard_catches_marker_split_at_any_boundary(split_at: int) -> None:
    text = "Dạ bạn. " + CANONICAL_DSML
    prefix_len = len("Dạ bạn. ")
    cut = prefix_len + split_at
    out, guard = _run_guard([text[:cut], text[cut:]])
    assert out == "Dạ bạn. "
    assert "DSML" not in out and "｜" not in out
    assert parse_dsml_tool_calls(guard.captured)


def test_guard_char_by_char_reported_leak() -> None:
    out, guard = _run_guard(list(REPORTED_LEAK))
    assert out == ""
    assert parse_dsml_tool_calls(guard.captured)[0].name == "search_shop_faq"


def test_guard_passes_plain_text_with_harmless_angle_brackets() -> None:
    chunks = ["Giá ", "<", "200k", " và ship ", "<", "3 ngày. a <", "b"]
    out, guard = _run_guard(chunks)
    assert out == "".join(chunks)
    assert guard.captured == ""


def test_guard_releases_trailing_angle_bracket_on_finish() -> None:
    out, guard = _run_guard(["Nhỏ hơn <"])
    assert out == "Nhỏ hơn <"
    assert guard.captured == ""
