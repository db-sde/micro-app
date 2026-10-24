"""The eval harness (backend/evals): scoring, the fake-WordPress projection,
the caching / budget-capped clients, truth fetching, and a full run of
run_eval on a temporary case. No network: fake model clients, an
in-memory fake WordPress, temporary directories.
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from evals import scoring
from evals.cases import load_cases, new_case
from evals.clients import BudgetExceeded, CachingAnthropic, Ledger, OfflineMiss, ResponseCache
from tests.conftest import FakeResponse
from tests.v2_helpers import UPES_STEPS_HTML, FakeAnthropic, message, standard_client, upes_course_docx

# ── scoring ──

@pytest.mark.parametrize("pred,truth,ok", [
    ("INR 1,30,000 /-", "₹1,30,000", True),
    ("INR 1,30,000/-", "INR 1,30,000 /-", True),
    ("2 Years", "2 years", True),
    ("INR 25,000", "INR 30,000", False),
    ("Fintech & AI", "DevOps", False),
])
def test_short_fields(pred, truth, ok) -> None:
    assert (scoring.short_score(pred, truth) >= scoring.SHORT_PASS) is ok


def test_html_fields_use_word_f1() -> None:
    assert scoring.score_value("<p>UPES offers an online MBA.</p>", "<p>UPES offers an MBA online.</p>")["passed"]
    assert not scoring.score_value("<p>UPES offers an MBA.</p><p>" + "x " * 40 + "</p>", "<p>" + "y " * 60 + "</p>")["passed"]


def test_repeaters_match_rows_and_sub_fields() -> None:
    truth = [{"plan_name": "Semester Plan", "plan_amount": "INR 45,000"}, {"plan_name": "Total Fee", "plan_amount": "INR 1,80,000"}]
    exact = [{"plan_name": "Semester plan", "plan_amount": "INR 45,000 /-"}, {"plan_name": "Total Fee", "plan_amount": "₹1,80,000"}]
    assert scoring.score_value(exact, truth)["passed"]
    short = scoring.score_value(exact[:1], truth)
    assert short["status"] == "mismatch" and short["detail"]["missing_rows"] == ["Total Fee"]
    wrong_amount = [exact[0], {"plan_name": "Total Fee", "plan_amount": "INR 90,000"}]
    assert scoring.score_value(wrong_amount, truth)["detail"]["subfield_accuracy"] == 0.5


def test_nested_semesters_are_scored_too() -> None:
    truth = [{"course_year_title": "Year I", "course_semesters": [
        {"course_semester_title": "Semester I", "course_semester_subjects": "<ul><li>A</li><li>B</li></ul>"}]}]
    pred = [{"course_year_title": "Year I", "course_semesters": [
        {"course_semester_title": "Semester I", "course_semester_subjects": "<ul><li>A</li></ul>"}]}]
    assert scoring.score_value(truth, truth)["passed"]
    assert not scoring.score_value(pred, truth)["passed"]


def test_statuses_and_what_is_not_scored() -> None:
    truth = {"mode": "Online", "emi_amount": "", "nirf_rank_course": "#45", "linked_university": 12,
             "hero_image": 99, "seo_title": "x", "faqs": []}
    pred = {"mode": "", "emi_amount": "INR 8,750", "nirf_rank_course": "#45", "linked_university": None,
            "seo_title": "y", "extra_field": "z"}
    by = {r["field"]: r for r in scoring.score_case(pred, truth)}
    assert by["mode"]["status"] == "missed"
    assert by["emi_amount"]["status"] == "invented"
    assert by["nirf_rank_course"]["status"] == "match"
    assert by["faqs"]["status"] == "both_empty"
    assert by["seo_title"]["generated"] is True
    assert "linked_university" not in by and "hero_image" not in by and "extra_field" not in by


def test_post_title_is_scored_as_a_name() -> None:
    by = {r["field"]: r for r in scoring.score_case({}, {}, "Jain University Online MBA", "Jain University Online MBA")}
    assert by["post_title"]["passed"] and by["post_title"]["category"] == "names"


def test_categories() -> None:
    assert scoring.category("admission_fee_note") == "admission"
    assert scoring.category("fee_heading") == "headings"
    assert scoring.category("other_specs") == "spec-wise fees"
    assert scoring.category("semester_plan_amount") == "fees"
    assert scoring.category("course_academic_years") == "syllabus"
    assert scoring.category("top_hiring_partners_course") == "jobs & placement"


def test_stress_checks() -> None:
    years = [{"course_year_title": "Year I", "course_semesters": [
        {"course_semester_title": "Semester I", "course_semester_subjects": "<ul><li>A</li><li>B</li></ul>"},
        {"course_semester_title": "Semester II", "course_semester_subjects": "<ul><li>C</li></ul>"}]}]
    acf = {"course_academic_years": years, "programs_table": [{}] * 5, "admission_steps": UPES_STEPS_HTML,
           "placement_content": "<p>Alumni work at ICICI Bank.</p>"}
    assert scoring.run_check({"type": "semester_subjects", "field": "course_academic_years", "equals": [2, 1]}, acf, None)["passed"]
    assert not scoring.run_check({"type": "semester_subjects", "field": "course_academic_years", "equals": [8, 8]}, acf, None)["passed"]
    assert scoring.run_check({"type": "row_count", "field": "programs_table", "equals": 5}, acf, None)["passed"]
    assert scoring.run_check({"type": "html_list_items", "field": "admission_steps", "equals": 2}, acf, None)["passed"]
    assert scoring.run_check({"type": "contains", "field": "admission_steps", "phrases": ["Step 1. Ensure"]}, acf, None)["passed"]
    assert scoring.run_check({"type": "not_contains", "field": "placement_content", "phrases": ["guaranteed"]}, acf, None)["passed"]
    assert scoring.run_check({"type": "equals", "field": "post_title", "value": "DevOps"}, acf, "DevOps")["passed"]


def test_page_invariants_catch_placeholders_and_bad_headings() -> None:
    acf = {"emi_amount": "N/A", "accreditations_heading": "AI FOR HUMAN RESOURCES : 1,96,000/-"}
    codes = {i["code"] for i in scoring.invariants(acf, "course", "AI FOR HUMAN RESOURCES : 1,96,000/-", "x", [])}
    assert {"placeholder", "heading_format"} <= codes


# ── projection (fake WordPress) ──

def test_projection_runs_the_real_publish_layer_in_both_modes(allow_mock_transport) -> None:
    from evals.projection import project
    payload = {"_meta": {"document_title": "x", "page_type": "course"}, "program_name": "Jamia Online MBA",
               "total_fee": "N/A", "fee_plans": [{"plan_name": "Total Fee", "plan_amount": "INR 60,000 /-"}],
               "syllabus_content": "<p>Intro.</p><h3>Year I</h3><ul><li>A</li></ul>", "nirf_rank": "#45"}
    published = project(payload, "course", "published")
    raw = project(payload, "course", "raw")
    assert published["title"] == raw["title"] == "Jamia Online MBA"
    assert published["acf"]["total_fee"] == "INR 60,000 /-"      # repaired at publish
    assert raw["acf"]["total_fee"] == "N/A"                        # what extraction produced
    assert published["acf"]["course_syllabus_description"] == "Intro."
    assert "course_syllabus_description" not in raw["acf"]
    assert raw["acf"]["nirf_rank_course"] == "#45"                 # renames still apply


def test_projection_restores_the_real_client(allow_mock_transport) -> None:
    from evals.projection import project
    from pipeline import wordpress_client as wc
    before = (wc.httpx, wc._polish_for_wordpress)
    project({"_meta": {}, "program_name": "X"}, "course", "raw")
    assert (wc.httpx, wc._polish_for_wordpress) == before


# ── caching, offline and budget ──

def test_responses_are_cached_by_exact_request(tmp_path) -> None:
    real = FakeAnthropic(lambda kw: message({"ok": True}, usage=(1000, 100)))
    ledger = Ledger()
    client = CachingAnthropic(lambda: real, ResponseCache(tmp_path), ledger)
    for _ in range(2):
        with ledger.scoped("v2-sonnet", "c1"):
            with client.beta.messages.stream(model="claude-sonnet-5-5", messages=[{"role": "user", "content": "a"}]) as s:
                assert json.loads(s.get_final_message().content[-1].text) == {"ok": True}
    assert len(real.calls) == 1
    assert (ledger.cache_misses, ledger.cache_hits) == (1, 1)
    assert ledger.spent_usd == pytest.approx((1000 * 2 + 100 * 10) / 1e6)
    assert ledger.runs[("v2-sonnet", "c1")]["cost_usd"] == pytest.approx(2 * (1000 * 2 + 100 * 10) / 1e6)  # nominal


def test_offline_and_budget_refuse_new_calls(tmp_path) -> None:
    real = FakeAnthropic(lambda kw: message({"ok": True}))
    offline = Ledger(offline=True)
    client = CachingAnthropic(lambda: real, ResponseCache(tmp_path), offline)
    with pytest.raises(OfflineMiss):
        client.messages.create(model="claude-sonnet-5-5", messages=[])
    assert offline.blocked and real.calls == []
    capped = Ledger(budget_usd=0.0)
    capped.spent_usd = 0.01
    with pytest.raises(BudgetExceeded):
        CachingAnthropic(lambda: real, ResponseCache(tmp_path / "b"), capped).messages.create(model="x", messages=[])


# ── truth ──

def test_truth_from_a_draft_post_via_get_only(wp_configured) -> None:
    from evals.fetch_truth import fetch_post, truth_from_post

    class Client:
        def __init__(self):
            self.calls = []

        def get(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return FakeResponse({"id": 7, "status": "draft", "title": {"raw": "Jamia Online MBA"}, "acf": {"mode": "Online"}})

    client = Client()
    post = fetch_post("course", 7, client=client)
    url, kwargs = client.calls[0]
    assert url == "https://wp.test/wp-json/wp/v2/course/7"
    assert kwargs["params"]["context"] == "edit"
    truth = truth_from_post(post, "course")
    assert truth["title"] == "Jamia Online MBA" and truth["acf"] == {"mode": "Online"} and truth["status"] == "draft"


def test_cases_and_overrides(tmp_path) -> None:
    docx = tmp_path / "Copy of UPES Online MBA program.docx"
    docx.write_bytes(upes_course_docx())
    d = new_case("upes-mba", docx, "course", post_id=7, root=tmp_path / "cases")
    spec = json.loads((d / "case.json").read_text())
    spec["truth_overrides"] = {"mode": "Online"}
    (d / "case.json").write_text(json.dumps(spec))
    (d / "truth.json").write_text(json.dumps({"title": "UPES Online MBA", "acf": {"mode": "", "duration": "2 Years"}}))
    [case] = load_cases(tmp_path / "cases")
    assert case.filename == "Copy of UPES Online MBA program.docx"
    assert case.truth()["acf"] == {"mode": "Online", "duration": "2 Years"}
    with pytest.raises(ValueError):
        load_cases(tmp_path / "cases", ["nope"])


# ── the whole run ──

def _fake_openai():
    def create(model, input):
        vectors = [[b / 255 for b in hashlib.sha256(t.encode()).digest()[:16]] for t in input]
        return SimpleNamespace(data=[SimpleNamespace(embedding=v) for v in vectors],
                               usage=SimpleNamespace(prompt_tokens=10 * len(input)))
    return SimpleNamespace(embeddings=SimpleNamespace(create=create))


def _fake_anthropic():
    client = standard_client()
    # v1's per-field calls: "nothing found" for every field
    client.messages = SimpleNamespace(create=lambda **kw: message({"value": None}, model=kw["model"], usage=(1200, 100), thinking=False))
    return client


@pytest.fixture
def eval_dirs(tmp_path):
    docx = tmp_path / "Copy of UPES Online MBA program.docx"
    docx.write_bytes(upes_course_docx())
    d = new_case("upes-mba", docx, "course", post_id=7, root=tmp_path / "cases")
    spec = json.loads((d / "case.json").read_text())
    spec["checks"] = [{"type": "html_list_items", "field": "admission_steps", "equals": 2},
                      {"type": "contains", "field": "admission_fee_note", "phrases": ["Additional information"]}]
    (d / "case.json").write_text(json.dumps(spec))
    (d / "truth.json").write_text(json.dumps({"title": "UPES Online MBA", "acf": {
        "program_name": "UPES Online MBA", "admission_steps": UPES_STEPS_HTML,
        "admission_fee_note": "Additional information: Keep scanned copies of your documents ready.",
        "course_amount_range": "INR 25,000 /- Semester – INR 40,000 /- Semester", "emi_amount": "", "faqs": []}}))
    return {"cases_dir": tmp_path / "cases", "cache_dir": tmp_path / "cache", "reports_dir": tmp_path / "reports"}


def _run(argv, eval_dirs):
    from evals import run_eval
    return run_eval.main(argv, anthropic_factory=_fake_anthropic, openai_factory=_fake_openai, env={}, **eval_dirs)


@pytest.mark.usefixtures("allow_mock_transport")
def test_paid_calls_need_yes(eval_dirs, capsys) -> None:
    pytest.importorskip("docling")
    assert _run([], eval_dirs) == 2
    assert "Nothing was run" in capsys.readouterr().out
    assert not eval_dirs["reports_dir"].exists()


@pytest.mark.usefixtures("allow_mock_transport")
def test_full_run_then_free_offline_rerun(eval_dirs) -> None:
    pytest.importorskip("docling")
    assert _run(["--yes", "--budget", "5"], eval_dirs) == 0
    [first] = list(eval_dirs["reports_dir"].iterdir())
    results = json.loads((first / "results.json").read_text())
    assert set(results["variants"]) == {"v1/published", "v1/raw", "v2-sonnet/raw", "v2-sonnet/published"}
    v2 = results["variants"]["v2-sonnet/raw"]["cases"][0]
    fields = {f["field"]: f for f in v2["fields"]}
    assert fields["admission_steps"]["passed"] and fields["admission_fee_note"]["passed"]
    assert fields["course_amount_range"]["passed"] and fields["post_title"]["passed"]
    assert all(c["passed"] for c in v2["checks"])
    assert v2["cost_usd"] > 0 and results["spent_usd"] > 0
    report = (first / "report.md").read_text()
    assert "## Summary" in report and "v2-sonnet/raw" in report and "## Stress checks" in report

    # same documents, prompts and models: everything comes from the cache
    import time
    time.sleep(1)  # report directories are named by the second
    assert _run(["--offline"], eval_dirs) == 0
    second = sorted(eval_dirs["reports_dir"].iterdir())[-1]
    again = json.loads((second / "results.json").read_text())
    assert again["spent_usd"] == 0 and again["cache_misses"] == 0
    assert again["variants"]["v2-sonnet/raw"]["cases"][0]["fields"] == v2["fields"]


def test_refuses_with_a_redirected_api_url(eval_dirs, capsys) -> None:
    from evals import run_eval
    assert run_eval.main([], env={"ANTHROPIC_BASE_URL": "https://proxy.example"}, **eval_dirs) == 3
    assert "ANTHROPIC_BASE_URL" in capsys.readouterr().err


def test_estimate_is_free_for_cached_extractions(tmp_path) -> None:
    pytest.importorskip("docling")
    from evals import estimate
    from pipeline.v2.markdown import to_markdown
    md = to_markdown(upes_course_docx(), "x.docx").markdown
    cache = ResponseCache(tmp_path)
    fresh = estimate.estimate_v2("c", "v2-sonnet", md, "course", "Copy of UPES Online MBA program", "high", cache)
    assert fresh.usd > 0 and not fresh.cached
    request = estimate._v2_request(md, "course", "Copy of UPES Online MBA program", "claude-sonnet-5-5", "high")
    cache.put(cache.key("beta.messages.stream", request), {"stored": True})
    assert estimate.estimate_v2("c", "v2-sonnet", md, "course", "Copy of UPES Online MBA program", "high", cache).usd == 0


def test_syllabus_may_open_with_a_year_heading() -> None:
    from pipeline.v2 import checks
    md = "Year I Semester I Accounting"
    ok = checks.check_payload({"syllabus_content": "<h3>Year I</h3><h4>Semester I</h4><ul><li>Accounting</li></ul>"}, "course", md, "t")
    assert ok == []
    bad = checks.check_payload({"exam_content": "<h3>Jain Examination Process</h3><p>Online exams.</p>"}, "course",
                               "Jain Examination Process Online exams.", "t")
    assert [f["code"] for f in bad] == ["starts_with_heading"]


def test_contains_checks_read_every_row() -> None:
    rows = [{"other_spec_name": f"Spec {i}", "other_spec_fee": "INR 1,75,000"} for i in range(9)]
    rows.append({"other_spec_name": "Oil and Gas", "other_spec_fee": "INR 2,20,000"})
    assert scoring.run_check({"type": "contains", "field": "other_specs", "phrases": ["Oil and Gas", "INR 2,20,000"]},
                             {"other_specs": rows}, None)["passed"]


def test_auto_checks_come_from_the_document(tmp_path) -> None:
    pytest.importorskip("docling")
    from evals.autochecks import generate
    docx = tmp_path / "Copy of UPES Online MBA program.docx"
    docx.write_bytes(upes_course_docx())
    d = new_case("upes-mba", docx, "course", root=tmp_path / "cases")
    [case] = load_cases(d.parent)
    checks = {(c["type"], c["field"]): c for c in generate(case)}
    assert checks[("html_list_items", "admission_steps")]["equals"] == 2
    assert checks[("row_count", "specialization")]["equals"] == 2


def test_manual_checks_win_over_generated_ones(tmp_path) -> None:
    docx = tmp_path / "x.docx"
    docx.write_bytes(upes_course_docx())
    d = new_case("c", docx, "course", root=tmp_path / "cases")
    spec = json.loads((d / "case.json").read_text())
    spec["checks"] = [{"type": "row_count", "field": "faqs", "equals": 3}]
    spec["auto_checks"] = [{"type": "row_count", "field": "faqs", "equals": 9}, {"type": "row_count", "field": "job_profiles", "equals": 5}]
    (d / "case.json").write_text(json.dumps(spec))
    [case] = load_cases(tmp_path / "cases")
    assert [(c["field"], c["equals"]) for c in case.checks] == [("faqs", 3), ("job_profiles", 5)]


def test_opus_sonnet_agreement() -> None:
    from evals.report import agreement
    variants = {
        "v2-opus/raw": {"cases": [{"case_id": "c", "acf": {"total_fee": "INR 1,00,000 /-", "mode": "Online", "seo_title": "a"}}]},
        "v2-sonnet/raw": {"cases": [{"case_id": "c", "acf": {"total_fee": "₹1,00,000", "mode": "Hybrid", "seo_title": "b"}}]},
    }
    result = agreement(variants, "v2-opus/raw", "v2-sonnet/raw")
    assert (result["agree"], result["total"]) == (1, 2)
    assert result["differences"][0]["field"] == "mode"


def test_batches_merge_into_one_report() -> None:
    from evals.merge import merge
    def run(started, case, acc):
        return {"started_at": started, "pipelines": ["v2-opus"], "prompt_version": "v2.4", "spent_usd": 1.0,
                "cache_hits": 0, "cache_misses": 2, "stopped": None,
                "variants": {"v2-opus/raw": {"cases": [{"case_id": case, "acc": acc}]}}}
    merged = merge([run("2026-10-23 23:40", "a", 1), run("2026-10-23 23:41", "b", 2), run("2026-10-23 23:42", "a", 3)])
    assert merged["cases"] == ["a", "b"]
    assert [c["acc"] for c in merged["variants"]["v2-opus/raw"]["cases"]] == [3, 2]   # latest run wins
    assert merged["spent_usd"] == 3.0
