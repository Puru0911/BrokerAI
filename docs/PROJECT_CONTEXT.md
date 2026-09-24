# BrokerAI — Project Context

Last updated: 2026-09-14

## MVP Goal

Build a conversational AI broker that:

- Understands any request that needs a counterpart
- Saves a living brief, not a category form
- Finds compatible people with RAG
- Qualifies and mediates in private
- Shares contacts only after both sides accept

## Active worktree

Until the user says otherwise:

- Agentic backend work goes in **`backend-agent/`** only. Do not edit `backend/` (the old graph prototype).
- **`frontend/`** may be edited.
- Do not change other trees unless asked.

## How to apply a scenario report

A user scenario is an example of a product rule, not a patch target. Do not encode the example (domain, fields, wording) into code or prompts. Read it as a system-wide behavior, design the general rule for every use case, then apply the smallest general fix. Do not add special-case machinery for one conversation.

## Current architecture

The product backend is `backend-agent/`: one LangChain tool-calling agent, RAG over briefs, and Python tools for side effects. There is no graph router.

```
user message
  → FastAPI chat route
  → Broker Agent (ChatGroq / ChatOpenRouter / ChatOpenAI.bind_tools loop)
       think / save_request / update_request / search_counterparties /
       evaluate_pair / open_match / message_party / update_notebook /
       close_match / accept_match / share_contacts
  → Postgres + Chroma
  → reply to the current user (and optionally a named party via message_party)
```

One agent talks to every party. Session chat is private; `agent_matches.notebook` is shared agent memory (facts, outstanding, agent_note, next_action) and is **not** shown to humans. `think` is a this-turn plan only. Anything the next turn must remember goes in `update_notebook`. There is no automatic `request_ready` turn after a user message — if the brief should be matched now, the agent indexes and searches in the same turn. `message_party(to=source|candidate, context=intent)` queues a **separate** broker turn on the other party's session (`trigger=match_context`) after this request commits. It returns an ack only and does not wait for their reply. This session's bubble is the final reply. The other human's answer is a later `user_message` on their session. `update_request` patches the brief without a full rewrite. If a user skips follow-up questions or answers only some of them, the agent keeps working with what it has and may ask a skipped detail later only if a live match actually needs it.

`backend/` is the earlier graph prototype. It is not the active architecture.

**Grok / future sessions:** simulate and implement against `backend-agent/` only. `backend/` uses LangGraph graphs; `backend-agent/` uses LangChain tools and can call any tool on any turn from conversation.

## Backend (`backend-agent/`)

FastAPI app with the same chat contract the Next.js client already uses.

- `app/main.py` — app factory
- `app/api/routes/broker.py` — sessions, messages, attachments, matches, connect
- `app/api/routes/internal.py` — `POST /internal/process-stale` (job secret, not a user route)
- `app/api/routes/users.py` — `GET/POST /users/me`
- `app/agents/runtime.py` — tool-calling loop
- `app/agents/prompts.py` — broker persona as a capability map; tool effects live on bound schemas
- `app/agents/tools/` — request, search, match, and contact tools
- `app/rag/` — Chroma index + semantic profile/query helpers
- `app/services/orchestrator.py` — session create, message handle, stale matches
- `app/services/contact.py` — contact cards after accept

### Data

New tables so this service can share Postgres with the old folder without colliding:

- `agent_sessions`, `agent_messages`
- `agent_requests` — one living brief per session
- `agent_matches` — a pair of briefs plus `notebook` (shared facts and outstanding question)
- `agent_events` — append-only match audit
- `agent_connections` — created when a party presses Connect; opens a direct 1:1 chat
- `agent_connection_messages` / `agent_connection_attachments` — party-to-party chat and files
- `agent_connection_reads` — per-user last-read for unread counts
- `agent_push_subscriptions` — Web Push endpoints
- `agent_attachments` — files and links on a session (`kind` file|url, `share_class` pending|public|personal)
- `agent_attachment_requests` — agent asked this user to upload something
- `agent_attachment_grants` — permission to share a personal item on a match
- `agent_attachment_shares` — item delivered to the other party

Files live in a private Supabase Storage bucket (`broker-attachments`), path `{user_id}/{session_id}/{attachment_id}/filename`. The backend uses the service role and issues short-lived signed URLs after authz. Downloads always require a Bearer token; “public” means shareable with a match, not world-readable.

New items start `pending`. The agent classifies from conversation history, caption, and filename on the upload turn (`classify_attachment`). Classification labels the file; it does not rewrite the living brief and does not deliver the file into a match. `public` (resume, listing photos, portfolio) can be shared into an open match. `personal` needs a grant (Allow in UI or `record_share_grant` after the user agrees). Pending is a last resort if the agent cannot tell.

An open match snapshot includes `other_files`: public items the counterpart already holds (id, kind, purpose, label, whether already delivered) plus personal items as purpose-only. Bytes, URLs, and personal filenames stay off that list. `shared_with_you` is what has already been copied into this chat.

Classify only labels a file. It does not send it into a match. When this person asks for a file: if the other side already has a public one, `share_attachment` delivers it here; if they do not, `message_party` asks them. When they later share from their chat, that existing share path delivers it to this side. Personal files still need the owner’s agreement. `share_attachment` delivers to the non-owner.

`user_profiles` is shared with the original backend.

Statuses are intentionally short:

- Request: `open` | `paused` | `closed`
- Match: `open` | `accepted` | `connected` | `closed` (`close_reason` is `skip`, `reject`, `withdraw`, `expired`, or `request_closed`)
- Session: `open` | `closed`

`skip_match` / `reject_match` may close an `accepted` or `connected` match (status becomes `closed`). `message_party` writes into the named party's chat (`source` or `candidate`); questions for the current user belong in the final reply.

`waiting_match_id` on a request is attention (“we last asked this person about this match”). It does not route the next message to a different engine.

### Agent tools

Bound schemas describe what each tool does. The broker chooses among them.

- `think` — private working note for this turn
- `save_request` — full create/rewrite of the brief
- `update_request` — patch only changed fields
- `index_request` — make the brief searchable
- `search_counterparties` / `search_again` — anonymized RAG candidates
- `evaluate_pair` — screens one retrieved pair; recommendation is information for the broker
- `open_match` — start working a pair (usually one open match at a time); seeds the match notebook
- `message_party` — queue a later broker turn in `source` or `candidate` chat
- `update_notebook` — shared terms plus agent_note/next_action for later turns
- `skip_match` / `reject_match` — close a pair
- `accept_match` — this user agreed; cards share when both have
- `share_contacts` — match card after both sides accept
- `get_match_events` / `get_request_snapshot` — fuller history or the living brief
- `request_attachment` — upload control in this chat for a file or link
- `classify_attachment` — public vs personal from conversation, caption, filename
- `share_attachment` — deliver to the other party; personal items ask permission
- `record_share_grant` — chat consent for a personal share

Python still enforces: no matching yourself, no contacts before accept, identity redaction in cross-party text before accept, max one open match, skip-reopen only after a brief changes.

### LLM

OpenRouter (primary) uses LangChain `ChatOpenRouter` with a config-driven `reasoning` object (`OPENROUTER_REASONING_ENABLED` / `EFFORT` / `EXCLUDE`). Default model is `nvidia/nemotron-3-ultra-550b-a55b:free` at medium effort. Groq uses `ChatGroq` with `reasoning_format=parsed` so Qwen thinking stays in `reasoning_content` and tools come back as JSON `tool_calls` (not XML). Gemini stays on `ChatOpenAI`. The agent uses native tool calling. Semantic indexing (`invoke_text_model`) turns reasoning off so the profile rewrite does not spend a thinking budget on free providers; retrieval planning and pair evaluation still use structured JSON helpers with reasoning on. When OpenRouter returns HTTP 200 with a `provider_unavailable` / Unmarshaller error body, the broker tool loop retries the model invoke up to `AGENT_MODEL_INVOKE_RETRIES` (default 3) and tells the model the last generation failed so it continues from tools that already succeeded.

If no API key is configured, the agent holds the request and says the model is unavailable.

The system prompt is the broker's operating brief: who is in this chat, what the packet contains, when each tool applies, how to decide, and how to speak. Bound schemas still carry arguments. User-facing replies are a question, an acknowledgement, or a short update — not a recap of the brief, of tool findings, or of the work of the turn. Empty search is one short line.

The broker system prompt is the same in every environment. When `ENV` is `local`, `dev`, or `development`, `use_dev_prompts()` still selects compact tool, index, search, evaluator, and trigger strings. Other environments bind the production copies of those.

Agent debug logs go to `backend-agent/logs/brokerai.log` (and the console). There is no decision-log table.

### RAG

Chroma persists under `backend-agent/data/chroma`, collection `agent_requests`. Each indexed brief is one semantic document produced by the LLM. Search is semantic only: it plans a counterpart-oriented query, retrieves nearest neighbors from Chroma with no metadata filters, then hydrates open briefs that belong to someone else.

## Frontend

The chat client talks to `/broker/sessions` and `/broker/sessions/{id}/messages`. Contact cards still use `kind: broker_contact_card` (name, email, location — **no phone number**) and Connect hits `/broker/matches/{id}/connect`, which creates `agent_connections` and opens a direct chat.

Direct party chat is a separate inbox from broker sessions:

- `GET /broker/connections` — every 1:1 chat for this user (peer, last message, unread)
- `GET /broker/connections/{id}` — history; marks the thread read
- `POST /broker/connections/{id}/messages` and `/attachments` — text, photos, files
- `WS /broker/ws?access_token=...` — live fan-out (`connection.created`, `connection.message`)
- Web Push via VAPID (`GET /broker/push/vapid-public-key`, `POST /broker/push/subscribe`)

**Realtime is FastAPI WebSockets, not Supabase Realtime.** Authz and file access already live in FastAPI (not Postgres RLS), and `DATABASE_URL` may be local Postgres or Neon. Supabase stays Auth + Storage. Push is sent from the same process that persists the message; the service worker suppresses the banner if a window is focused.

Files and links use the composer paperclip / link control. Structured assistant cards: `broker_attachment_request`, `broker_attachment_permission`, `broker_attachment_share`.

Visual system (2026-09-05): warm paper canvas, Plus Jakarta Sans, pine accent, nameless SVG mark (two overlapping circles + center node — no product name). Thinking indicator shows only while waiting for an agent reply after a user chat turn, delayed ~280ms. Composer is an auto-growing textarea (Enter sends, Shift+Enter newline).

Point `NEXT_PUBLIC_BACKEND_URL` at the agent backend to use it.

## Run

```bash
cd backend-agent
uv sync
uv run uvicorn app.main:app --reload
```

```bash
cd frontend
npm run dev
```

Local auth: frontend temporary sign-in (hidden when `NODE_ENV=production`); backend accepts `dev:<email>` only when `ENV=local`. Real Supabase access tokens are signature-checked: ES256/RS256 via JWKS (`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`), legacy HS256 via `SUPABASE_JWT_SECRET`. JWKS is fetched with httpx and cached; the event loop is not blocked. `/docs` and `/db/*` are gone in production. Stale matches run via `POST /internal/process-stale` with `X-Job-Secret`.

Local still uses `create_all` on startup. Other environments refuse to boot unless Alembic is at head (`uv run alembic upgrade head`).

## Production configuration (Supabase)

In the production (and local-if-using-real-auth) project:

1. **Project Settings → API**
   - Copy **Project URL** → `SUPABASE_URL`
   - Copy **JWT Secret** (legacy secret, not the anon or service_role key) → `SUPABASE_JWT_SECRET`
   - Copy **service_role** → `SUPABASE_SERVICE_ROLE_KEY` (backend only)
   - Issuer defaults to `{SUPABASE_URL}/auth/v1`; set `SUPABASE_JWT_ISSUER` only if it differs
   - Audience stays `authenticated`
2. **Authentication → URL configuration**
   - Site URL: `https://app.example.com` (local: `http://localhost:3000`)
   - Redirect URLs: `https://app.example.com/auth/callback` (and `http://localhost:3000/auth/callback` for local)
3. **Authentication → Providers:** enable Google and Email (magic link). Google authorized redirect is `https://<project-ref>.supabase.co/auth/v1/callback`
4. **Storage:** private bucket `broker-attachments`, 10 MB limit, deny-all RLS for `anon`/`authenticated` (API uses the service role)
5. **Database:** app `DATABASE_URL` uses the **transaction pooler** (`:6543`). Run `uv run alembic upgrade head` against the **direct** URI (`:5432`)

## Next

- Frontend visibility for open matches
- Multi-worker WebSocket fan-out (Redis) if we run more than one uvicorn worker
- Multi-party deals beyond 1:1 pairs
