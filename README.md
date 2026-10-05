# Worklane

One console for two ways of finding work, each run as its own service:

- **Freelance**: watches Freelancer.com for new projects, decides which ones are worth a bid, writes the proposal with AI, and sends the bid from your account.
- **Jobs**: turns a pasted job description into a tailored application email, finds the recipient in the text, and sends it from your own Gmail after you review it.

```
Freelance: new project -> hard rules -> selection prompt -> proposal prompt -> approval queue or auto-bid
Jobs:      job description -> recipient + details extracted -> AI draft -> your review -> Gmail
```

The Jobs service lives in `backend/app/jobs/` with its own tables (`job_*`), API (`/api/jobs/...`) and pages (`/jobs/...`). It shares only the login, the database connection and the AI client with the freelance service.

| Part | Tech | Hosted on |
|---|---|---|
| `backend/` API | FastAPI, SQLAlchemy, Alembic | Render (web service) |
| `backend/` worker | arq | Render (background worker) |
| Redis | queue for the worker | Upstash |
| Database | PostgreSQL via SQLAlchemy ORM + Alembic migrations | Supabase |
| `frontend/` dashboard | Next.js | Vercel |

## Run locally

Backend (uses your Supabase database and polls inside the web process, so no Redis is needed):

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
copy .env.example .env            # then fill in the values, including the Supabase DATABASE_URL
alembic upgrade head
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
pnpm install
copy .env.example .env.local
pnpm run dev
```

Open http://localhost:3000 and sign in with `ADMIN_EMAIL` / `ADMIN_PASSWORD` from `backend/.env`.

Tests: `cd backend && pytest`. They start their own embedded PostgreSQL and never touch Supabase.

## First-time setup in the dashboard

EasyBid starts **paused** and in **manual** mode. Nothing is fetched or sent until you switch it on.

1. **Settings**: import skills from your Freelancer profile, set budgets, bid cap and pricing. A project needs at least "Minimum matching skills" of your skills among its tags, and none of your blocked skills.
2. **Profile**: add your bio, past projects and links. Proposals only claim what is listed here.
3. **Prompts**: save a proposal prompt (required) and a selection prompt (optional). Use **Test** to preview against a real project; a test never sends a bid.
4. **Dashboard**: press **Resume**.
5. **Queue**: review, edit and approve proposals. Once you trust the output, switch the mode to `semi` or `auto` in Settings.

Modes:

- `manual`: every proposal waits in the queue.
- `semi`: projects scoring at or above the semi-auto score are bid on automatically, the rest wait.
- `auto`: every selected project is bid on automatically.

The daily bid cap and the pause switch apply in every mode, including manual approval.

## Deploy

### 1. Supabase (database)

1. Create a project.
2. Project Settings > Database > Connection string > **Session pooler**. Copy the URI and put your database password in it. This is `DATABASE_URL`.

Use the session pooler rather than the direct connection: Render has no IPv6, and the direct connection is IPv6-only. The tables are created by `alembic upgrade head`, which the API container runs on every start.

All database access goes through the SQLAlchemy ORM in `backend/app/models.py`; schema changes are Alembic migrations in `backend/alembic/versions/`. The migration enables row level security on every table with no policies, so Supabase's public Data API (the anon key) cannot read or write them. The backend connects as the table owner, which bypasses row level security.

If you ran EasyBid on the old local SQLite file, copy that data across once: `python -m scripts.import_sqlite easybid.db`.

### 2. Render (backend)

1. Push this repository to GitHub.
2. Render > New > Blueprint, pick the repository. `render.yaml` creates the API and the worker.
3. Fill in the environment variables it asks for. `CORS_ORIGINS` is your Vercel URL, for example `https://easybid.vercel.app`.

`REDIS_URL` on the worker is your Upstash URL: Upstash console > your database > Connect > TCP, the one that starts with `rediss://`. Upstash bills per command; the worker polls every 5 seconds to keep that low.

To run a single service instead of two, create only the web service and leave `EMBEDDED_SCHEDULER` unset (it defaults to true): the polling loop runs inside the web process and Redis is not used at all. The blueprint sets it to false on the API because its worker does the polling; if the worker stops reporting in for three minutes, the web process takes over. The dashboard shows a warning whenever no scheduler has reported in for three minutes. A free web service spins down after 15 minutes without requests, which would stop polling; the API requests its own `/api/health` every 5 minutes (using the `RENDER_EXTERNAL_URL` Render provides) to stay up. A free instance running all month uses about 744 of the 750 free instance hours, so a paid instance is the dependable choice.

### 3. Vercel (frontend)

1. New Project > import the repository > Root Directory: `frontend`.
2. Environment variable `NEXT_PUBLIC_API_URL` = your Render API URL, for example `https://easybid-api.onrender.com`.
3. Deploy, then make sure the final Vercel URL is in `CORS_ORIGINS` on Render.

## Jobs service

### Connect Gmail (once)

1. [Google Cloud console](https://console.cloud.google.com): create a project, then **APIs & Services > Library > Gmail API > Enable**.
2. **OAuth consent screen**: user type External, add your Gmail as a test user, add the scopes `gmail.send` and `gmail.readonly`.
3. **Publish the app** (Publishing status: In production). In Testing status Google expires the connection every 7 days. Without Google's verification you will see an "unverified app" warning when connecting; continue past it, it is your own app.
4. **Credentials > Create credentials > OAuth client ID**, type Web application. Authorised redirect URI: `https://<your-render-api>/api/jobs/gmail/callback` (and `http://localhost:8000/api/jobs/gmail/callback` for local use).
5. On the backend set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` (exactly the URI from step 4) and `APP_URL` (the dashboard URL).
6. Dashboard > Jobs > Settings > **Connect Gmail**.

Only the refresh token is stored, encrypted with a key derived from `SECRET_KEY`. Changing `SECRET_KEY` means connecting Gmail again.

### What protects your personal Gmail

- A daily send limit (default 20), far below Gmail's own.
- Plain-text emails, no tracking pixels, no link shorteners.
- Every recipient is checked before sending: address format, a mail server for the domain, no throwaway inboxes.
- A warning before writing again to an address or company applied to recently.
- Nothing is sent without you pressing Send, and the same email can never go out twice.
- The AI may only claim what is in Jobs > Profile & CVs, and never adds an address that is not in the job description.

## What is checked before a bid

In this order, and everything before the AI steps costs nothing:

1. **Skills**: enough of your skills among the project's tags, none of your blocked skills.
2. **Rules**: budget, age, number of bids, language, excluded keywords.
3. **Account eligibility**: bids left, account not limited, Preferred-Freelancer-only and identity-verification projects only if your account qualifies. Requirements Freelancer reveals only by refusing a bid (such as a minimum account balance) cannot be seen in advance: the bid is tried, and a refusal moves on to the next project.
4. **Selection prompt** (AI), then **proposal prompt** (AI).
5. **Clean-up**: quotation marks, markdown, bullets, tags and preambles are stripped; a proposal with placeholders, contact details or the wrong length is rewritten once and otherwise rejected. The same check runs again on hand-edited text before sending.

A refused bid never stops EasyBid: the proposal is marked failed and the run moves on to the next project. Five refusals in a row hold bidding off for 15 minutes, after which it carries on by itself. Once the daily bid cap is reached, nothing is fetched or written until the cap resets at 00:00 UTC.

## Notes

- The Freelancer API does not return the client's details (payment verification, rating, country) for this kind of token, so rules cannot filter on the client.
- Budget minimums and your hourly rate are set in USD. Project budgets are converted with Freelancer's exchange rate; bids are placed in the project's currency.
- A bid request is never retried automatically. If the outcome is unknown the proposal is marked failed with a note to check Freelancer first.
- Freelancer allows 1,000 API requests per hour per token. Polling every 60 seconds uses about 60.
