from app.agents.prompts import (
    BROKER_SYSTEM_PROMPT,
    BROKER_SYSTEM_PROMPT_DEV,
    BROKER_SYSTEM_PROMPT_FULL,
    use_small_prompts,
    MATCH_CONTEXT_INSTRUCTION,
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
    TOOL_OFFER_INTRODUCTION_FULL,
    TOOL_OPEN_MATCH_FULL,
    TOOL_REQUEST_ATTACHMENT_FULL,
    TOOL_SAVE_REQUEST_FULL,
    TOOL_SEARCH_COUNTERPARTIES_FULL,
    TOOL_SHARE_ATTACHMENT_FULL,
    TOOL_SHARE_CONTACTS_FULL,
    TOOL_SKIP_MATCH_FULL,
    TOOL_THINK_FULL,
    TOOL_UPDATE_NOTEBOOK_FULL,
    TOOL_UPDATE_REQUEST_FULL,
    USER_MESSAGE_INSTRUCTION,
)

_SECTION_HEADERS = (
    "== THIS CONVERSATION ==",
    "== EACH TURN ==",
    "== YOUR TOOLS ==",
    "== HOW YOU WORK ==",
    "== HOW YOU SPEAK ==",
    "== LIMITS ==",
)

_ALL_TOOLS = (
    "think",
    "save_request",
    "update_request",
    "index_request",
    "get_request_snapshot",
    "search_counterparties",
    "search_again",
    "evaluate_pair",
    "open_match",
    "message_party",
    "update_notebook",
    "skip_match",
    "reject_match",
    "accept_match",
    "offer_introduction",
    "get_match_events",
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


def _tools_section(prompt: str) -> str:
    return prompt.split("== YOUR TOOLS ==")[1].split("==")[0]


def _assert_system_prompt(prompt: str) -> None:
    lowered = prompt.lower()
    assert "you are broker" in lowered
    assert "session_role" in lowered
    assert "living_request" in lowered
    assert "notebook" in lowered
    assert "message_party" in lowered
    assert "nobody suitable is listed" in lowered or "nobody suitable" in lowered
    assert "not an advocate" not in lowered
    assert "langgraph" not in lowered
    for header in _SECTION_HEADERS:
        assert header in prompt
    for tool in _ALL_TOOLS:
        assert f"- {tool} —" in _tools_section(prompt)


def test_broker_prompt_states_purpose_and_capabilities() -> None:
    _assert_system_prompt(BROKER_SYSTEM_PROMPT_FULL)
    lowered = BROKER_SYSTEM_PROMPT_FULL.lower()
    assert "this chat is private" in lowered
    assert "outreach_context" in lowered
    assert "new_uploads" in lowered
    assert "your_role" in lowered
    assert "never speak in first person" in lowered
    assert "tool names" in lowered
    assert "one question" in lowered
    assert "connecting people" in lowered
    assert "optional, not mandatory" in lowered
    assert "request_attachment" in lowered
    assert "== FILES ==" not in BROKER_SYSTEM_PROMPT_FULL
    assert "== CONNECTING PEOPLE ==" not in BROKER_SYSTEM_PROMPT_FULL
    assert "== HOW TO DECIDE, EVERY TURN ==" not in BROKER_SYSTEM_PROMPT_FULL


def test_small_system_prompt_covers_the_same_contract() -> None:
    _assert_system_prompt(BROKER_SYSTEM_PROMPT_DEV)
    assert len(BROKER_SYSTEM_PROMPT_DEV) < len(BROKER_SYSTEM_PROMPT_FULL)
    assert BROKER_SYSTEM_PROMPT == BROKER_SYSTEM_PROMPT_FULL


def test_prompt_size_setting_selects_small_or_full() -> None:
    from app.core.config import Settings, settings

    assert Settings(AGENT_PROMPT_SIZE="compressed").AGENT_PROMPT_SIZE == "small"
    assert Settings(AGENT_PROMPT_SIZE="SMALL").AGENT_PROMPT_SIZE == "small"
    assert Settings(AGENT_PROMPT_SIZE="full").AGENT_PROMPT_SIZE == "full"
    assert Settings(AGENT_PROMPT_SIZE="nope").AGENT_PROMPT_SIZE == "full"
    assert settings.AGENT_PROMPT_SIZE in {"full", "small"}
    assert use_small_prompts() is (settings.AGENT_PROMPT_SIZE == "small")


def test_tools_section_gives_each_tool_one_line() -> None:
    section = _tools_section(BROKER_SYSTEM_PROMPT_FULL)
    lines = [line for line in section.splitlines() if line.startswith("- ")]
    assert [line.split(" —", 1)[0][2:] for line in lines] == list(_ALL_TOOLS)
    lengths = [len(line) for line in lines]
    assert max(lengths) - min(lengths) < 120


def test_reply_rules_forbid_tool_leak_and_extra_questions() -> None:
    speak = BROKER_SYSTEM_PROMPT_FULL.split("== HOW YOU SPEAK ==")[1].split("==")[0].lower()
    assert "tool names" in speak
    assert "verdicts" in speak
    assert "recap their brief" in speak
    work = BROKER_SYSTEM_PROMPT_FULL.split("== HOW YOU WORK ==")[1].split("==")[0].lower()
    assert "optional, not mandatory" in work
    assert "never treat a skipped question as a stop" in work
    assert "request_attachment" in work
    assert "toward a connection" in work


def test_tools_describe_effects_not_sequences() -> None:
    assert "complete living brief" in TOOL_SAVE_REQUEST_FULL.lower()
    assert "omitted" in TOOL_UPDATE_REQUEST_FULL.lower()
    assert "private working note" in TOOL_THINK_FULL.lower()
    assert "broker only" in TOOL_UPDATE_NOTEBOOK_FULL.lower() or "humans never see" in TOOL_UPDATE_NOTEBOOK_FULL.lower()
    assert "search index" in TOOL_INDEX_REQUEST_FULL.lower()
    assert "anonymized" in TOOL_SEARCH_COUNTERPARTIES_FULL.lower()
    assert "candidate_id" in TOOL_EVALUATE_PAIR_FULL
    assert "recommended_action" in TOOL_EVALUATE_PAIR_FULL.lower()
    assert "other person's chat stays unchanged" in TOOL_OPEN_MATCH_FULL.lower()
    assert "other person's private chat" in TOOL_MESSAGE_PARTY_FULL.lower()
    assert "does not take a party name" in TOOL_MESSAGE_PARTY_FULL.lower()
    assert "acknowledgement" in TOOL_MESSAGE_PARTY_FULL.lower()
    assert " to is " not in TOOL_MESSAGE_PARTY_FULL.lower()
    assert "closes" in TOOL_SKIP_MATCH_FULL.lower()
    assert "go-ahead" in TOOL_ACCEPT_MATCH_FULL.lower()
    assert "this person's go-ahead" in TOOL_ACCEPT_MATCH_FULL.lower()
    assert "contact cards" in TOOL_ACCEPT_MATCH_FULL.lower()
    assert "introduction control" in TOOL_OFFER_INTRODUCTION_FULL.lower()
    assert "both sides" in TOOL_SHARE_CONTACTS_FULL.lower()
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
            TOOL_OFFER_INTRODUCTION_FULL,
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


def test_user_message_instruction_is_a_reply_brief() -> None:
    lowered = USER_MESSAGE_INSTRUCTION.lower()
    assert "ordinary language" in lowered
    assert "tool" in lowered
    assert "classify" not in lowered
    assert "accept_match" not in lowered


def test_trigger_instructions_state_the_situation() -> None:
    assert "no new user message" in REQUEST_READY_INSTRUCTION.lower() or (
        "no new user text" in REQUEST_READY_INSTRUCTION.lower()
    )
    assert "evaluate_pair" not in REQUEST_READY_INSTRUCTION
    assert "follow recommended" not in REQUEST_READY_INSTRUCTION.lower()
    assert "gone quiet" in MATCH_TIMEOUT_INSTRUCTION.lower()
    assert "skip" not in MATCH_TIMEOUT_INSTRUCTION.lower()
    assert "search again" not in MATCH_TIMEOUT_INSTRUCTION.lower()
    assert "outreach_context" in MATCH_CONTEXT_INSTRUCTION.lower()
    assert "this person" in MATCH_CONTEXT_INSTRUCTION.lower()
    assert "message_party" in MATCH_CONTEXT_INSTRUCTION.lower()


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
