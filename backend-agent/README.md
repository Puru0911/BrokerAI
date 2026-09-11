# BrokerAI agent backend

This is the agentic BrokerAI backend. It is a new service, not a patch on `backend/`.

The broker is one LangChain tool-calling agent with RAG. There is no graph router and no intake / matching / mediation pipeline. The same agent talks to every party. A match notebook (shared facts + outstanding question) is visible on both turns. `think` is a custom tool, not provider-native thinking. `update_request` patches a brief without rewriting it.

## Run

```bash
cd backend-agent
cp .env.example .env
# LLM keys can also be picked up from ../backend/.env
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

Point the frontend at this process with `NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:8000`.

Chat routes match the existing frontend:

- `POST /broker/sessions`
- `POST /broker/sessions/{id}/messages`
- `POST /broker/matches/{id}/connect` — creates a direct chat (no phone number on the card)
- `GET /broker/connections` — all 1:1 chats for the current user
- `WS /broker/ws` — live messages (query `access_token`)
- `POST /broker/push/subscribe` — Web Push

Auth and user profiles are unchanged. Contact cards share name, email, and location only. After Connect, parties chat in-app over WebSockets (not Supabase Realtime).

## Data

Broker tables are new (`agent_sessions`, `agent_messages`, `agent_requests`, `agent_matches`, `agent_events`, `agent_connections`, `agent_connection_messages`, `agent_connection_attachments`, `agent_connection_reads`, `agent_push_subscriptions`, `agent_attachments`, `agent_attachment_requests`, `agent_attachment_grants`, `agent_attachment_shares`) so this service can share the same Postgres database as `backend/` without colliding. `user_profiles` is shared.

Session files go to a private Supabase Storage bucket (`broker-attachments`). Set `SUPABASE_SERVICE_ROLE_KEY`. The agent classifies uploads from conversation as `public` (shareable) or `personal` (needs permission).

Chroma lives in `backend-agent/data/chroma` with collection `agent_requests`.

Debug logs go to `logs/brokerai.log` (rotating file + console). Set `LOG_LEVEL` / `LOG_FILE` in `.env`.

## Statuses

Kept short on purpose:

- Request: `open` | `paused` | `closed`
- Match: `open` | `accepted` | `connected` | `closed`
- Session: `open` | `closed`

A request may wait on one match via `waiting_match_id`. That is attention, not a router. Every user message still goes to the same agent. Match terms live on `agent_matches.notebook`, not in event `message_text`.

## Tests

```bash
cd backend-agent
uv run pytest
uv run ruff check .
```
