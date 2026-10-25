# BrokerAI — Project Context

Last updated: 2026-10-25 (REQ-016 public landing and privacy pages)

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
       evaluate_pair / present_candidates / open_match / message_party /
       update_notebook / close_match / accept_match / share_contacts
  → Postgres + Chroma
  → reply to the current user (and optionally a named party via message_party)
```

One agent talks to every party. Screening is one-sided: a background pipeline indexes the brief, searches, and runs `evaluate_pairs` (up to `MAX_PAIR_PER_REQUEST`, default 3). Results are stored on `agent_suggested_matches` for **this request only**: `strong_match` (Strong fit cards), `possible_match` (Close fit cards: what fits vs still open), `pending_clarify` (this-user questions, no card), or skip. The counterpart never sees that evaluation. Cards appear on Your request as Interested/Skip (`present_candidates`), brief-only with no photos. A match lane exists only after Interested. Close-fit Interested then asks the other person on that match lane. Open matches are uncapped. Isolation is **match lanes**, not a second agent: `agent_messages.match_id` is null for the request/brief lane and set for that pair. Each turn sets `focus_match_id`; history and the context packet are scoped to that lane (`open_matches` = full snapshot of the focus only; request-lane packets include `suggested_matches`). The model does not receive a roster of other live matches. `update_request` always patches the shared living brief, including from a match lane when this person adds a detail that applies beyond that pair. Pair-specific terms stay in the match notebook. `SESSION_ROLE` follows the focused match (request lane is always source).

Do not split this into intake vs mediation agents. The product is one broker with the full tool set on every turn. Parallelism already exists as fire-and-forget `match_context` turns on the other party's matching lane.

Session chat is private; `agent_matches.notebook` is shared agent memory (facts, outstanding, agent_note, next_action) and is **not** shown to humans. `think` is a this-turn plan only. Anything the next turn must remember goes in `update_notebook`. `index_request` starts a background pipeline (index, then search and pair evaluation). The broker wakes once when that pipeline finishes. `search_counterparties` starts the search-and-screen job when the brief is already indexed. Pair evaluation also applies request-lane `view_filters` set by `evaluate_pair`. The agent replies after starting the work. `message_party` queues a **separate** broker turn after this request commits, on the other party's **match lane** only. It is refused until Interested has opened a match. Close-fit questions for the other person wait until Interested, then go on that match lane so they stay tied to the pair. After Interested, Python opens the pair and runs a `request_ready` kickoff on the opener's new match lane. `ask_clarifying_question` stays on Your request as `pending_questions` tagged with `candidate_id` and is asked after Strong/Close fit cards. After they answer, `evaluate_pair` re-screens those stored ids (no new search for that answer). A leftover live pair becomes a Close fit card; it is not messaged from Your request. `update_request` patches the brief without a full rewrite. If a user skips follow-up questions or answers only some of them, the agent keeps working with what it has and may ask a skipped detail later only if a live match actually needs it.

Product rules live in `docs/REQUIREMENTS.md` (newest: REQ-016 — public landing and privacy pages for OAuth).

Public marketing lives at `/` (`frontend/app/page.tsx`). Privacy policy lives at `/privacy` for Google OAuth consent. Public site and app are `broker-ai.app`. Login still at `/login`; the app remains `/app`. User-facing copy must not mention Vercel, staging hosts, or that the domain is pending.

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

- `agent_sessions`, `agent_messages` (`match_id` null = request lane, set = that match lane). Deleting a session that still has matches tombstones `session.status=deleted` and closes those matches with `request_closed` so the remaining party keeps a match tab; `match_id` is `ON DELETE SET NULL`, so dropping the match row would dump that chat onto Your request.
- `agent_requests` — one living brief per session (kept closed when the owner deletes a session that still has matches), plus `pending_questions` this person still owes
- `agent_matches` — a pair of briefs plus `notebook` (shared facts and outstanding question)
- `agent_suggested_matches` — source-only screened candidates (strong_match / presented / interested / skipped) plus the request-lane card message. Clarifying questions this person still owes live on `agent_requests.pending_questions`, with no candidate ids.
- `agent_match_reads` — per-user last-read for match-lane unread badges
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

`skip_match` / `reject_match` may close an `accepted` or `connected` match (status becomes `closed`). Closing one pair leaves other open matches on the request. `message_party` writes into the other party's match lane for an open pair. A clarifying question for this user stays in this chat (`ask_clarifying_question`); stored suggestions are re-evaluated after they answer. `ask_other_person` is asked on the match lane only after Interested. Skip on a suggestion card excludes that candidate from later fills for this request. Unacted presented cards stay in chat and are not sent again. Search, evaluate, and present keep at most one candidate request per counterpart user.

`waiting_match_id` on a request is attention (“we last asked this person about this match”). It does not route the next message. The POST body `match_id` (and outreach `focus_match_id`) chooses the lane. Frontend match tabs send that id; the request tab omits it.

### Agent tools

Bound schemas describe what each tool does. The broker chooses among them.

- `think` — private working note for this turn
- `save_request` — full create/rewrite of the brief
- `update_request` — patch only changed fields
- `index_request` — start the background index then search and pair screen; the broker wakes when that pipeline finishes
- `search_counterparties` — start a background search and pair screen of the indexed brief; return a count later, not candidate briefs
- `evaluate_pair` — re-screen stored or last-search ids; optional `filters` is a view overlay (`view_filters`) that does not change the saved brief
- `present_candidates` — writes Interested/Skip cards on the request lane for new strong matches; already-shown cards are not sent again; does not notify the other person
- `request_attachment` — records that a file would help; the broker asks in chat; no upload card
- `open_match` — start working a pair this person already marked Interested; seeds the match notebook
- `message_party` — queue a later broker turn in the other person's chat on an open match lane
- `update_notebook` — shared terms plus agent_note/next_action for later turns
- `skip_match` / `reject_match` — close a pair
- `accept_match` — this user agreed; cards share when both have
- `share_contacts` — match card after both sides accept
- `get_match_events` / `get_request_snapshot` — fuller history or this person's living brief
- `get_match_brief` / `answer_match_question` — source-relative counterpart facts, never the other living brief
- `classify_attachment` — public vs personal from conversation, caption, filename
- `share_attachment` — deliver to the other party; personal items ask permission
- `record_share_grant` — chat consent for a personal share

Python still enforces: no matching yourself, no contacts before accept, identity redaction in cross-party text before accept, no `open_match` until Interested, suggestion present cap `MAX_PAIR_PER_REQUEST` (default 3), skip-reopen only after a brief changes. `message_party` may use `candidate_id` on the other person's request lane before Interested. Match tools default `match_id` to the focused lane.

### LLM

OpenRouter (primary) uses LangChain `ChatOpenRouter` with a config-driven `reasoning` object (`OPENROUTER_REASONING_ENABLED` / `EFFORT` / `EXCLUDE`). Default model is `nvidia/nemotron-3-ultra-550b-a55b:free` at low effort. Broker chat sampling is `temperature=0.3` and `top_p=0.8`. OpenRouter routing prefers `deepinfra`, then `novita`, `coreweave`, `parasail`, with fallbacks on and `require_parameters` so endpoints must honor tools / JSON. Broker tool binding does not send `parallel_tool_calls` on OpenRouter; no Qwen 3.8 27B host advertises that parameter, and requiring it 404s every endpoint. OpenRouter has no separate thinking temperature; effort is the thinking control. Groq uses `ChatGroq` with `reasoning_format=parsed` so Qwen thinking stays in `reasoning_content` and tools come back as JSON `tool_calls` (not XML). Gemini stays on `ChatOpenAI`. The agent uses native tool calling. Semantic indexing (`invoke_text_model`) turns reasoning off so the profile rewrite does not spend a thinking budget on free providers; request title/summary generation (`generate_request_copy` on save/update) uses structured JSON with reasoning off the same way. Retrieval planning and pair evaluation still use structured JSON helpers with reasoning on. `AGENT_NAME` (default `BrokerAI`) is the chat welcome name; the frontend mirror is `NEXT_PUBLIC_AGENT_NAME`. When OpenRouter returns HTTP 200 with a `provider_unavailable` / Unmarshaller error body, the broker tool loop retries the model invoke up to `AGENT_MODEL_INVOKE_RETRIES` (default 3) and tells the model the last generation failed so it continues from tools that already succeeded.

If no API key is configured, the agent holds the request and says the model is unavailable.

The system prompt is the broker's operating brief: who is in this chat, what the packet contains, when each tool applies, how to decide, and how to speak. Bound schemas still carry arguments. User-facing replies are an acknowledgement, a short update, or questions as needed — not a recap of the brief, of tool findings, or of the work of the turn. When mentioning a counterpart before accept, share only terms that answer this person's request. Empty search is one short line. On a match lane before accept, `other_brief` is a stub (`possible_counterpart`). `get_match_events` returns events and the notebook only. Counterpart facts go through `get_match_brief` and `answer_match_question`. Notebook `facts` are this person's stated terms; cross-party inference belongs in `agent_note`. Index, search, and pair evaluation run as one background pipeline; a `request_ready` turn continues when that pipeline finishes. After a successful screen, the broker does not start another search. A browse overlay is `evaluate_pair` filters; only this person's Skip is excluded from later search. Failed screen jobs retry the parse once in Python, then the agent retries quietly without a user-visible “restarted search” bubble. Strong fit and Close fit cards are presented immediately; this person's pending questions are asked on a follow-up `clarify` turn, tagged with candidate ids. Close-fit outreach waits until Interested. `evaluate_pair` re-screens stored candidate ids after those answers.

Agent debug logs go to `backend-agent/logs/brokerai-YYYY-MM-DD.log` (one file per day, and the console). Model reasoning is logged as `model thinking`. There is no decision-log table.

### RAG

Chroma persists under `backend-agent/data/chroma`, collection `agent_requests`. Each indexed brief is one semantic document produced by the LLM. Search is semantic only: it plans a counterpart-oriented query, retrieves nearest neighbors from Chroma with no metadata filters, then hydrates open briefs that belong to someone else.

## Frontend

The chat client talks to `/broker/sessions` and `/broker/sessions/{id}/messages` (`match_id` optional). Session GET/list include `matches[]` (label, status, unread, connect offer, connection id). `POST /broker/matches/{id}/read` clears a lane badge. Contact cards still use `kind: broker_contact_card` (name, email, location — **no phone number**) and Connect hits `/broker/matches/{id}/connect`, which creates `agent_connections` and opens a direct chat. The request view has a match-lane rail (request tab + one tab per pair); the UI does not auto-switch after `open_match`. Introduction offers render only on that match's tab; the request lane shows banners when another match is waiting, unread, or ready to introduce. Thinking and in-flight sends are per-lane.

Direct party chat is a separate inbox from broker sessions:

- `GET /broker/connections` — every 1:1 chat for this user (peer, last message, unread)
- `GET /broker/connections/{id}` — history; marks the thread read
- `POST /broker/connections/{id}/messages` and `/attachments` — text, photos, files
- `WS /broker/ws?access_token=...` — live fan-out (`connection.created`, `connection.message`)
- Web Push via VAPID (`GET /broker/push/vapid-public-key`, `POST /broker/push/subscribe`)
- Activity email via Resend when the recipient has no live `/broker/ws` (match_context outreach, leftover intro offer, contact cards). `PATCH /users/me` and `GET /mail/unsubscribe`. 1:1 connection mail is out of scope; push still covers those threads. Presence is in-process (one uvicorn worker), same as the hub.

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
3. **Authentication → Providers:** enable Google and Email (magic link). Google authorized redirect is `https://<project-ref>.supabase.co/auth/v1/callback`. Google sign-in auto-creates `user_profiles` from People API (`names`, `genders`, `birthdays`) using extra scopes `user.gender.read` and `user.birthday.read`. Enable the People API on the Google Cloud project and add those scopes on the OAuth consent screen. Magic-link users complete the same name / gender / date-of-birth form. `location` and `mobile_number` stay nullable on the table and are not collected.
4. **Storage:** private bucket `broker-attachments`, 10 MB limit, deny-all RLS for `anon`/`authenticated` (API uses the service role)
5. **Database:** app `DATABASE_URL` uses the **transaction pooler** (`:6543`). Run `uv run alembic upgrade head` against the **direct** URI (`:5432`)

## Next

- Exclusive-close policy on accept (housing vs parallel freelance) as a product rule, not the lane model
- Multi-worker WebSocket fan-out (Redis) if we run more than one uvicorn worker
- Multi-party deals beyond 1:1 pairs
