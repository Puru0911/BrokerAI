# BrokerAI agent backend

This is the agentic BrokerAI backend. It is a new service, not a patch on `backend/`.

The broker is one LangChain tool-calling agent with RAG. There is no graph router and no intake / matching / mediation pipeline. The same agent talks to every party. A match notebook (pair process + pair-only concessions) is visible on both turns. `think` is a custom tool, not provider-native thinking. `update_search_brief` patches the searchable core; `update_request_details` stores extras for evaluate and mediation without re-indexing.

## Run

```bash
cd backend-agent
cp .env.example .env
# LLM keys can also be picked up from ../backend/.env
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

Set `SUPABASE_JWT_SECRET` from Supabase **Project Settings → API → JWT Secret** if you sign in with Google or magic link. `dev:` tokens only work when `ENV=local`. Production also needs `INTERNAL_JOB_SECRET` and `uv run alembic upgrade head` (the process will not start if the schema is behind). `AGENT_NAME` (default `BrokerAI`) is the name in the empty-session welcome: `Hi! I'm {AGENT_NAME}. Tell me what you're looking for and I'll find you the right people`. Match it on the frontend with `NEXT_PUBLIC_AGENT_NAME`.

Point the frontend at this process with `NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:8000`.

Chat routes match the existing frontend:

- `POST /broker/sessions`
- `POST /broker/sessions/{id}/messages` — optional `match_id` for a match lane; omit for the request/brief lane
- `GET /broker/sessions` / `GET /broker/sessions/{id}` — include `matches[]` (label, unread, waiting, connect offer, connection id)
- `POST /broker/matches/{id}/read` — clear a match-lane unread badge
- `POST /broker/matches/{id}/connect` — creates a direct chat (no phone number on the card)
- `GET /broker/connections` — all 1:1 chats for the current user
- `WS /broker/ws` — live messages (query `access_token`)
- `POST /broker/push/subscribe` — Web Push
- `PATCH /users/me` — `{ "notify_email": true|false }`
- `GET /mail/unsubscribe?token=` — activity-email opt-out (HMAC token, no login)
- `POST /internal/process-stale` — expire timed-out matches (`X-Job-Secret`)
- `GET /health` — liveness; `GET /health/ready` — Postgres + auth config

Auth and user profiles are unchanged. Contact cards share name, email, and location only. After Connect, parties chat in-app over WebSockets (not Supabase Realtime).

When a user does not have `/broker/ws` open, the agent emails them (Resend) for match outreach, a leftover introduction offer, or delivered contact cards. Set `RESEND_API_KEY` and a verified `MAIL_FROM`. Local skips sending if those are empty. 1:1 connection threads still use Web Push. Presence is in-process, same as the WebSocket hub (one worker).

## Data

Broker tables are new (`agent_sessions`, `agent_messages`, `agent_requests`, `agent_matches`, `agent_match_reads`, `agent_events`, `agent_connections`, `agent_connection_messages`, `agent_connection_attachments`, `agent_connection_reads`, `agent_push_subscriptions`, `agent_mail_log`, `agent_attachments`, `agent_attachment_requests`, `agent_attachment_grants`, `agent_attachment_shares`) so this service can share the same Postgres database as `backend/` without colliding. `user_profiles` is shared (`notify_email` defaults true).

Session files go to a private Supabase Storage bucket (`broker-attachments`). Set `SUPABASE_SERVICE_ROLE_KEY`. The agent classifies uploads from conversation as `public` (shareable) or `personal` (needs permission).

Chroma lives in `backend-agent/data/chroma` with collection `agent_requests`.

Debug logs go to `logs/brokerai-YYYY-MM-DD.log` (one file per day, plus console). Set `LOG_LEVEL` / `LOG_FILE` in `.env`. Model reasoning is logged as `model thinking` on each broker step.

## Statuses

Kept short on purpose:

- Request: `open` | `paused` | `closed`
- Match: `open` | `accepted` | `connected` | `closed`
- Session: `open` | `closed`

A request may present up to `MAX_PAIR_PER_REQUEST` screened candidates (default 3) as Interested/Skip cards on Your request. A match lane exists only after Interested. Open matches are uncapped. `agent_messages.match_id` is the lane: null is the brief/request chat, set is that pair. `waiting_match_id` is attention, not a router. POST `/sessions/{id}/messages` may include `match_id`. Every user message still goes to the same agent with a focused context packet. Match terms live on `agent_matches.notebook`, not in event `message_text`.

## Tests

```bash
cd backend-agent
uv run pytest
uv run ruff check .
```
