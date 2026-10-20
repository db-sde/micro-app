# Parser → chatbot catalog sync

This implements the receiver's schema version 1 from `Chatbot DB/CATALOG_SYNC.md`,
`backend/catalog/schema.py` and `backend/catalog/routes.py`. No deployment or live
WordPress/chatbot calls are part of implementation or tests.

## Configure and activate

1. Back up the parser database. Deploy the receiver's catalog migration/code first.
2. Configure a **single WordPress site** per chatbot source. Audit old parser uploads
   against that site before import: historic upload metadata may not record its site.
   Do not mix sites whose WordPress post IDs overlap.
3. Set these **backend environment variables**:
   - `CHATBOT_BASE_URL`: HTTPS origin only, such as `https://chatbot.example.com`.
     Paths, query strings, fragments and credentials are rejected.
   - `CHATBOT_CATALOG_WEBHOOK_SECRET`: a new shared random secret, at least 32
     characters, identical to receiver `CATALOG_WEBHOOK_SECRET`. Keep it separate
     from WordPress credentials, widget keys and chatbot admin auth.
   - `CHATBOT_CATALOG_SOURCE_HOSTS`: exact canonical content hosts, matching receiver
     `CATALOG_SOURCE_HOSTS`; defaults to `degreebaba.com,www.degreebaba.com`.
   - Existing `WORDPRESS_SITE_URL` and publishing credentials remain server-only.
   - `CATALOG_RECOVERY_DIR`: a **private persistent disk directory**, shared by app
     processes, outside `/uploads` and any static/public directory. Its default is
     `backend/catalog-recovery`. Files are created with mode 0600. Back it up with
     the SQL database. An ephemeral deployment disk cannot guarantee journal recovery.
4. Missing either chatbot origin or secret disables delivery. Malformed configured
   values show a safe error. HTTP is allowed only on localhost/127.0.0.1/::1 with
   `APP_ENV=development`; default is production. Canonical content URLs always need
   HTTPS, including local transport tests. Keep clocks synchronized (300-second skew).
5. Start the backend normally. Startup creates the additive tables and starts one
   sender thread per process; a database-wide sender lease bounds HTTP concurrency
   to **one across processes**. No Redis, paid AI, chatbot admin token or frontend
   secrets are required. When catalog sync is configured, a failed PostgreSQL
   connection refuses startup rather than silently creating a second SQLite outbox.
6. Test staging first, then review existing chatbot catalog mappings before initial
   backfill. Using the operator's chatbot admin session, inspect
   `GET /api/admin/catalog/entities?entity_type=university&limit=100&offset=0`
   (also course/specialization; paginate through all rows). Never embed the admin
   bearer token in parser frontend code or runtime sender configuration.

New successful published university/course/specialization publications enqueue
automatically. To adopt a reviewed existing chatbot record **on first publish**,
enter its exact catalog slug in the publish modal and approve the mapping there.
Leave it empty for a new entity; the receiver generates a stable unique slug.
Never derive an adoption slug from a friendly name.

## Operator workflow and backfill

Upload validation and history show independent WordPress and chatbot states:
not configured, not eligible/draft, queued, syncing, synced, superseded, failed.
Warnings and safe errors are visible. Only a receiver `applied` receipt is synced;
202/200 receipt acceptance alone is delivery, not import completion.

In validation, expand the catalog panel to save a **per-post** reviewed catalog slug
or explicit `clear_fields`. Saving removals requires an explicit checkbox; names,
IDs, slugs and relationships cannot be cleared. Removals are consumed by one new
immutable event. Missing/null/empty fields never infer removals. Nonempty repeater
arrays contain the entire reviewed list, replacing that whole receiver repeater.
Editor changes alone do not change a published snapshot: publish reviewed content
corrections to WordPress before sending a corrected snapshot.

For legacy uploads, preview flags the snapshot for review, even when its URL/ID are
already known. Review the original document against the live published page, enter
its existing WordPress post ID in the catalog panel, approve that content review,
and **read WordPress references**. This authenticated, read-only request retrieves
real WordPress ID, canonical URL, status and ACF relationship IDs; it never creates
or updates a WordPress post. It does not enqueue yet, so set the reviewed catalog
slug before pressing retry or starting backfill. On later reconciliations the saved
published snapshot is retained; unpublished editor changes are not sent implicitly.

History → **Preview / dry-run** shows deduplicated local posts, counts, blocked
parents and coverage. It may add local legacy reference rows; it does not allocate
versions, send events or change WordPress. Review mappings/content, then start the
resumable backfill. Membership/event IDs are durable. Repeating a backfill reuses
existing events, including completed/failed ones, without republishing WordPress.
The sender resumes after restarts and applies universities before their courses,
and courses before their specializations. It waits for the **latest** parent
snapshot to apply; specialization university and course university must match.
Missing parents show exact WordPress IDs. Import their original reviewed documents,
link their existing WordPress IDs via reference reconciliation, review adoption
slugs and sync them first. Friendly names never substitute for IDs.

Coverage is **only local saved publications and explicitly reviewed imports**.
This does not crawl WordPress or claim to cover pages absent from the parser.
Deleted uploads retain their publication/outbox audit records; they are not
withdrawn from either WordPress or chatbot by deleting local upload history.

Retry behavior:

- Network failure, 429, 5xx: automatic exponential backoff with jitter (bounded to
  approximately 75 minutes). Manual retry schedules the same event sooner.
- Receiver `queued`: poll with bounded backoff (up to 60 seconds).
- Receipt GET 404: resend the same POST bytes/event/version, then poll again.
- 401: check shared secret, method/path signing and clocks. 409: review version/source
  mapping conflicts. 413: reduce reviewed content. 422: correct schema/canonical
  host/relationships. Redirects are not followed. These stop for operator correction.
- Receiver `failed`: show its safe error. After correction, parser retry creates a
  **new UUID/version**, using the last successfully published snapshot and current
  reviewed mapping/removal settings. Correct page content through WordPress publish
  first. It never alters the old event bytes. An operator may instead use receiver
  admin `POST /api/admin/catalog/events/{event_id}/retry` with their admin session;
  the parser does not store/use that token.
- Receiver `ignored`: mark superseded. Check whether the latest local version was
  confirmed applied; otherwise show an operator reconciliation error. Do not force
  an old snapshot over a newer receiver version.

## Durability, migrations and failure recovery

Startup's idempotent additive catalog migration creates `catalog_lock`,
`catalog_posts`, `catalog_publications`, `catalog_outbox`, `catalog_backfills` and
seeds the singleton lock row. No existing table/column is removed or rewritten.
As with the existing application initialization, run the initial migration with a
single app process before expanding the process count to avoid concurrent DDL.
SQLite and PostgreSQL are supported. Explicit SQLite `DATABASE_URL` is also accepted
for isolated testing/development.

Identity is `(WordPress site, page_type, WordPress post ID)`. A database write/row
lock serializes first insertion and version allocation across uploads/processes.
The SQL transaction saves WordPress references, the original approved content
snapshot, incremented version, UUID and exact serialized UTF-8 request bytes
together. No chatbot HTTP request occurs in the WordPress publishing handler.
Original ACF content is captured before WordPress field renaming/coercion. Media,
relationship routing fields, private `_meta` and unknown non-ACF keys are excluded
from event data. No document binaries or publishing credentials are included.

Each send has a 90-second durable lease, compared with a 20-second HTTP timeout.
An expired lease recovers abandoned sends after restart. Stale sender results cannot
overwrite a newer lease. Versions for the same post are sent in order. POST signs
`/webhook/catalog`; GET signs `/webhook/catalog/{uuid}` with empty bytes. Every
attempt signs a fresh Unix timestamp over method + exact path + stored body bytes.
Body size is capped at 2 MiB before allocating a version. HTTP redirects are terminal
configuration errors. The database pins both WordPress site and chatbot origin;
changing either after activation requires an operator-planned source migration.

Immediately after WordPress success, a private fsynced recovery journal records
only approved content, remote references, operation UUID and reviewed adoption slug.
If the SQL/outbox transaction fails, a second transaction attempts to save the
successful WordPress references and an actionable error. The journal is retained,
and the worker recovers the same operation without another WordPress write. Replay
is idempotent, and older recovered snapshots cannot replace newer publications.
If disk and SQL both fail, the response still reports WordPress success and its
real post ID: repair storage, then reconcile that ID; **do not republish**. A process
crash between remote WordPress success and recording its result also needs read-only
operator reconciliation; WordPress and local storage cannot commit atomically.

Rollback: remove chatbot variables and restart to stop new delivery; retain SQL
catalog tables, counters, immutable events and private journal files. Do not reset
version counters or delete the source binding to switch unrelated sites. Imported
receiver data and accepted receiver jobs persist after parser rollback. Back up both
apps before initial imports. Dropping these additive tables is data-destructive
and is not an automatic downgrade migration.

## Contract boundaries

Published upserts only. Draft/private/deleted WordPress changes do **not** withdraw
existing chatbot knowledge; UI flags operator action and pending local delivery is
stopped for known nonpublished posts. A receipt already accepted by the receiver
may still apply. Direct WordPress edits are not observed automatically. Blogs and
category pages are excluded. Automatic withdrawal/deletion or continuous WordPress
reconciliation needs a coordinated receiver extension before such a workflow goes
live.

These new operator endpoints inherit this app's existing access model. Deploy the
parser behind the same operator-only authentication/access boundary as WordPress
publishing; do not expose operator mutation endpoints to anonymous public traffic.
Webhook secret authentication protects the receiver, not the parser's operator UI.

## Local validation

Run `pytest -q backend/tests`, `ruff check backend`, `npm test --prefix frontend`,
and `npm run build --prefix frontend`. Tests scrub credentials before collection-time
imports, use disposable SQLite databases, permit only in-process TestClient HTTP,
and mock all external HTTP. The startup/shutdown lifecycle test uses the isolated database and mocks embedding
initialization. No external embedding, WordPress/chatbot deployment, or paid AI call
is made. SQL locking is exercised concurrently
on SQLite; PostgreSQL uses a row UPDATE lock but must additionally be exercised on
a disposable staging PostgreSQL deployment before activation at scale.
