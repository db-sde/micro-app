# DegreeBaba Content Publisher

An end-to-end document parser and WP ACF field mapping system. It extracts structured information from Word documents (`.docx`), resolves field mappings using embeddings and AI, validates the payload quality, and exports ready-to-use WordPress ACF payload JSONs.

---

## Architecture Overview

- **Backend:** FastAPI application utilizing SQLAlchemy, PostgreSQL (Neon database integration), OpenAI, and Anthropic APIs. Background bulk processing runs using FastAPI's native `BackgroundTasks` (completely decoupled from Redis/Celery).
- **Frontend:** React SPA built with Vite and vanilla CSS styling.

---

## Getting Started

### 1. Prerequisites
- Python 3.10+
- Node.js 18+
- Active internet connection (for Neon DB and LLM APIs)

---

### 2. Backend Setup & Run

1. Navigate to the backend directory:
   ```bash
   cd backend
   ```

2. Create a configuration file `.env` by copying the example template:
   ```bash
   cp .env.example .env
   ```

3. Open `.env` and fill in the required credentials:
   ```env
   OPENAI_API_KEY=your_openai_api_key
   ANTHROPIC_API_KEY=your_anthropic_api_key
   DATABASE_URL=postgresql://neondb_owner:... (your Neon Postgres URI)
   FRONTEND_URL=http://localhost:5173
   ```

4. Create and activate a Python virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

5. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

6. Start the FastAPI development server:
   ```bash
   python3 main.py
   ```
   The API will be available at `http://localhost:8000`.

---

### 3. Frontend Setup & Run

1. Navigate to the frontend directory:
   ```bash
   cd ../frontend
   ```

2. Create a configuration file `.env` by copying the example template:
   ```bash
   cp .env.example .env
   ```

3. Open `.env` and verify the backend API base URL variable:
   ```env
   VITE_API_BASE=http://localhost:8000
   ```

4. Install the required Node packages:
   ```bash
   npm install
   ```

5. Start the frontend Vite development server:
   ```bash
   npm run dev
   ```
   Open your browser and navigate to the printed address (default: `http://localhost:5173`).

---

## APIs & Endpoints Reference

The backend exposes the following endpoints (relative to `http://localhost:8000`):

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/upload` | `POST` | Upload a single `.docx` file and run the full pipeline |
| `/upload-blog` | `POST` | Upload a `.docx` file for a blog/category page and get a 4-5 point summary |
| `/upload/{upload_id}` | `GET` | Fetch an upload's full payload, validation report, and field mappings |
| `/confirm/{upload_id}` | `POST` | Update field mapping overrides and trigger validation recalculation |
| `/payload/{upload_id}` | `PATCH` | Overwrite the ACF payload with manually-edited JSON (from the JSON editor) and re-validate; can also reclassify the page type |
| `/download/{upload_id}` | `GET` | Fetch the final WordPress ACF JSON payload |
| `/bulk` | `POST` | Upload a `.zip` containing multiple `.docx` files to process in the background |
| `/bulk/{job_id}/progress` | `GET` | Query progress/results status of a bulk upload job |
| `/history` | `GET` | List metadata of all past uploads (paginated) |
| `/history/{upload_id}` | `DELETE` | Delete an upload record and its associated field mappings |
| `/upload-image` | `POST` | Upload an image for a slot (`hero_image`/`certificate_image`); pushes it to Cloudinary (local-disk fallback) and stores the resulting URL directly on that ACF field |
| `/publish/{upload_id}` | `POST` | Publish an upload's ACF JSON payload to WordPress as a post of the matching CPT (`draft` by default); re-publishing updates the same post |
| `/parse` | `POST` | Debug endpoint to return raw document parse output only |
| `/health` | `GET` | Service health status ping |

### Image storage setup (Cloudinary)

Add this to `backend/.env` (see `.env.example`) — copy it directly from the Cloudinary console's "Product Environment Credentials" panel:

```env
CLOUDINARY_URL=cloudinary://your_api_key:your_api_secret@your_cloud_name
```

`/upload-image` pushes the file to Cloudinary and stores the resulting HTTPS URL directly on the ACF field — WordPress never hosts the image itself. Without `CLOUDINARY_URL` set, uploads fall back to local disk (dev/testing only — that URL won't be reachable once published elsewhere).

### WordPress publishing setup

Add these to `backend/.env` (see `.env.example`):

```env
WORDPRESS_SITE_URL=https://your-wordpress-site.com
WORDPRESS_APP_USER=your_wp_username
WORDPRESS_APP_PASSWORD=xxxx xxxx xxxx xxxx xxxx xxxx
```

Generate the Application Password under **WP Admin → Users → Profile → Application Passwords**. `/publish` assumes ACF fields are exposed over the REST API (ACF PRO 5.11+ with "Show in REST API" enabled per field group, or the ACF to REST API plugin) and that each page type (`university`/`course`/`specialization`) maps to a same-named custom post type — override per-type via `WORDPRESS_POST_TYPE_UNIVERSITY` / `_COURSE` / `_SPECIALIZATION` if your CPT slugs differ.

**Behavior worth knowing about**, all implemented in `pipeline/wordpress_client.py`:
- New posts are created in two requests (title/status, then a follow-up update with the `acf` data) — including `acf` in the same request that creates the post silently drops the field data on some WordPress/ACF setups. Updating an already-published post works fine in one request.
- `hero_image` has no ACF field on any page type — it's side-loaded to the WordPress media library and set as the post's native **Featured Image** instead.
- Our internal extraction schema (`acf/fields.py`) doesn't necessarily match your WordPress field group's real field *names* one-for-one. `_PUBLISH_FIELD_RENAMES` / `_PUBLISH_FIELD_DROP` / `_repeater_to_html_list` / `_remap_fee_plans` in `wordpress_client.py` reconcile the two — if you add or rename fields in WordPress's ACF field groups, check whether one of these needs a matching update, or `/publish` will drop that field (logged as a warning, not an error) rather than send something WordPress will reject.

---

## Testing & CI

### Running the checks locally

```bash
cd backend
pip install -r requirements-dev.txt
pytest            # unit + API tests
ruff check .      # lint
```

```bash
cd frontend
npm ci && npm run build   # the same build Vercel runs
```

### What the suite covers

The tests target the parts of the pipeline that have actually broken in
production — schema drift and publish-time reconciliation — rather than
chasing a coverage number:

| Area | File | Why it exists |
|---|---|---|
| ACF schema invariants | `tests/test_acf_fields.py` | `acf/fields.py` is the source of truth; a duplicate key or a repeater with no sub-fields surfaces as an opaque WordPress 400. |
| KV fast path | `tests/test_kv_parser.py` | Patterns are ordered and first-match-wins, so an over-greedy one silently swallows another field's line. |
| Relationship hints | `tests/test_formatter.py` | `linked_*` must stay null in the payload while the document's stated name survives in `_meta` for publish-time resolution. |
| Heading classifier | `tests/test_classifier.py` | Tag→field routing, including heading/content pairing whose target field name differs per page type. |
| Publish reconciliation | `tests/test_wordpress_client.py` | Field renames/drops, fee-tier mapping, post-title caching, and relationship matching — all without network access. |
| Enrichment helpers | `tests/test_enricher.py` | Derived values (duration, fees, syllabus year/semester structure) that reach the page verbatim. |
| Validation & scoring | `tests/test_validator.py` | Status semantics behind the quality score shown in the UI. |
| HTTP contract | `tests/test_api.py` | Health probe, the `/schema` endpoint the frontend depends on, and input validation. |

**Safety:** `backend/.env` holds live WordPress and Cloudinary
credentials, and every pipeline module calls `load_dotenv()` at import.
`tests/conftest.py` therefore blanks those variables for the whole
session and replaces httpx's transport with a raiser, so an un-mocked
network call fails the test instead of publishing to the production site.
Tests never write to the local dev database.

### Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request:

- **backend** — ruff, pytest with coverage, and a real import of the ASGI app (catches import-time breakage unit tests can miss).
- **frontend** — `npm ci && npm run build`, the same command Vercel runs.
- **hygiene** — fails if an `.env` file, `__pycache__`, or `node_modules` is ever committed, and checks the two requirements manifests stay linked.
- **ci** — an aggregate job to point branch protection at.

### Deployment

Render (backend) and Vercel (frontend) currently **auto-deploy on push**,
so CI is advisory: a red build still ships. To make deploys gated, turn
off auto-deploy on both and add the deploy-hook secrets described at the
top of `.github/workflows/deploy.yml` — that workflow only runs after CI
succeeds on `main`, and skips cleanly while the secrets are unset. Set
the `BACKEND_URL` repository variable to also get a post-deploy health
check.

---

## Development Notes

- **Database:** Uses PostgreSQL (integrated with Neon Serverless Postgres). Tables are automatically created/synced at backend startup via SQLAlchemy..
- **Background Workers:** Bulk zip files are processed sequentially in-process via FastAPI's `BackgroundTasks` helper. No Redis server or Celery worker execution is needed.
- **Frontend SPA routing on Vercel:** `frontend/vercel.json` rewrites every path to `index.html` so client-side routes (e.g. `/upload/123/validation`) work on a direct load or page refresh, not just via in-app navigation. If you redeploy the frontend somewhere other than Vercel, make sure that host has an equivalent SPA fallback rule.

## Chatbot catalog integration

Optional durable parser-to-chatbot sync, per-post mapping/status, safe retry and
resumable backfill are documented in [CATALOG_SYNC.md](CATALOG_SYNC.md).
Delivery is disabled until the server-only chatbot origin and shared secret are set.
