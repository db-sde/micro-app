# Extraction eval: v1 vs v2

Compares v1 (as published today) and v2 with Sonnet 5.5 (Opus is not used; earlier reports include it), field by field, against WordPress pages the team has corrected. Plan and design: `../../EXTRACTION_V2_PLAN.md` §5.

Documents, truth, the response cache and reports stay out of git (`.gitignore`): they are real page content.

## 1. Add a case

```bash
cd backend
.venv/bin/python -c "from evals.cases import new_case; new_case('jamia-mba', '/path/Copy of Jamia Islamia Online MBA program.docx', 'course', post_id=1234)"
```

Then edit `evals/cases/jamia-mba/case.json`: `split` (`dev` or `holdout`), fields to ignore, your corrections (`truth_overrides`) and stress `checks` (see `evals/cases.py` for every check type).

## 2. Fetch the truth (read-only)

```bash
.venv/bin/python -m evals.fetch_truth jamia-mba        # GET ?context=edit, so drafts work
.venv/bin/python -m evals.fetch_truth --all
.venv/bin/python -m evals.fetch_truth jamia-mba --from-export post.json
```

## 3. Estimate, then run

```bash
env -u ANTHROPIC_BASE_URL .venv/bin/python -m evals.run_eval --estimate-only
env -u ANTHROPIC_BASE_URL .venv/bin/python -m evals.run_eval --yes --budget 30
env -u ANTHROPIC_BASE_URL .venv/bin/python -m evals.run_eval --offline        # re-score from cache, free
```

- Every response is cached by its exact request. Re-running after changing checks, derivations or scoring costs nothing; changing the prompt or a field description makes new calls.
- Uncached calls need `--yes` and stop at `--budget` (default $25).
- The run refuses to start with `ANTHROPIC_BASE_URL` or chatbot settings in the environment. The database is in-memory and WordPress is a fake (`evals/projection.py`), so nothing is written anywhere.

## What gets scored

Each pipeline's payload goes through the real `publish_payload` against the fake site, and the ACF body it would send is compared with the corrected post:

| variant | meaning |
|---|---|
| `v1/published` | v1 exactly as /publish sends it today (the baseline) |
| `v1/raw` | v1 with the publish-time repairs off (for reference) |
| `v2-*/raw` | v2 with the publish-time repairs off: what the extraction itself got right |
| `v2-*/published` | v2 as it would actually be published |

Short fields: normalized exact match (currency/format-only differences are a match). HTML: word F1 ≥ 0.85. Repeaters: row matching on the key sub-field, then per-sub-field accuracy. SEO/hero texts are generated, so they are not scored against truth. Every variant also gets the truth-free page checks (headings, fees, admission, placeholders, grounding…) and the case's stress checks.

Output: `evals/reports/<timestamp>/report.md` and `results.json`.
