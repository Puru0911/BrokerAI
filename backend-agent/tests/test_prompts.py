from app.agents.prompts import (
    BROKER_SYSTEM_PROMPT,
    BROKER_SYSTEM_PROMPT_DEV,
    BROKER_SYSTEM_PROMPT_FULL,
    MATCH_TIMEOUT_INSTRUCTION,
    NATURAL_FALLBACK_REPLY,
    PAIR_EVALUATOR_PROMPT,
    PAIR_EVALUATOR_PROMPT_DEV,
    PAIR_EVALUATOR_PROMPT_FULL,
    REQUEST_READY_INSTRUCTION,
    SEMANTIC_INDEX_PROMPT,
    SEMANTIC_INDEX_PROMPT_DEV,
    SEMANTIC_INDEX_PROMPT_FULL,
    SEMANTIC_SEARCH_PROMPT,
    SEMANTIC_SEARCH_PROMPT_DEV,
    SEMANTIC_SEARCH_PROMPT_FULL,
    TOOL_ACCEPT_MATCH_FULL,
    TOOL_CLASSIFY_ATTACHMENT_FULL,
    TOOL_EVALUATE_PAIR_FULL,
    TOOL_INDEX_REQUEST_FULL,
    TOOL_MESSAGE_PARTY_FULL,
    TOOL_OPEN_MATCH_FULL,
    TOOL_REQUEST_ATTACHMENT_FULL,
    TOOL_SAVE_REQUEST_FULL,
    TOOL_SEARCH_COUNTERPARTIES_FULL,
    TOOL_SHARE_ATTACHMENT_FULL,
    TOOL_SKIP_MATCH_FULL,
    TOOL_THINK_FULL,
    TOOL_UPDATE_NOTEBOOK_FULL,
    TOOL_UPDATE_REQUEST_FULL,
)

_SECTION_HEADERS = (
    "== WHO YOU ARE TALKING TO RIGHT NOW ==",
    "== WHAT YOU SEE EACH TURN ==",
    "== YOUR TOOLS ==",
    "== HOW TO DECIDE, EVERY TURN ==",
    "== USER-FACING REPLIES ==",
    "== HARD RULES ==",
    "== TONE ==",
)

_REQUIRED_TOOLS = (
    "think",
    "save_request",
    "update_request",
    "index_request",
    "search_counterparties",
    "evaluate_pair",
    "open_match",
    "message_party",
    "update_notebook",
    "skip_match",
    "accept_match",
    "share_contacts",
    "request_attachment",
    "classify_attachment",
    "share_attachment",
    "record_share_grant",
)

_PROCEDURE_MARKERS = (
    "how to decide",
    "call a tool when its condition applies",
    "follow recommended_action",
    "call index_request only",
    "on a live match, call first",
    "call only when",
    "use when",
    "then message_party",
    "right after accept_match",
    "never before",
)


def _assert_system_prompt(prompt: str) -> None:
    lowered = prompt.lower()
    assert "you are broker" in lowered
    assert "session_role" in lowered
    assert "living_request" in lowered
    assert "notebook" in lowered
    assert "message_party" in lowered
    assert "nobody suitable is listed" in lowered
    assert "not an advocate" not in lowered
    assert "langgraph" not in lowered
    for header in _SECTION_HEADERS:
        assert header in prompt
    for tool in _REQUIRED_TOOLS:
        assert tool in prompt


def test_broker_prompt_states_purpose_and_capabilities() -> None:
    _assert_system_prompt(BROKER_SYSTEM_PROMPT_FULL)
    lowered = BROKER_SYSTEM_PROMPT_FULL.lower()
    assert "user-facing replies" in lowered
    assert "tool findings" in lowered
    assert "files the other person already holds" in lowered
    assert "if they already have a public file" in lowered
    assert "context is why they should be reached" in lowered


def test_dev_system_prompt_matches_production() -> None:
    _assert_system_prompt(BROKER_SYSTEM_PROMPT_DEV)
    assert BROKER_SYSTEM_PROMPT_DEV == BROKER_SYSTEM_PROMPT_FULL
    assert BROKER_SYSTEM_PROMPT == BROKER_SYSTEM_PROMPT_FULL


def test_tools_describe_effects_not_sequences() -> None:
    assert "complete living brief" in TOOL_SAVE_REQUEST_FULL.lower()
    assert "omitted" in TOOL_UPDATE_REQUEST_FULL.lower()
    assert "private working note" in TOOL_THINK_FULL.lower()
    assert "broker only" in TOOL_UPDATE_NOTEBOOK_FULL.lower()
    assert "search index" in TOOL_INDEX_REQUEST_FULL.lower()
    assert "anonymized" in TOOL_SEARCH_COUNTERPARTIES_FULL.lower()
    assert "candidate_id" in TOOL_EVALUATE_PAIR_FULL
    assert "recommended_action" in TOOL_EVALUATE_PAIR_FULL.lower()
    assert "other party's chat stays unchanged" in TOOL_OPEN_MATCH_FULL.lower()
    assert "other party's private chat" in TOOL_MESSAGE_PARTY_FULL.lower()
    assert "does not take a party name" in TOOL_MESSAGE_PARTY_FULL.lower()
    assert "acknowledgement" in TOOL_MESSAGE_PARTY_FULL.lower()
    assert " to is " not in TOOL_MESSAGE_PARTY_FULL.lower()
    assert "closes" in TOOL_SKIP_MATCH_FULL.lower()
    assert "agreed" in TOOL_ACCEPT_MATCH_FULL.lower()
    assert "upload control" in TOOL_REQUEST_ATTACHMENT_FULL.lower()
    assert "conversation" in TOOL_CLASSIFY_ATTACHMENT_FULL.lower()
    assert "personal" in TOOL_SHARE_ATTACHMENT_FULL.lower()
    assert "gallery" in TOOL_SHARE_ATTACHMENT_FULL.lower()
    assert "attachment_ids" in TOOL_SHARE_ATTACHMENT_FULL

    tool_docs = "\n".join(
        [
            TOOL_THINK_FULL,
            TOOL_SAVE_REQUEST_FULL,
            TOOL_UPDATE_REQUEST_FULL,
            TOOL_INDEX_REQUEST_FULL,
            TOOL_SEARCH_COUNTERPARTIES_FULL,
            TOOL_EVALUATE_PAIR_FULL,
            TOOL_OPEN_MATCH_FULL,
            TOOL_MESSAGE_PARTY_FULL,
            TOOL_UPDATE_NOTEBOOK_FULL,
            TOOL_SKIP_MATCH_FULL,
            TOOL_ACCEPT_MATCH_FULL,
            TOOL_REQUEST_ATTACHMENT_FULL,
            TOOL_CLASSIFY_ATTACHMENT_FULL,
            TOOL_SHARE_ATTACHMENT_FULL,
        ]
    )
    lowered = tool_docs.lower()
    for marker in _PROCEDURE_MARKERS:
        assert marker not in lowered
    for blob in tool_docs.split("\n"):
        blob = blob.strip()
        if blob:
            assert blob[0].isupper()
    assert tool_docs.strip().endswith(".")


def test_trigger_instructions_state_the_situation() -> None:
    assert "no new user message" in REQUEST_READY_INSTRUCTION.lower() or (
        "no new user text" in REQUEST_READY_INSTRUCTION.lower()
    )
    assert "evaluate_pair" not in REQUEST_READY_INSTRUCTION
    assert "follow recommended" not in REQUEST_READY_INSTRUCTION.lower()
    assert "gone quiet" in MATCH_TIMEOUT_INSTRUCTION.lower()
    assert "skip" not in MATCH_TIMEOUT_INSTRUCTION.lower()
    assert "search again" not in MATCH_TIMEOUT_INSTRUCTION.lower()


def test_fallback_reply_is_plain() -> None:
    assert NATURAL_FALLBACK_REPLY == "I'll look and update you."


def test_helper_prompts_use_spec_contracts() -> None:
    for index_prompt in (SEMANTIC_INDEX_PROMPT, SEMANTIC_INDEX_PROMPT_DEV):
        assert "LOOKING FOR:" in index_prompt
    for search_prompt in (SEMANTIC_SEARCH_PROMPT, SEMANTIC_SEARCH_PROMPT_DEV):
        assert "query_text" in search_prompt
        assert "semantic" in search_prompt.lower()
    for eval_prompt in (PAIR_EVALUATOR_PROMPT, PAIR_EVALUATOR_PROMPT_DEV):
        assert "strong_match" in eval_prompt
        assert "recommended_action" in eval_prompt
        assert "complementary" in eval_prompt
        assert "ask_clarifying_question" in eval_prompt
        assert "next_questions" in eval_prompt
        assert "buy / rent" not in eval_prompt.lower()
        assert "housing vs hiring" not in eval_prompt.lower()
    assert len(SEMANTIC_INDEX_PROMPT_DEV) < len(SEMANTIC_INDEX_PROMPT_FULL)
    assert len(PAIR_EVALUATOR_PROMPT_DEV) < len(PAIR_EVALUATOR_PROMPT_FULL)
    assert len(SEMANTIC_SEARCH_PROMPT_DEV) < len(SEMANTIC_SEARCH_PROMPT_FULL)
