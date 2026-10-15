from app.agents.prompts import REQUEST_COPY_PROMPT, SEMANTIC_SEARCH_PROMPT


def test_semantic_search_prompt_is_semantic_only() -> None:
    assert "query_text" in SEMANTIC_SEARCH_PROMPT
    assert "metadata pre-filtering" not in SEMANTIC_SEARCH_PROMPT
    assert '"filters"' not in SEMANTIC_SEARCH_PROMPT
    assert "budget_min" not in SEMANTIC_SEARCH_PROMPT


def test_request_copy_prompt_asks_for_title_and_summary() -> None:
    lowered = REQUEST_COPY_PROMPT.lower()
    assert '"title"' in REQUEST_COPY_PROMPT
    assert '"summary"' in REQUEST_COPY_PROMPT
    assert "sidebar" in lowered
    assert "housing" not in lowered
    assert "dating" not in lowered
