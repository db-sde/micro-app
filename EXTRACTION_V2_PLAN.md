# Extraction v2 — plan

Status (2026-10-24): **v2 is the default pipeline in production** (`EXTRACTION_PIPELINE` unset = v2; `v1` is a rollback). Earlier status (2026-10-23): **steps 1–4 built and tested with mocks** (§6: Docling spike, schema/guide/checks/derive, extraction + generation + switch + flag badges, eval harness in `backend/evals/`, see its README). No paid call has run yet. Next: load the real documents and post IDs, run the free estimate, then paid runs after you approve it. v1 stays the default (`EXTRACTION_PIPELINE=v1`).

## 0. What I checked before planning

| Check | Result |
|---|---|
| Git remotes | `origin` and `db-sde` existed, removed at your request. No remotes now. |
| Chatbot sync | `CHATBOT_BASE_URL` / `CHATBOT_CATALOG_WEBHOOK_SECRET` not set in `backend/.env` or the shell. Sync is disabled. |
| Database | `DATABASE_URL` in this copy is `postgresql://…@localhost:5432/degreebaba` (no server running), so the app falls back to the local `backend/degreebaba.db` SQLite file. No live DB is reachable from this copy. The eval will use its own in-memory SQLite anyway. |
| `ANTHROPIC_BASE_URL` | **Set in the shell environment** this session runs in. The SDK reads it, so paid eval runs are started with it unset (`env -u ANTHROPIC_BASE_URL …`). |
| Baseline | `pytest`: 334 passed, 1 xfailed. `ruff`: clean. `npm test`: 10/10. |
| SDK | Installed `anthropic==0.105.2` already supports `output_config.format` (structured outputs), `thinking={"type":"adaptive"}`, streaming and `betas`. Latest is 2.1.0. |
| Docling | `docling-slim[format-docx]` 2.142.1 = `docling-core` + `python-docx`. No torch, OCR or ML models. Install size and memory still to be measured. |
| Live schema | Unauthenticated `OPTIONS /wp-json/wp/v2/{type}` works: 46 / 62 / 58 ACF fields (university / course / specialization). |
| Published posts | Only **12** are public: 1 university (Shoolini), 1 course (Online BCA), 10 specialization. The corrected course pages are presumably drafts. |
| Source docs | No `.docx` in this copy (the local DB holds 107 old v1 payloads only). |

Read: `service.py`, `extractor.py`, `enricher.py`, `kv_parser.py`, `classifier.py`, `page_detector.py`, `formatter.py`, `validator.py`, `docx_parser.py` (structure, heading detection), `acf/fields.py`, `wordpress_client.py` (polish, extras, fee remap, `publish_payload`), `main.py` (`/upload`, `/confirm`, `/history`, `/stats`, `/schema`), the three spec test files and `test_history_api.py`, and `ValidationScreen.jsx` / `MappingScreen.jsx`.

## 1. How v2 plugs in

```
run_extraction_pipeline(file_bytes, filename, forced_page_type, db)
  ├─ EXTRACTION_PIPELINE=v1 → the older pipeline (rollback only)
  └─ EXTRACTION_PIPELINE=v2 (default) → pipeline/v2/run.py:run_v2(...)
        1 docx → Markdown (Docling .docx backend; fallback: docx_parser)
        2 page type (forced, else existing detect_page_type)
        3 schema + field guide for that page type (snapshot of live WP + fields.py)
        4 ONE streaming Claude call → JSON (structured output)
        5 deterministic table maths (spec-wise fees, range, other_specs fees)
        6 thin validation → flags
        7 SEO / meta / hero / programs_intro from the final values
        8 usage, cost and latency logged
  └─ shared tail (both pipelines): validate_payload → build_json_output → persist Upload + FieldMapping → same response shape
```

The setting is read on each call, so tests and the eval can switch it. The response keeps today's keys (`upload_id, filename, page_type, payload, validation, field_mappings, processing_time_ms`). v2 adds optional `pipeline: "v2"` and `usage`. The v2 `field_mappings` rows are `{field_key, heading_in_doc, confidence, status, source:"LLM"}`; the stored row also keeps `value`, so `/confirm` (Fix Mappings) keeps working.

Every new endpoint or helper that blocks stays a plain `def`.

## 2. Files

**New: `backend/pipeline/v2/`**

| File | Purpose |
|---|---|
| `markdown.py` | Docling `DocumentConverter(allowed_formats=[DOCX])` → Markdown with heading levels, ordered/unordered/nested lists, and full tables (header + every row). Keeps `[field_name]` / `[a,b,c]` tags and `Linked_university` / `Linked_course` lines verbatim (I'll check Docling doesn't escape `[` `_`, and render from its items if it does). Also returns a plain `tables` list for the table maths. **Admission rule (UPES):** a bold "Step N. Title:" line is a list item of the current section, never a new heading. v1 loses UPES steps because `docx_parser._is_heading` treats short all-bold lines as headings. Fallback: on any Docling error, render `docx_parser` output as Markdown, with `parser="fallback"` recorded in meta. Docling is imported lazily, so app startup is unaffected. |
| `schema.py` | Builds the per-page-type JSON Schema from `acf/wp_schema/{type}.json` (committed OPTIONS snapshot, including repeater sub-fields) merged with `acf/fields.py`. `python -m pipeline.v2.schema --refresh` re-fetches OPTIONS (read-only) and writes a fresh snapshot. Every field is required and nullable. Repeater rows are objects with their sub-fields. Each field is wrapped as `{value, source_heading, confidence: "high"/"medium"/"low"}`. |
| `field_guide.py` | One short line per field saying **what it is on the page**, built from your spec. Examples: "paragraph shown above the year/semester syllabus accordion"; "one short note under the admission steps, never one of the steps"; "section heading: short, never a sentence, fee or table row"; formats learned from published posts (`specialization_lowest_emi_strats_from` like `10,156`; `other_spec_fee` like `INR 82,300/-`; `examination_process` title/description rows). Used by the prompt and printed in the eval report. |
| `extract.py` | The one call: `client.beta.messages.stream(model=…, max_tokens=64000, thinking={"type":"adaptive"}, output_config={"effort":"high","format":{"type":"json_schema",…}}, …).get_final_message()`. A cached system block holds the rules, schema and field guide. The user turn holds the page type, document title and full Markdown. Rules in the prompt: never invent (null when absent), no placeholders, headings are headings, note ≠ steps, complete repeaters, entity name from the title, return the source heading per field. Handles `stop_reason` `refusal` / `max_tokens` explicitly. Server-side refusal fallback is on by default (`fallbacks:"default"`, beta `server-side-fallback-2026-07-01`). On 0.105.2 the typed signature lacks `fallbacks`, so it goes through the SDK's `extra_body`. Very large docs (above ~300k tokens, unlikely with a 1M context) are split by top-level section, and every chunk keeps the title and the field list. Models: `claude-opus-5-5` by default, `claude-sonnet-5-5` selectable (`V2_MODEL`). |
| `derive.py` | Pure table maths on v2's tables: spec-wise fee table → `specialization` rows, `course_amount_range`, `other_specs` fees and the "All Specializations" shared fee, and `total_fee` when it has no digits. Done by factoring `collect_specialization_fees` / `_derive_specialization_fees` to accept a table list; the v1 signatures stay as thin wrappers, so v1 behaviour and its tests don't change. Fee tiers stay in the publish layer (`_remap_fee_plans`), unchanged. |
| `checks.py` | Validation that flags, never guesses: heading ≤90 chars with no amount and not a sentence; money fields contain an amount; `admission_fee_note` ≠ any step; no placeholders (`N/A`, `NA`, `nil`, `-`, `not available` → null + flag); HTML doesn't start with its own heading; repeater rows have required sub-fields; **completeness** (rows vs source table rows, semesters/subjects vs Markdown counts); `spec_name` matches the title; **grounding** (each value's numbers and key phrases appear in the Markdown). Flags go into `validation.field_report[i].flags` and `summary.flagged`. Confidence = model level, lowered by flags. |
| `generate.py` | `seo_title`, `meta_description`, hero texts and `programs_intro`, written after names and values are final (structured output, same model setting). |
| `run.py` | `run_v2(...)` → `(payload, mapping_records, flags, meta)`; logs `response.usage`, cost and latency per document. |

**Changed (small)**

| File | Change |
|---|---|
| `pipeline/service.py` | Branch on `EXTRACTION_PIPELINE`. The persistence and response tail moves into a shared helper, unchanged for v1. |
| `pipeline/validator.py` | Optional `flags` argument. Without it the output is byte-identical to today. |
| `acf/fields.py` | New registries used only by v2: `V2_PUBLISHED_FIELDS` (live WP fields v1 never sends, see §4) and `V2_UNPUBLISHED_FIELDS` (`eligibility_intro`, `fee_intro`, `accreditations_intro`, course `jobs_intro`). `ACF_FIELDS` and `get_valid_field_keys` stay unchanged, so v1 validation, tags and embeddings are untouched. Faculty `member_program` / `member_qualification` are already extracted separately and merged at publish, and v2 keeps that. |
| `pipeline/wordpress_client.py` | **Needs your OK.** One line so v2's directly extracted WP fields pass the publish key filter: `valid_keys = get_valid_field_keys(pt) \| V2_PUBLISHED_FIELDS[pt]`. v1 never produces those keys, so v1 publishes are unchanged. `_syllabus_extras` / `_placement_extras` already fill only empty fields, so v2 values win. Unpublished intro keys keep being dropped (logged). |
| `requirements.txt` | `docling-slim[format-docx]==2.142.1`, pinned after measuring install size and peak memory in a scratch venv (Render). |
| Frontend | Validation and Mapping screens show a ⚠ badge with the flag text as a tooltip, plus an `LLM` source colour. Logic goes in a small `.mjs` helper with node tests. No flow changes. |

**Tests (all mocked: no Anthropic, OpenAI or WordPress calls)**
- Markdown: fixture `.docx` files built in-test with python-docx (headings, nested lists, tables, tags, bold "Step N." lines, the UPES shape), plus the Docling-failure fallback.
- Schema: built from the committed snapshot; repeater sub-fields; every field has a guide line.
- Extract: fake streaming client returns canned JSON; refusal, `max_tokens`, split and merge paths; request params asserted (model, adaptive thinking, structured output, fallbacks).
- One test per spec item (§3) running checks + derive on canned model output.
- Service: v1/v2 switch, unchanged response shape, `/upload` stays sync `def`.

## 3. Spec items v2 must meet at extraction time (each one is an eval check)

Names from the title (`_TITLE_KEYS`, `specialization_from_title`). SEO and hero written after the name is final. Headings ≤90 chars, never a sentence, fee or row; fallback "<page name> <Label>"; only empty headings auto-filled; HTML never starts with its own heading. Placeholders → null. Admission: one ordered list; "Step N" paragraphs → `<ol>`; **bold "Step N. Title:" lines stay inside the admission section, each as `<li><strong>Step 1. Ensure your eligibility:</strong> Students are required to…</li>`**; text after the last step ("Additional information: …", "Important instructions") → `admission_fee_note`, never steps 7/8, and never a copy of a step. `eligibility_summary` is a clean sentence. Fees: rows only with amounts, no EMI plan; lowest Total → `total_fee`; repeated plan names carry their column. Spec-wise table → `specialization` rows / range / `other_specs` fees, with "All Specializations" handled as specified, or names from a "<Program> Specializations" list. Syllabus: intro → `*_syllabus_description` + section heading; academic years complete (Jamia 8/8/11/9). Jobs: `jobs_content` intro + `job_profiles` rows. Partners from lead-in lines or inline "include A, B, C, etc.", no invented placement guarantee. Repeaters complete (MIT SDE 5 programs).

## 4. Live schema vs our registry (new findings)

- **Live fields nobody sends:** specialization `specialization_lowest_emi_strats_from` (filled by hand on 4/10 published posts), `examination_process` repeater (9/10 by hand), `best_price_specialization`, `duration_specialization`, `about_info`; course `best_price_value`, `course_intake` (date), `popularity_score` (number), `partner_banks_course`; university `examination_cards` repeater, `emi_interest_rate_value`, `placement_highlights`, `partner_banks_names`; repeater sub-fields `specialization_icon`, `eligibility_icon`. v2 extracts the text ones that a doc can contain, after the WP team confirms what each holds.
- **Sent but not live:** fee-tier totals `semester_plan_amount_total`, `annual_plan_amount_total`, `one-time_payment_amount_total` (course) and `semester_plan_total`, `annual_plan_total`, `one-time_payment_savings` (specialization). `_remap_fee_plans` sends them whenever `plan_total` is set, and WordPress ignores them. This goes on the WP team list rather than into a code change here (publish layer).
- On all 10 published specialization posts, `hiring_partners_specialization` and `jobs_content` are empty (probably published before those fixes).
- Partner format: your spec says an HTML `<ul>` of names. The current code and tests send `"IBM, KPMG, …"` to the partner field and put the `<ul>` in `placement_content`. v2 follows the current code until the WP team confirms what the theme renders.
- v1 detail: the enricher defaults `admission_fee_note` to `"N/A"`, which `_polish_for_wordpress` then removes. v2 never writes placeholders.
- `_polish_for_wordpress` strips the first heading of every HTML field. For `syllabus_content` that opens with `<h3>Year I</h3>`, that removes the year heading, not a repeated section heading. It matters only if the theme shows `syllabus_content` (the accordion uses `course_academic_years`). To confirm with the WP team; the publish layer is unchanged.

## 5. Evaluation

**Layout:** `backend/evals/` (outside `tests/`; documents and truth are git-ignored)
```
evals/cases/<case_id>/doc.docx
                    truth.json      # WordPress key space (what the page should hold)
                    checks.yaml     # required phrases, counts, stress assertions
evals/fetch_truth.py                 # GET a post's acf by ID (read-only) or import an export
evals/run_eval.py --pipelines v1,v2-opus,v2-sonnet --cases …
evals/reports/<timestamp>/{report.md, results.json}
```

**Fair comparison in WordPress key space.** Truth comes from corrected WP posts, so each pipeline's payload is projected through the real, unmodified `publish_payload` against an in-memory fake WordPress (`httpx.MockTransport`, fake site URL, no network). The ACF body it would have sent is what gets scored.
- **v1:** as published (all patches on). This is the baseline you asked for.
- **v2 "raw":** `_polish_for_wordpress`, `_syllabus_extras` and `_placement_extras` swapped for no-ops in the eval only. This is the score that proves extraction-time correctness and decides whether enricher guesswork can be deleted.
- **v2 "as published":** patches on, which shows what would actually reach WordPress.

**Scoring per field**
- Short fields: normalized exact match (case, whitespace, currency `₹`/`INR`/`/-` → amount + unit).
- HTML/textarea: tag-stripped token similarity (pass ≥ 0.85) + required phrases + structure (`<ol>` item count, no leading heading).
- Repeaters: rows aligned on the key sub-field; row precision/recall and per-sub-field accuracy; complete-list check.
- Null handling: value where truth is null = *invented*; null where truth has a value = *missed*.
- Truth-free invariants (§3) run on every doc, even before truth is ready.

**Report** (`report.md`): per-field accuracy table for the three pipelines; failures grouped by the categories in §3 (names, headings, placeholders, admission, eligibility, fees, spec-wise fees, syllabus, jobs/placement, repeaters, grounding) with the actual vs expected values; tokens, cost and latency per doc (v1 counted through wrapped Haiku/OpenAI clients).

**Cases:** Course first (Shoolini with/without PAP + "All Specializations", Jamia syllabus, OP Jindal admission + alumni partners, Sharda spec-wise range), then Specialization (Shoolini Retail Management, Jain MCA DevOps), then University (UPES lost steps, MIT SDE 5 programs). A few docs are held out from prompt iteration so the final report isn't tuned to its own test set.

**Cost control:** raw model outputs are cached by (doc hash, model, prompt version), so changes to checks and scoring never re-spend. Before any paid run I'll run `count_tokens` on the real docs and send you the measured estimate.

**Rough estimate until measured:** per doc ≈ 30k input + 15–30k output/thinking tokens.

| Pipeline | Per doc |
|---|---|
| v2-Opus 5.5 ($4/$20) | ~$0.45–0.75 |
| v2-Sonnet 5.5 ($2/$10) | ~$0.25–0.40 |
| v1 (Haiku 4.5 per-field calls + OpenAI embeddings) | ~$0.10–0.20 |

One full 15-doc run of all three costs about $12–20; ~5 prompt iterations on v2 only add about $40–60. **Total ≈ $60–90.** Nothing paid runs without your go-ahead.

## 6. Order of work

1. Docling spike: install size, peak memory, and Markdown quality on your docs (UPES admission first). No API cost.
2. Schema snapshot + field guide + `checks.py` + `derive.py`, with tests.
3. `extract.py` / `generate.py` / `run.py` + the service switch, with mocked tests; then the frontend flag badge.
4. Eval harness + truth import; truth-free invariants on v1 right away (free).
5. Paid runs after your approval of the measured estimate → iterate prompt, guide and checks → comparison report.
6. WordPress team list (§4 + your items) as its own document.
7. You decide on making v2 the default; then delete only the enricher rules the v2-raw scores show are no longer needed.

## 6a. Docling spike results (2026-10-23, synthetic stress document)

Run on a python-docx document with the real docs' shapes: title line, `[tag]` headings, `Linked_*` lines, a Quick-facts block, bold "Step N. Title:" admission lines (description in the same paragraph and in the next one; one with 14 pt bold), numbered + nested lists, a with/without-PAP spec-wise fee table with an "All Specializations" row, a merged-cell Year/Semester table with multi-line cells, a lead-in partner list, FAQs. **The real documents still need to go through it** (UPES first).

| Question | Result |
|---|---|
| Install | `docling-slim[format-docx]==2.142.1`: +~200 MB in a fresh venv (pandas 80 MB, numpy 35, lxml 20, Pillow 13, docling 10). numpy, lxml and python-docx are already backend dependencies. **Resolves with the backend's exact pins** (numpy stays 2.4.6). No torch, OCR or models. |
| Memory | +83 MB RSS on import (measured after numpy/lxml/docx/pydantic were already loaded). Over 200 conversions RSS stays flat or drops (130 → 75 MB), with no growth. |
| Time | Import 2 s warm (8.6 s on the very first run while bytecode compiles). Conversion ~0.03 s per doc. Imported lazily on the first v2 upload. |
| Bold "Step N. Title:" lines | **Stay inside the admission section** as `**Step 1. Ensure your eligibility:** Students are required…`. Only Word heading styles become headings, so the UPES failure mode can't happen in v2's Markdown. A bold pseudo-heading written as a real section title also stays a bold line, which the model reads in context. |
| Lists | Ordered, unordered and nested (indented `-` under `2.`) are preserved. Numbering continues across separate lists that share one Word numbering definition, exactly as Word shows them. |
| Tables | Header row and every row are kept. Merged header cells repeat (`Year I \| Year I`), which is harmless. |
| Needed fixes (all verified) | (1) Export with `escape_underscores=False`, otherwise `[about_heading]` becomes `[about\_heading]` and `Linked_university` becomes `Linked\_university`. (2) `escape_html=False`, otherwise `Larsen & Toubro` becomes `Larsen &amp; Toubro`. (3) Rewrite `\n` inside table cells as `<br>` before export, otherwise multi-line cells merge ("Management Concepts Accounting for Managers"), which would break semester subject counts. |

## 7. Decisions (approved 2026-10-23)

1. **Eval data:** you'll send the `.docx` files and post IDs. Draft posts may be read with REST GET using the app's WordPress credentials.
2. **Publish filter:** the one-line `wordpress_client.py` change in §2 is approved.
3. **SDK:** stay on `anthropic==0.105.2`; `fallbacks` goes through `extra_body`.
4. **Model (2026-10-24):** Sonnet 5.5 is the default v2 model; Opus 5.5 stays selectable (`V2_MODEL=claude-opus-5-5`). On 20 documents: checks 99% vs 100%, $0.089 vs $0.222 per document, 33 s vs 62 s. To confirm with prompt v2.5: re-run Sonnet on all 25 documents once the API credit is topped up.
