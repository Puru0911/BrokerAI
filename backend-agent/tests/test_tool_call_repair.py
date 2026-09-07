from langchain_core.messages import AIMessage

from app.agents.tool_call_repair import (
    coerce_str_list,
    failed_generation_from_error,
    parse_xml_tool_calls,
    repair_tool_message,
)

FAILED = """<tool_call>
<function=save_request>
<parameter=title>
Second-hand premium motorcycle dealer in Mumbai
</parameter>
<parameter=summary>
Mumbai-based business buying and selling second-hand premium motorcycles.
</parameter>
<parameter=objective>
Buy and sell second-hand premium motorcycles.
</parameter>
<parameter=constraints>
["Based in Mumbai"]
</parameter>
<parameter=preferences>
["Premium brands and models"]
</parameter>
<parameter=open_questions>
["Specific brands or models you focus on?", "Typical price range for transactions?", "Are you currently"""


def test_parse_qwen_xml_tool_call_including_truncated_tail() -> None:
    calls = parse_xml_tool_calls(FAILED)
    assert len(calls) == 1
    call = calls[0]
    assert call["name"] == "save_request"
    assert call["args"]["title"] == "Second-hand premium motorcycle dealer in Mumbai"
    assert call["args"]["constraints"] == ["Based in Mumbai"]
    assert call["args"]["preferences"] == ["Premium brands and models"]
    assert "open_questions" in call["args"]


def test_coerce_str_list_accepts_json_and_plain_text() -> None:
    assert coerce_str_list('["Based in Mumbai"]') == ["Based in Mumbai"]
    assert coerce_str_list("Mumbai\nPune") == ["Mumbai", "Pune"]
    assert coerce_str_list([" already "]) == ["already"]
    assert coerce_str_list(None) == []


class _FakeError(Exception):
    def __init__(self, body: dict) -> None:
        super().__init__("Error code: 400")
        self.body = body


def test_repair_tool_message_from_groq_body() -> None:
    exc = _FakeError(
        {
            "error": {
                "code": "tool_use_failed",
                "failed_generation": FAILED,
            }
        }
    )
    assert failed_generation_from_error(exc) == FAILED
    repaired = repair_tool_message(exc)
    assert isinstance(repaired, AIMessage)
    assert repaired.tool_calls[0]["name"] == "save_request"
