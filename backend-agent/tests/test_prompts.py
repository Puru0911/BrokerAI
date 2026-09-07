from app.agents.prompts import (
    BROKER_SYSTEM_PROMPT,
    BROKER_SYSTEM_PROMPT_DEV,
    BROKER_SYSTEM_PROMPT_FULL,
    NATURAL_FALLBACK_REPLY,
    PAIR_EVALUATOR_PROMPT,
    PAIR_EVALUATOR_PROMPT_DEV,
    PAIR_EVALUATOR_PROMPT_FULL,
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
    use_dev_prompts,
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


def test_broker_prompt_matches_agentic_spec() -> None:
    prompt = BROKER_SYSTEM_PROMPT_FULL
    assert "You are Broker, an AI matchmaking agent" in prompt
    assert "SESSION_ROLE" in prompt
    assert "living_request" in prompt
    assert "index_request" in prompt
    assert "skip_match" in prompt
    assert "Never put in a reply" in prompt
    assert "langgraph" not in prompt.lower()
    assert "notebook" in prompt
    assert "broker for every party" in prompt.lower()
    assert "to is \"source\" or \"candidate\"" in prompt
    assert "final reply" in prompt
    assert "keep working with what they gave" in prompt
    assert "humans never see it" in prompt.lower() or "humans do not see it" in prompt.lower()
    for tool in _REQUIRED_TOOLS:
        assert tool in prompt
    assert "new_uploads" in prompt
    assert "pending is a last resort" in prompt.lower() or "Pending is a last resort" in prompt


def test_dev_prompt_covers_same_operations_with_fewer_tokens() -> None:
    prompt = BROKER_SYSTEM_PROMPT_DEV
    assert len(prompt) < 0.6 * len(BROKER_SYSTEM_PROMPT_FULL)
    assert "You are Broker" in prompt
    assert "SESSION_ROLE" in prompt
    assert "living_request" in prompt
    assert "notebook" in prompt
    assert "final reply" in prompt
    assert "keep working with what they gave" in prompt
    assert "update_notebook" in prompt
    assert "new_uploads" in prompt
    assert "pending is a last resort" in prompt.lower()
    assert "to=source|candidate" in prompt or "to is source or candidate" in prompt
    assert "langgraph" not in prompt.lower()
    for tool in _REQUIRED_TOOLS:
        assert tool in prompt
    if use_dev_prompts():
        assert BROKER_SYSTEM_PROMPT == BROKER_SYSTEM_PROMPT_DEV


def test_tools_match_spec_names() -> None:
    assert "FULL" in TOOL_SAVE_REQUEST_FULL or "complete" in TOOL_SAVE_REQUEST_FULL.lower()
    assert "omitted" in TOOL_UPDATE_REQUEST_FULL.lower()
    assert "provider thinking" in TOOL_THINK_FULL.lower()
    assert "humans do not see" in TOOL_UPDATE_NOTEBOOK_FULL.lower()
    assert "no further questions" in TOOL_INDEX_REQUEST_FULL.lower()
    assert "waiting on an answer" in TOOL_INDEX_REQUEST_FULL.lower()
    assert (
        "Does not notify" in TOOL_SEARCH_COUNTERPARTIES_FULL
        or "does not notify" in TOOL_SEARCH_COUNTERPARTIES_FULL.lower()
    )
    assert "candidate_id" in TOOL_EVALUATE_PAIR_FULL
    assert "recommended_action" in TOOL_EVALUATE_PAIR_FULL
    assert "message_party" in TOOL_OPEN_MATCH_FULL
    assert "recommended_action" in TOOL_OPEN_MATCH_FULL
    assert "source" in TOOL_MESSAGE_PARTY_FULL.lower()
    assert "candidate" in TOOL_MESSAGE_PARTY_FULL.lower()
    assert "natural conversation" in TOOL_MESSAGE_PARTY_FULL.lower()
    assert "drop" in TOOL_SKIP_MATCH_FULL.lower()
    assert "agreed" in TOOL_ACCEPT_MATCH_FULL.lower()
    assert "upload prompt" in TOOL_REQUEST_ATTACHMENT_FULL.lower()
    assert "conversation history" in TOOL_CLASSIFY_ATTACHMENT_FULL.lower()
    assert "personal" in TOOL_SHARE_ATTACHMENT_FULL.lower()


def test_fallback_reply_is_plain() -> None:
    assert NATURAL_FALLBACK_REPLY == "I'll look and update you."


def test_helper_prompts_use_spec_contracts() -> None:
    for index_prompt in (SEMANTIC_INDEX_PROMPT, SEMANTIC_INDEX_PROMPT_DEV):
        assert "LOOKING FOR:" in index_prompt
    for search_prompt in (SEMANTIC_SEARCH_PROMPT, SEMANTIC_SEARCH_PROMPT_DEV):
        assert "query_text" in search_prompt
        assert "semantic only" in search_prompt.lower()
    for eval_prompt in (PAIR_EVALUATOR_PROMPT, PAIR_EVALUATOR_PROMPT_DEV):
        assert "strong_match" in eval_prompt
        assert "recommended_action" in eval_prompt
        assert "complementary" in eval_prompt
        assert "ask_clarifying_question" in eval_prompt
        assert "next_questions" in eval_prompt
    assert len(SEMANTIC_INDEX_PROMPT_DEV) < len(SEMANTIC_INDEX_PROMPT_FULL)
    assert len(PAIR_EVALUATOR_PROMPT_DEV) < len(PAIR_EVALUATOR_PROMPT_FULL)
    assert len(SEMANTIC_SEARCH_PROMPT_DEV) < len(SEMANTIC_SEARCH_PROMPT_FULL)
