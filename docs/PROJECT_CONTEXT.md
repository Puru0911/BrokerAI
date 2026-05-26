# BrokerAI — Project Context

Last updated: 2026-05-21

## MVP Goal

Build a conversational AI broker that:

- Collects user needs/offers via chat
- Stores requests in a vector store
- Matches compatible parties
- Mediates follow-ups while keeping user privacy

## Current State

### Backend

FastAPI skeleton exists with a health endpoint.

- `backend/app/main.py` — app factory + router
- `backend/app/api/routes/health.py` — `GET /health`
- `backend/app/core/config.py` — settings via `.env`
- `backend/app/db/models/user_profile.py` — Postgres-backed user profile table keyed by Supabase user id
- `backend/app/api/routes/users.py` — `GET /users/me` and `POST /users/me` for first-login profile collection
- `backend/app/db/models/broker_session.py` — broker session and message persistence
- `backend/app/api/routes/broker.py` — authenticated broker session/message APIs
- `backend/app/services/broker_request_builder.py` — converts ready broker decisions into structured request JSON
- `broker_requests` table — one canonical structured request document per session for MVP, stored in Postgres JSONB
- `backend/app/services/broker_rag.py` — LLM-prepared semantic request indexing and Chroma-backed candidate retrieval
- `backend/app/services/broker_orchestrator.py` — top-level LangGraph router that decides whether a user message should continue intake or active mediation, and triggers indexing/retrieval/match evaluation when a request is ready
- `backend/app/services/broker_matching.py` — LLM match evaluator and initial outreach strategist for retrieved request pairs
- `backend/app/services/broker_mediation.py` — active mediation lookup and reply handling for matched parties
- `backend/app/services/structured_llm.py` — shared OpenRouter structured-output adapter for intake and RAG LLM tasks
- `backend/app/services/broker_intake.py` — LangGraph broker orchestration with master broker and clarifier nodes
- `broker_decision_logs` table — stores provider/model/status/decision summary/errors/latency for LLM decisions; logs audit summaries, not hidden chain-of-thought
- `broker_matches` and `broker_mediation_events` tables — durable match lifecycle state and append-only mediation audit events
- `broker_party_connections` table — durable contact-connection record created after an accepted match when a party presses Connect on a shared contact card
- `backend/app/services/broker_contact.py` — contact-sharing service that creates structured contact-card messages for both accepted parties and records connection events

LLM orchestration:

- Primary provider: OpenRouter through LangChain `ChatOpenAI` compatibility. Groq is also supported through its OpenAI-compatible API for `llama-3.3-70b-versatile`, and Gemini is supported through Google's OpenAI-compatible endpoint for `gemini-2.5-flash`.
- Orchestration: a top-level BrokerAI master graph delegates user messages to intake or mediation. The intake subgraph uses `prepare_context`, `master_broker`, optional `clarifier`, and `finalize_decision` nodes.
- Config: `LLM_PROVIDER`, `LLM_REQUEST_TIMEOUT_SECONDS`, `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `LLM_MODEL`, `GROQ_API_KEY`, `GROQ_BASE_URL`, `GROQ_LLM_MODEL`, `GEMINI_API_KEY`, `GEMINI_BASE_URL`, `GEMINI_LLM_MODEL`.
- The master broker node owns routing and session state: it decides whether the request needs clarification or is `ready_for_matching`.
- The clarifier node only runs when delegated by the master and writes the next user-facing clarification message.
- Clarification is a loop across conversation turns: the master may keep delegating until enough information exists, but each clarifier turn should focus on the most useful next slice of context and avoid overwhelming the user.
- Prompt posture: prompts define agent roles and orchestration contracts without over-scripting the conversation. The master prompt produces general-purpose request state and chooses whether matching can begin; the clarifier prompt follows that delegation in natural broker language while keeping intake trustworthy and privacy-aware.
- Intake routing should stay master-led and generalist. Do not add category-specific code guards for clarification decisions unless the product explicitly needs a deterministic policy outside model judgment.
- If no API key is configured or the LLM graph fails, BrokerAI records the failure and returns an LLM-unavailable intake response rather than using hardcoded field-follow-up rules.
- When the master marks a session `ready_for_matching`, BrokerAI upserts a `broker_requests` row with normalized metadata and `structured_data` JSONB.
- Before indexing, the RAG layer asks the configured OpenRouter LLM to produce a detailed privacy-aware semantic profile for the ready request and stores that profile under `structured_data.semantic_retrieval`.
- Chroma embeds the profile's semantic document into a local persistent request collection, records embedding status on `broker_requests`, and retrieves candidate requests through `/broker/requests/{request_id}/matches`.
- Before a vector query, the RAG layer asks the LLM for a counterparty-oriented semantic retrieval plan; Chroma embeds that query text and returns nearest candidates for downstream ranking.
- After retrieval, the matching evaluator judges each pair, creates `broker_matches`, skips weak/non-complementary candidates, and sends first in-app BrokerAI outreach messages according to its `source_first`, `candidate_first`, or `both` strategy.
- Previously skipped match pairs are eligible for re-evaluation when either underlying request has changed after the skip. This lets BrokerAI recover when a user later updates a constraint or offer that makes an earlier non-match viable.
- When a user replies in a session with active mediation, the top-level orchestrator routes the message to mediation instead of intake. The mediation reply handler classifies accept/reject/question/update/other, updates match state, writes events, and relays messages to the other party when appropriate.
- Mediation reply handling includes prior mediation event history in the LLM context, stores negotiated term updates under each request's `structured_data.mediation_terms`, and keeps accepted matches routable through mediation until final coordination/closure.
- Mediation decisions include an explicit `agreement_reached` flag so accepting another party's concrete proposal can trigger the accepted-match flow without forcing the proposing party through a redundant confirmation turn.
- Once both sides accept the core terms of a mediated match, BrokerAI automatically shares privacy-aware contact-card messages with both parties. The card is structured JSON rendered by the frontend, and its Connect action creates a durable `broker_party_connections` record that can back direct party-to-party chat.
- Stale mediation can be processed through `/broker/mediations/process-stale`; timed-out active matches are expired and BrokerAI attempts the next candidate for the source request.
- The match endpoint returns a request preview for the MVP. The full JSONB payload remains an internal matching artifact until BrokerAI adds LLM ranking, privacy policy, and mediation between parties.
- Architecture boundary: `broker_sessions` and `broker_messages` preserve conversation history, `broker_requests` is the canonical matchable request document, and Chroma is a semantic retrieval index rather than the system of record.
- Embedding contract for the MVP: `broker_rag.py` explicitly configures Chroma's `DefaultEmbeddingFunction`, which uses the local `all-MiniLM-L6-v2` model. Each request is indexed as one LLM-produced semantic document rather than chunks because an accepted broker request is an atomic match unit at this stage.
- Temporary testing flow: after a request is embedded, BrokerAI automatically runs semantic retrieval and writes a local JSON artifact to `MATCH_EXPORT_DIR` using the source request title as the filename. This is for inspecting semantic retrieval plans and candidate matches before the real match lifecycle exists. The automatic export limit is controlled by `MATCH_EXPORT_AUTO_LIMIT`.

Run locally:

- `cd backend && uv run uvicorn app.main:app --reload`

### Frontend

Next.js (App Router) skeleton exists with Tailwind and Supabase Auth login flow.

Auth flow:

- `frontend/app/login/page.tsx` — Google OAuth + email magic link
- `frontend/app/login/actions.ts` — local-only temporary sign-in for Supabase email rate limit fallback
- `frontend/lib/auth/dev-session.ts` — local dev session cookie helper
- `frontend/app/auth/callback/route.ts` — exchanges auth code for session, then redirects
- `frontend/middleware.ts` — protects `/app/*` and `/profile/*`, redirects to `/login` if unauthenticated
- `frontend/app/app/page.tsx` — protected chat workspace after login
- `frontend/app/profile/page.tsx` — first-login user profile form before chat access
- `frontend/components/profile/create-profile-form.tsx` — collects name, location, and mobile number
- `frontend/components/chat/broker-chat.tsx` — responsive chat UI with live broker sessions, messages, new-session creation, and sign out
- `frontend/lib/api/broker.ts` — client API helper for broker session orchestration
- Structured BrokerAI contact-card messages render as contact detail cards in chat with a Connect button. The current Connect action creates the backend party-connection record; direct party-to-party messaging UI is the next layer on top of that record.
- `frontend/public/brokerai-logo.jpg` — BrokerAI logo asset used on login and chat screens
- New users do not get an empty broker session during chat boot. The chat renders a local BrokerAI welcome message before any session exists, and the first submitted request creates the first session with a request-based title and intake decision in one API call.
- The chat shell is fixed to the viewport; session history and chat messages scroll inside their own panes. Sending a message is optimistic: the user's message appears immediately, followed by a BrokerAI thinking indicator until the API response returns.

Local development fallback:

- If Supabase magic-link email is rate limited, enter an email on `/login` and use **Temporary local sign in**.
- The backend accepts `dev:<email>` bearer tokens only when `ENV=local`.
- This bypass is for local development only and must not be used in production.

Environment variables:

- `frontend/.env.example` — `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_BACKEND_URL`
- `backend/.env.example` — basic backend config

Run locally:

- `cd frontend && npm i && npm run dev`

## Next Modules (Proposed)

- Add frontend visibility for active mediations and match status.
- Build direct party-to-party chat UI on top of accepted `broker_party_connections`.
- Add migrations for evolving Postgres tables beyond the current `create_all` bootstrap.
