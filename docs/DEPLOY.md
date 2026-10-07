# Deploy BrokerAI MVP

| Piece | Host | Directory |
| --- | --- | --- |
| Web | Vercel | `frontend/` |
| API | Fly.io (`brokerai-api`) | `backend-agent/` |
| Postgres, Auth, Storage | Supabase project `gwowjvxtfzjgcwdacjxc` | — |

Chroma lives on a Fly volume attached to **one** API machine. Local Docker is not required.

## 1. Accounts (browser)

1. [Fly.io](https://fly.io) — sign in and add a payment method.
2. [Vercel](https://vercel.com) — sign in (Hobby is enough for MVP).
3. [Supabase](https://supabase.com/dashboard/project/gwowjvxtfzjgcwdacjxc) — after the Vercel production URL exists:
   - Auth → URL configuration: Site URL = Vercel origin (e.g. `https://<project>.vercel.app`)
   - Redirect URLs include `https://<project>.vercel.app/auth/callback`
   - Email (magic link) enabled
   - Storage bucket `broker-attachments` exists and is private

Then in this repo’s terminal:

```bash
fly auth login
fly auth whoami
vercel login
vercel whoami
```

## 2. Fly API — create app and volume

```bash
fly apps create brokerai-api --org personal
fly volumes create brokerai_chroma --app brokerai-api --region nrt --size 3
```

If `personal` is not your org, use `fly orgs list`. If `brokerai-api` is taken, change `app =` in `backend-agent/fly.toml`.

Tokyo (`nrt`) sits next to the production Supabase region (`ap-northeast-1`).

## 3. Fly API secrets

Paste values from `backend-agent/.env.production` or the Supabase dashboard. Do not commit them.

```bash
cd backend-agent

fly secrets set \
  DATABASE_URL='postgresql+asyncpg://postgres.gwowjvxtfzjgcwdacjxc:[PASSWORD]@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres' \
  SUPABASE_JWT_SECRET='...' \
  SUPABASE_SERVICE_ROLE_KEY='...' \
  INTERNAL_JOB_SECRET='...' \
  OPENROUTER_API_KEY='...' \
  LLM_MODEL='qwen/qwen3.8-27b' \
  --app brokerai-api
```

`DATABASE_URL` must use `postgresql+asyncpg://` and the **transaction pooler** (`:6543`). URL-encode special characters in the password (`@` → `%40`).

Optional: Groq, Gemini, Resend, VAPID. See the secrets list in the previous session notes.

After the Vercel URL is known:

```bash
fly secrets set \
  PUBLIC_APP_URL='https://<project>.vercel.app' \
  CORS_ORIGINS='["https://<project>.vercel.app"]' \
  --app brokerai-api
```

## 4. Deploy the API

Backend public URL (no custom domain): `https://brokerai-api.fly.dev`

```bash
cd backend-agent
fly deploy --app brokerai-api
fly scale count 1 --app brokerai-api
curl -sS https://brokerai-api.fly.dev/health
curl -sS https://brokerai-api.fly.dev/health/ready
```

Keep **one** machine. The volume is pinned to it; do not scale out.

`fly.toml` uses scale-to-zero: `auto_stop_machines = "stop"`, `min_machines_running = 0`. After about five minutes with no HTTP/WebSocket traffic, Fly stops the VM. The next request starts it again. Stopped time is not billed for CPU/RAM. The Chroma volume (`brokerai_chroma`) is billed while it exists. The first request after a stop waits for boot plus `alembic upgrade head` and uvicorn (health check grace is 2 minutes). An open `/broker/ws` connection counts as traffic, so the machine stays up while someone is in chat.

## 5. Vercel frontend (CLI is enough)

The dashboard is optional. CLI from `frontend/`:

```bash
cd frontend
vercel login
vercel link
# First run: set Root Directory to frontend if you link from the repo root instead.
vercel env add NEXT_PUBLIC_SUPABASE_URL production
vercel env add NEXT_PUBLIC_SUPABASE_ANON_KEY production
vercel env add NEXT_PUBLIC_BACKEND_URL production
vercel env add BACKEND_URL production
vercel --prod
```

When `vercel env add NEXT_PUBLIC_BACKEND_URL` asks for a value, use `https://brokerai-api.fly.dev`. Same for `BACKEND_URL`.

Vercel assigns `https://<project>.vercel.app` (plus a unique `https://<project>-<hash>.vercel.app`). No custom domain is required.

`NEXT_PUBLIC_*` is baked at **build** time. Change a public var and run `vercel --prod` again.

Then put that `https://<project>.vercel.app` origin into Fly `PUBLIC_APP_URL` / `CORS_ORIGINS` and Supabase Auth Site URL + `/auth/callback`.

## 6. Stale-match job (optional)

`POST https://brokerai-api.fly.dev/internal/process-stale` with header `X-Job-Secret`. Skip until the API is healthy.
