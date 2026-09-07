# Active backend (do not forget)

The product backend is **`backend-agent/`**. It is a LangChain tool-calling broker (`ChatOpenAI.bind_tools` loop). There is no graph router.

`backend/` is the earlier **LangGraph** prototype (intake graph, matching graph, mediation graph). Do not edit it. Do not use it as the source of truth for simulations, prompts, or product behavior unless the user explicitly names it.

When simulating or implementing broker behavior:

- Read `backend-agent/app/agents/prompts.py` and `backend-agent/app/agents/tools/`
- One agent, any tool, any turn, conversation-driven
- Shared match state is `open_matches[].notebook`
- Session chat is private per party

Until the user says otherwise, all agentic backend work goes in `backend-agent/` only. `frontend/` may be edited.
