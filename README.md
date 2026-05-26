# BrokerAI

BrokerAI is an intelligent conversational broker that connects people with compatible needs and offers. It uses a FastAPI backend, LangGraph-based orchestration, semantic retrieval with ChromaDB, and a Next.js frontend for chat-driven intake and mediation.

## What It Does

- Collects natural-language needs and offers through chat.
- Turns ready conversations into structured broker requests.
- Stores matchable requests in PostgreSQL and indexes semantic profiles in ChromaDB.
- Retrieves likely counterparties with vector search.
- Uses LLM judgment to evaluate matches and start private mediation.
- Shares contact cards only after both parties accept the core match terms.

## Tech Stack

- Backend: FastAPI, Python 3.11+, Pydantic v2, SQLAlchemy 2.0, LangChain, LangGraph
- Vector store: ChromaDB local persistence for MVP
- Database: PostgreSQL, suitable for Supabase or Neon
- Frontend: Next.js 15 App Router, TypeScript, Tailwind CSS
- Auth: Supabase Auth with a local development fallback
- LLM providers: OpenRouter primary, with Groq and Gemini OpenAI-compatible fallbacks

## Repository Layout

```text
backend/
  app/
    agents/
    api/
    core/
    db/
    schemas/
    services/
  tests/
frontend/
  app/
  components/
  lib/
  public/
docs/
  PROJECT_CONTEXT.md
```

## Prerequisites

- Python 3.11+
- uv
- Node.js 20+
- npm
- PostgreSQL
- Supabase project for production-like auth, or local dev-session fallback

## Backend Setup

```bash
cd backend
cp .env.example .env
uv sync
uv run uvicorn app.main:app --reload
```

The backend runs at `http://127.0.0.1:8000` by default.

Important backend environment variables:

- `DATABASE_URL`
- `LLM_PROVIDER`
- `OPENROUTER_API_KEY`
- `OPENROUTER_BASE_URL`
- `LLM_MODEL`
- `GROQ_API_KEY`
- `GEMINI_API_KEY`
- `CHROMA_PERSIST_DIR`
- `MATCH_EXPORT_DIR`
- `SUPABASE_URL`

## Frontend Setup

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

The frontend runs at `http://localhost:3000` by default.

Important frontend environment variables:

- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`
- `NEXT_PUBLIC_BACKEND_URL`

## Local Development

Start the backend first, then the frontend:

```bash
cd backend
uv run uvicorn app.main:app --reload
```

```bash
cd frontend
npm run dev
```

For local auth testing, the frontend includes a temporary sign-in flow and the backend accepts `dev:<email>` bearer tokens only when `ENV=local`.

## Tests And Checks

Backend:

```bash
cd backend
uv run pytest
uv run ruff check .
```

Frontend:

```bash
cd frontend
npm run typecheck
npm run lint
```

## Git Hygiene

Do not commit real environment files, local vector databases, generated match exports, dependency directories, or framework build output. The root `.gitignore` excludes these by default.

Before the first commit, confirm that only source files, lockfiles, docs, examples, and public assets are staged:

```bash
git status --short
```

## Project Context

The living architecture and implementation notes are maintained in `docs/PROJECT_CONTEXT.md`. Update that file when major product, architecture, or integration decisions are made.
