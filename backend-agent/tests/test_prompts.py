from app.agents.prompts import (
    BROKER_SYSTEM_PROMPT,
    MATCH_CONTEXT_INSTRUCTION,
    MATCH_TIMEOUT_INSTRUCTION,
    NATURAL_FALLBACK_REPLY,
    PAIR_EVALUATOR_PROMPT,
    REQUEST_READY_INSTRUCTION,
    SEMANTIC_INDEX_PROMPT,
    SEMANTIC_SEARCH_PROMPT,
    TOOL_ACCEPT_MATCH,
    TOOL_ANSWER_MATCH_QUESTION,
    TOOL_CLASSIFY_ATTACHMENT,
    TOOL_GET_MATCH_BRIEF,
    TOOL_GET_MATCH_EVENTS,
    TOOL_INDEX_REQUEST,
    TOOL_MESSAGE_PARTY,
    TOOL_OFFER_INTRODUCTION,
    TOOL_OPEN_MATCH,
    TOOL_PRESENT_CANDIDATES,
    TOOL_REQUEST_ATTACHMENT,
    TOOL_SAVE_REQUEST,
    TOOL_UPDATE_REQUEST_DETAILS,
    TOOL_UPDATE_SEARCH_BRIEF,
    TOOL_EVALUATE_PAIR,
    TOOL_SEARCH_COUNTERPARTIES,
    TOOL_SHARE_ATTACHMENT,
    TOOL_SHARE_CONTACTS,
    TOOL_SKIP_MATCH,
    TOOL_THINK,
    TOOL_UPDATE_NOTEBOOK,
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
    "update_search_brief",
    "update_request_details",
    "index_request",
    "get_request_snapshot",
    "search_counterparties",
    "evaluate_pair",
    "present_candidates",
    "open_match",
    "message_party",
    "update_notebook",
    "skip_match",
    "reject_match",
    "accept_match",
    "offer_introduction",
    "get_match_events",
    "get_match_brief",
    "answer_match_question",
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
    assert "broker" in lowered
    assert "session_role" not in lowered
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
    _assert_system_prompt(BROKER_SYSTEM_PROMPT)
    lowered = BROKER_SYSTEM_PROMPT.lower()
    assert "this chat is private" in lowered
    assert "outreach_context" in lowered
    assert "new_uploads" in lowered
    assert "your_role" in lowered
    assert "lane" in lowered
    assert "focus_match_id" in lowered
    assert "this turn is this lane only" in lowered
    assert "other_matches" not in lowered
    assert "never speak in first person" in lowered
    assert "tool names" in lowered
    assert "one question" not in lowered
    assert "connecting people" in lowered
    assert "optional, not mandatory" in lowered
    assert "answer this person's own request" in lowered
    assert "do not hint at the answer" in lowered
    assert "request_attachment" in lowered
    assert "== FILES ==" not in BROKER_SYSTEM_PROMPT
    assert "== CONNECTING PEOPLE ==" not in BROKER_SYSTEM_PROMPT
    assert "== HOW TO DECIDE, EVERY TURN ==" not in BROKER_SYSTEM_PROMPT
    assert "shared across every match" in lowered
    assert "update_search_brief" in lowered
    assert "update_request_details" in lowered
    assert "background_job" in lowered
    assert "get_match_brief" in lowered
    assert "view_filters" in lowered


def test_tools_section_gives_each_tool_one_line() -> None:
    section = _tools_section(BROKER_SYSTEM_PROMPT)
    lines = [line for line in section.splitlines() if line.startswith("- ")]
    assert [line.split(" —", 1)[0][2:] for line in lines] == list(_ALL_TOOLS)
    lengths = [len(line) for line in lines]
    assert max(lengths) - min(lengths) < 120


def test_reply_rules_forbid_tool_leak_and_extra_questions() -> None:
    speak = BROKER_SYSTEM_PROMPT.split("== HOW YOU SPEAK ==")[1].split("==")[0].lower()
    assert "tool names" in speak
    assert "verdicts" in speak
    assert "recap their brief" in speak
    assert "language this person last used" in speak
    assert "answer this person's own request" in speak
    assert "do not hint at the answer" in speak
    assert "one question" not in speak
    each = BROKER_SYSTEM_PROMPT.split("== EACH TURN ==")[1].split("==")[0].lower()
    assert "open_match_count" in each
    assert "this person's files" in each
    assert "caption" in each
    assert "description" in each
    assert "other_files" in each
    assert "shared_with_you" in each
    assert "pending_questions" in each
    assert "view_filters" in each
    assert "background_job" in each
    assert "retry_allowed" in each
    assert "could not be scored" in each
    work = BROKER_SYSTEM_PROMPT.split("== HOW YOU WORK ==")[1].split("==")[0].lower()
    assert "optional, not mandatory" in work
    assert "never treat a skipped question as a stop" in work
    assert "request_attachment" in work
    assert "toward a connection" in work
    assert "one question" not in work
    assert "present_candidates" in work
    assert "pending_questions" in work
    assert "together" in work
    assert "already shown" in work
    assert "at most one candidate" in work
    assert "retry_allowed is false" in work
    assert "do not start the same job this turn" in work
    assert "retry that job" not in work
    assert "several open matches" in work
    assert "in the background" in work
    assert "evaluate_pair filters" in work
    assert "does not change the brief" in work
    assert "indexed brief" in work
    assert "this person's skip" in work
    assert "pipeline" in work
    assert "update_search_brief" in work
    assert "update_request_details" in work
    assert "does not reindex" in work
    assert "evaluate_pair" in work
    assert "do not present pending_clarify" in work
    assert "do not message_party for a close fit until" in work
    limits = BROKER_SYSTEM_PROMPT.split("== LIMITS ==")[1].lower()
    assert "search_again" not in limits


def test_tools_describe_effects_not_sequences() -> None:
    assert "search brief" in TOOL_SAVE_REQUEST.lower()
    assert "omitted" in TOOL_UPDATE_SEARCH_BRIEF.lower()
    assert "does not reindex" in TOOL_UPDATE_REQUEST_DETAILS.lower()
    assert "does not change the search brief" in TOOL_UPDATE_REQUEST_DETAILS.lower()
    assert "private working note" in TOOL_THINK.lower()
    assert "broker only" in TOOL_UPDATE_NOTEBOOK.lower() or "humans never see" in TOOL_UPDATE_NOTEBOOK.lower()
    assert "pair-only" in TOOL_UPDATE_NOTEBOOK.lower()
    assert "search index" in TOOL_INDEX_REQUEST.lower() or "indexing" in TOOL_INDEX_REQUEST.lower()
    assert "background" in TOOL_SEARCH_COUNTERPARTIES.lower()
    assert "not candidate briefs" in TOOL_SEARCH_COUNTERPARTIES.lower()
    assert "saved brief" in TOOL_SEARCH_COUNTERPARTIES.lower()
    assert "view overlay" in TOOL_EVALUATE_PAIR.lower()
    assert "does not change the saved brief" in TOOL_EVALUATE_PAIR.lower()
    assert "interested/skip" in TOOL_PRESENT_CANDIDATES.lower()
    assert "together" in TOOL_PRESENT_CANDIDATES.lower()
    assert "strong fit" in TOOL_PRESENT_CANDIDATES.lower()
    assert "close fit" in TOOL_PRESENT_CANDIDATES.lower()
    assert "other person is not notified" in TOOL_PRESENT_CANDIDATES.lower()
    assert "stored or last-search" in TOOL_EVALUATE_PAIR.lower()
    assert "does not return counterpart briefs" in TOOL_EVALUATE_PAIR.lower()
    assert "other person's chat stays unchanged" in TOOL_OPEN_MATCH.lower()
    assert "marked interested" in TOOL_OPEN_MATCH.lower()
    assert "other person's private chat" in TOOL_MESSAGE_PARTY.lower()
    assert "does not take a party name" in TOOL_MESSAGE_PARTY.lower()
    assert "open match" in TOOL_MESSAGE_PARTY.lower()
    assert "request lane" not in TOOL_MESSAGE_PARTY.lower()
    assert "acknowledgement" in TOOL_MESSAGE_PARTY.lower()
    assert " to is " not in TOOL_MESSAGE_PARTY.lower()
    assert "closes" in TOOL_SKIP_MATCH.lower()
    assert "go-ahead" in TOOL_ACCEPT_MATCH.lower()
    assert "this person's go-ahead" in TOOL_ACCEPT_MATCH.lower()
    assert "contact cards" in TOOL_ACCEPT_MATCH.lower()
    assert "introduction control" in TOOL_OFFER_INTRODUCTION.lower()
    assert "both sides" in TOOL_SHARE_CONTACTS.lower()
    assert "does not show an upload card" in TOOL_REQUEST_ATTACHMENT.lower()
    assert "message box" in TOOL_REQUEST_ATTACHMENT.lower()
    assert "conversation" in TOOL_CLASSIFY_ATTACHMENT.lower()
    assert "file type" in TOOL_CLASSIFY_ATTACHMENT.lower()
    assert "description" in TOOL_CLASSIFY_ATTACHMENT.lower()
    assert "filename" not in TOOL_CLASSIFY_ATTACHMENT.lower()
    assert "personal" in TOOL_SHARE_ATTACHMENT.lower()
    assert "gallery" in TOOL_SHARE_ATTACHMENT.lower()
    assert "attachment_ids" in TOOL_SHARE_ATTACHMENT
    assert "other person's chat" in TOOL_SHARE_ATTACHMENT.lower()
    assert "does not return the other person's brief" in TOOL_GET_MATCH_EVENTS.lower()
    assert "complementary summary" in TOOL_GET_MATCH_BRIEF.lower()
    assert "not in the brief" in TOOL_ANSWER_MATCH_QUESTION.lower()

    tool_docs = "\n".join(
        [
            TOOL_THINK,
            TOOL_SAVE_REQUEST,
            TOOL_UPDATE_SEARCH_BRIEF,
            TOOL_UPDATE_REQUEST_DETAILS,
            TOOL_INDEX_REQUEST,
            TOOL_SEARCH_COUNTERPARTIES,
            TOOL_EVALUATE_PAIR,
            TOOL_PRESENT_CANDIDATES,
            TOOL_OPEN_MATCH,
            TOOL_MESSAGE_PARTY,
            TOOL_UPDATE_NOTEBOOK,
            TOOL_SKIP_MATCH,
            TOOL_ACCEPT_MATCH,
            TOOL_OFFER_INTRODUCTION,
            TOOL_REQUEST_ATTACHMENT,
            TOOL_CLASSIFY_ATTACHMENT,
            TOOL_SHARE_ATTACHMENT,
            TOOL_GET_MATCH_EVENTS,
            TOOL_GET_MATCH_BRIEF,
            TOOL_ANSWER_MATCH_QUESTION,
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
    assert "same language they used" in lowered
    assert "one question" not in lowered
    assert "update_request_details" in lowered
    assert "update_search_brief" in lowered
    assert "tool" in lowered
    assert "classify" not in lowered
    assert "accept_match" not in lowered


def test_trigger_instructions_state_the_situation() -> None:
    assert "no new user message" in REQUEST_READY_INSTRUCTION.lower() or (
        "no new user text" in REQUEST_READY_INSTRUCTION.lower()
    )
    assert "evaluate_pair" not in REQUEST_READY_INSTRUCTION
    assert "possible_match" in REQUEST_READY_INSTRUCTION
    assert "close fit" in REQUEST_READY_INSTRUCTION.lower()
    assert "follow recommended" not in REQUEST_READY_INSTRUCTION.lower()
    assert "background_job" in REQUEST_READY_INSTRUCTION.lower()
    assert "retry_allowed is false" in REQUEST_READY_INSTRUCTION.lower()
    assert "do not start the same job this turn" in REQUEST_READY_INSTRUCTION.lower()
    assert "retry that job" not in REQUEST_READY_INSTRUCTION.lower()
    assert "do not start another search this turn" in REQUEST_READY_INSTRUCTION.lower()
    assert "clarify" in REQUEST_READY_INSTRUCTION.lower()
    assert "gone quiet" in MATCH_TIMEOUT_INSTRUCTION.lower()
    assert "skip" not in MATCH_TIMEOUT_INSTRUCTION.lower()
    assert "search again" not in MATCH_TIMEOUT_INSTRUCTION.lower()
    assert "outreach_context" in MATCH_CONTEXT_INSTRUCTION.lower()
    assert "this person" in MATCH_CONTEXT_INSTRUCTION.lower()
    assert "message_party" in MATCH_CONTEXT_INSTRUCTION.lower()
    assert "do not open_match on this outreach turn" in MATCH_CONTEXT_INSTRUCTION.lower()


def test_fallback_reply_is_plain() -> None:
    assert NATURAL_FALLBACK_REPLY == "I'll look and update you."


def test_helper_prompts_use_spec_contracts() -> None:
    assert "LOOKING FOR:" in SEMANTIC_INDEX_PROMPT
    assert "query_text" in SEMANTIC_SEARCH_PROMPT
    assert "semantic" in SEMANTIC_SEARCH_PROMPT.lower()
    assert "strong_match" in PAIR_EVALUATOR_PROMPT
    assert "recommended_action" in PAIR_EVALUATOR_PROMPT
    assert "complementary" in PAIR_EVALUATOR_PROMPT
    assert "ask_clarifying_question" in PAIR_EVALUATOR_PROMPT
    assert "ask_other_person" in PAIR_EVALUATOR_PROMPT
    assert "do not open yet" in PAIR_EVALUATOR_PROMPT.lower()
    assert "next_questions" in PAIR_EVALUATOR_PROMPT
    assert "clarifying_questions" in PAIR_EVALUATOR_PROMPT
    assert "source_relative_brief" in PAIR_EVALUATOR_PROMPT
    assert "not a JSON Schema" in PAIR_EVALUATOR_PROMPT
    assert "view_filters" in PAIR_EVALUATOR_PROMPT
    assert "overlay" in PAIR_EVALUATOR_PROMPT.lower()
    assert "buy / rent" not in PAIR_EVALUATOR_PROMPT.lower()
    assert "housing vs hiring" not in PAIR_EVALUATOR_PROMPT.lower()
