from app.agents.prompts import SEMANTIC_SEARCH_PROMPT


def test_semantic_search_prompt_is_semantic_only() -> None:
    assert "query_text" in SEMANTIC_SEARCH_PROMPT
    assert "metadata pre-filtering" not in SEMANTIC_SEARCH_PROMPT
    assert '"filters"' not in SEMANTIC_SEARCH_PROMPT
    assert "budget_min" not in SEMANTIC_SEARCH_PROMPT
