"""What each field IS on the published page, for the extraction prompt.

Each line is the instruction the model gets for that field (as the JSON
Schema "description"). The rules come from errors found on published
pages; see EXTRACTION_V2_PLAN.md §3. Formats come from posts the team
corrected by hand.

Empty string / empty list means "not in the document".
"""

from __future__ import annotations

PAGE_NAME_FIELD = {"university": "university_name", "course": "program_name", "specialization": "spec_name"}

# Section label used for heading descriptions and the "<page name> <Label>"
# fallback (matches wordpress_client._HEADING_LABELS where both exist).
HEADING_LABELS: dict[str, str] = {
    "about_heading": "About", "why_choose_heading": "Advantages", "facts_heading": "Quick Facts",
    "accreditations_heading": "Accreditations", "programs_heading": "Programs & Fees",
    "admission_heading": "Admission Process", "emi_heading": "EMI Options",
    "exam_heading": "Examination Process", "faculty_heading": "Faculty",
    "placement_heading": "Placement Partners", "reviews_heading": "Reviews", "faqs_heading": "FAQs",
    "highlights_heading": "Highlights", "specializations_heading": "Specializations",
    "fee_heading": "Fee Structure", "eligibility_heading": "Eligibility Criteria",
    "syllabus_heading": "Syllabus", "jobs_heading": "Job Roles & Salary",
    "certificate_heading": "Certificate", "other_specs_heading": "Other Specializations",
}

_HEADING_RULE = (
    "Section heading of the {label} section, exactly as the document writes it, without any [tag] "
    "prefix. A heading is short (90 characters or fewer) and is never a sentence, a fee or amount, "
    "or a table row (e.g. 'AI FOR HUMAN RESOURCES : 1,96,000/-' is a table row, not a heading). "
    "Fill it even when the section's [tag] names only its content fields (a section tagged [why_choose_content] "
    "titled 'Pros of X' gives why_choose_heading 'Pros of X'). Empty only if that section has no heading of its own."
)

_MONEY = "Copy the amount exactly as written, with its currency and suffix (e.g. 'INR 1,30,000 /-')."

# Shared by every page type unless a page type overrides it.
COMMON: dict[str, str] = {
    "university_name": "The university's short brand name as the page title uses it (e.g. 'UPES Online', 'Jamia Millia Islamia Online'). Take it from the document title.",
    "university_full_name": "The university's full official name, only if the document states it.",
    "established_year": "Four-digit year the university was established (e.g. '2003').",
    "naac_grade": "NAAC grade only, e.g. 'A+' or 'A++' (not 'NAAC Grade A+').",
    "nirf_rank": "NIRF rank as a number with '#' (e.g. '#45'). Empty unless a NIRF rank number is stated.",
    "ugc_approved": "UGC status as written, e.g. 'UGC-entitled' or 'Approved'.",
    "ugc_status": "UGC status as written, e.g. 'Entitled' or 'Approved'.",
    "mode_of_learning": "Mode of learning as stated (e.g. 'Online').",
    "mode": "Mode of learning as stated (e.g. 'Online', 'Hybrid').",
    "duration": "Program duration as a short value, e.g. '2 Years' or '24 Months'.",
    "validity": "How long the program/degree stays valid, as stated (e.g. '4 Years').",
    "program_validity": "How long the program/degree stays valid, as stated (e.g. '4 Years').",
    "num_programs": "Number of programs the university offers, as a short stat (e.g. '5+'). Only if stated or countable from the programs table.",
    "num_specializations": "Number of specializations offered, as a short stat (e.g. '8+'). Only if stated or countable from a specialization list/table.",
    "starting_fee": "The lowest fee the page starts from, as written (e.g. 'INR 60,000 /-'). " + _MONEY,
    "total_fee": (
        "The complete program fee. If a fee table has a Total row, use it; if there are several totals "
        "(e.g. with and without Pay After Placement), use the LOWEST total. Never a single year or semester. "
        "Empty if fees only vary by specialization and no single total is given. " + _MONEY
    ),
    "emi_amount": "Monthly EMI amount as written (e.g. 'INR 6,927/-'). Empty if no EMI amount is stated; never 'N/A'.",
    "admission_fee_note": (
        "One short note shown under the admission steps: the text that follows the last step "
        "(e.g. 'Additional information: …', 'Important instructions: …'), as plain text. It is never "
        "one of the steps and never a copy of a step (not 'Step 5. Pay the fee…'). Empty if the document has no such note."
    ),
    "hero_description": (
        "The banner text under the page name, only when the document gives it as its own section (for example a "
        "heading tagged [hero_description] or titled 'Hero description'), as plain text. Empty otherwise: it is "
        "then written from the extracted facts."
    ),
    "specialization_hero_description": (
        "The banner text under the specialization name, only when the document gives it as its own section (for example "
        "tagged [specialization_hero_description] or titled 'Hero description'), as plain text. Empty otherwise."
    ),
    "about_content": "Body of the About section as clean HTML (<p>, <ul>, <ol>, <li>, <strong>, <em>, <h3>, <h4>). Keep all of it; do not summarise. Do not start with the section heading.",
    "why_choose_content": "Body of the 'Why choose' section as clean HTML. Keep all of it. Do not start with the section heading.",
    "admission_steps": (
        "The admission process as clean HTML: an optional intro <p>, then ONE ordered list <ol> of the steps in order. "
        "Bold 'Step N. Title:' lines are steps of this section, never new sections. Each step keeps its title and its "
        "description: <li><strong>Step 1. Ensure your eligibility:</strong> Students are required to…</li>. "
        "When a step has no title of its own, keep it as written: <li><strong>Step 1.</strong> Visit the official website…</li>; "
        "never invent a step title. "
        "Steps written as paragraphs ('Step 1…', 'Step 2…') also become <li> items. Anything after the last step "
        "(notes, 'Important instructions', 'Additional information') is NOT a step: leave it out here (it goes to "
        "admission_fee_note). Do not start with the section heading."
    ),
    "emi_content": "Body of the EMI / financing section as clean HTML. Do not start with the section heading.",
    "exam_content": "Body of the examination section as clean HTML. Do not start with the section heading.",
    "faculty_intro": "The paragraph before the faculty list/table, as plain text. Not the list itself.",
    "placement_content": (
        "Body of the placement section as clean HTML, kept as written. Do not claim guaranteed placement unless the "
        "document says so (some only list where alumni work). Do not start with the section heading."
    ),
    "syllabus_content": "The whole syllabus as clean HTML: <h3> per year, <h4> per semester, a <ul> of every subject. Keep every semester and every subject.",
    "certificate_description": "The certificate/degree description from the document, as plain text.",
    "specializations_intro": "One-line subtitle above the specialization list, from the document (e.g. 'Choose from 8 career-focused specializations').",
    "facts": "Quick facts as rows: fact_title (the label, e.g. 'Duration') and fact_description (its value). One row per fact, all of them.",
    "accreditations": "One row per approval/accreditation body: body_name (e.g. 'NAAC'), body_descriptor (e.g. 'A+ Grade'), body_detail (extra detail as written). All of them.",
    "course_accreditations": "One row per approval/accreditation body: course_body_name (e.g. 'NAAC'), course_body_descriptor (e.g. 'A+ Grade'), course_body_detail. All of them.",
    "programs_table": "Every program in the programs/fees table, one row each (program_name, program_fee, program_eligibility). Never drop rows: a table with 5 programs gives 5 rows.",
    "faculty_members": "One row per faculty member: member_name, member_designation, member_program (the program they teach, if given), member_qualification (degrees, if given). Keep program and qualification separate.",
    "reviews": "One row per student review: review_text, reviewer_name, reviewer_label (role/batch if given). Empty strings when a part isn't given; never invent names.",
    "faqs": "Every question and answer pair, in order (question, answer). All of them.",
    "highlights": "Program highlights, one row each: highlight_title and highlight_description. All of them.",
    "eligibility_content": "Eligibility criteria, one row per distinct criterion (qualification, minimum marks, work experience, age…): eligibility_title (short label) and eligibility_description (the requirement). All of them.",
    "fee_plans": (
        "Payment plans that have an amount, one row each: plan_name, plan_amount, plan_total. Only rows with an amount "
        "(not 'Variable by specialization'). EMI is not a plan (it has its own field). A 'Total' row is a plan named 'Total Fee'. "
        "plan_total = the table column/option the amount belongs to (e.g. 'Without Pay After Placement Option'), empty "
        "if the table has a single amount column. When the same plan name appears under several columns, put the column "
        "in the name: 'Semester Plan (Without Pay After Placement Option)'. " + _MONEY
    ),
    "job_profiles": "Every job role in the job-roles table, one row each: job_title and avg_salary as written (e.g. 'INR 6 LPA'). All rows.",
    "eligibility_intro": "Intro paragraph(s) above the eligibility criteria list, as plain text. Not the criteria themselves.",
    "fee_intro": "Intro paragraph(s) above the fee table/plans, as plain text. Not the fees themselves.",
    "accreditations_intro": "Intro paragraph(s) above the accreditations list, as plain text. Not the list.",
    "partner_banks_names": (
        "Banks / lenders / NBFCs the document names for EMI or education loans, as a clean HTML <ul> with one <li> per name "
        "(e.g. <ul><li>HDFC Bank</li><li>Propelld</li></ul>). Names only, as written. Empty if no lender is named."
    ),
    "emi_interest_rate_value": (
        "The EMI interest rate exactly as stated (e.g. '0%' for no-cost EMI, or '12% p.a.'). Empty unless the document "
        "states a rate or says the EMI is no-cost / zero-interest."
    ),
}

_COURSE: dict[str, str] = {
    "program_name": "The program's page name from the document title, e.g. 'Jamia Online MBA' or 'Shoolini University Online MBA' (no 'Copy of', no 'program'/'page').",
    "about_content": "Body of the About-the-program section as clean HTML. Keep all of it. Do not start with the section heading.",
    "specialization": (
        "Every specialization offered, one row each: specialization_name, and specialization_details = its fee(s) as written "
        "when a specialization-wise fee table gives them (empty otherwise). An 'All Specializations' row is a shared fee, not a "
        "specialization: never list it."
    ),
    "course_amount_range": "When the fee varies by specialization: 'lowest – highest' fee as written (e.g. 'INR 25,000 /- – INR 40,000 /-'); a single value when all are equal. Empty otherwise.",
    "course_academic_years": (
        "The year/semester syllabus, complete, one row per semester in order: course_year_title (e.g. 'Year I'), "
        "course_semester_title (e.g. 'Semester I') and course_semester_subjects = a <ul> of EVERY subject of that semester. "
        "Never drop a semester or a subject."
    ),
    "course_syllabus_description": "The paragraph shown above the year/semester syllabus accordion (the intro before the first year/semester), as plain text. Not the subjects.",
    "top_hiring_partners_course": (
        "Hiring partners / recruiters / companies where alumni work, as 'A, B, C' (names only, HTML entities decoded, no 'etc.'). "
        "From a lead-in line followed by short name lines, or an inline 'include A, B, C, etc.'. Empty if none are named."
    ),
    "jobs_intro": "The paragraph above the job-roles table, as plain text. Not the table.",
    "partner_banks_course": COMMON["partner_banks_names"],
}

_SPECIALIZATION: dict[str, str] = {
    "spec_name": "The specialization this page is about, from the document title: 'Copy of Jain University Online MCA in DevOps' gives 'DevOps'. Never guessed from the content or a fee table.",
    "about_content": "Body of the About-the-specialization section as clean HTML. Keep all of it. Do not start with the section heading.",
    "total_fee": COMMON["total_fee"] + " If only a specialization-wise table gives this specialization's fee, use that fee.",
    "academic_years": (
        "The year/semester syllabus, complete, one row per semester in order: year_title (e.g. 'Year I'), semester_title "
        "(e.g. 'Semester I') and semester_subjects = a <ul> of EVERY subject of that semester. Never drop a semester or a subject."
    ),
    "syllabus_description": "The paragraph shown above the year/semester syllabus accordion (the intro before the first year/semester), as plain text. Not the subjects.",
    "other_specs": (
        "The other specializations of the same program listed on this page, one row each: other_spec_name, and other_spec_fee "
        "as written (e.g. 'INR 82,300/-') when the document gives it. Not this page's own specialization."
    ),
    "jobs_content": "The paragraph(s) above the job-roles table, as plain text. Not the table.",
    "hiring_partners_specialization": _COURSE["top_hiring_partners_course"],
    "partner_banks_specialization": COMMON["partner_banks_names"],
    "examination_process": "The examination section as rows: exam_process_title (e.g. 'Exam Mode') and exam_process_description (e.g. 'Online, Proctored Examination'). One row per point.",
}

_UNIVERSITY: dict[str, str] = {
    "placement_highlights": (
        "Short placement highlights the document states, as a clean HTML <ul> (e.g. '250+ hiring partners', "
        "'Highest package INR 12 LPA', 'Virtual job fairs'). Only points written in the document, one per <li>; not the "
        "whole placement text and not a list of company names. Empty if the document has none."
    ),
    "examination_cards": (
        "The examination process as short cards, one row per point: exam_card_title (e.g. 'Exam Mode', 'Evaluation', "
        "'Results') and exam_card_description (e.g. 'Online proctored exams from home'). Taken from the examination "
        "section; exam_content keeps the full text."
    ),
}

OVERRIDES = {"university": _UNIVERSITY, "course": _COURSE, "specialization": _SPECIALIZATION}


def describe(page_type: str, key: str) -> str:
    """The guide line for one field; '' when there is none."""
    text = OVERRIDES.get(page_type, {}).get(key) or COMMON.get(key, "")
    if not text and key in HEADING_LABELS:
        text = _HEADING_RULE.format(label=HEADING_LABELS[key])
    return text
