# Content map: what each page section shows, and where it comes from

One home for every piece of content. The parser writes each piece once, into
the field below; the theme shows each field once. Anything not in the
document stays empty (never "N/A", "not mentioned", "0 (Not offered)"), and
the theme hides a section or chip whose field is empty.

Status: **draft for the WordPress team (Nexevo) to confirm** — items marked
❓ need their answer. Field names are the live ACF names on
staging.degreebaba.com. The parser's own rules live in
`backend/pipeline/v2/field_guide.py` (extraction) and
`backend/pipeline/wordpress_client.py` (`_polish_for_wordpress`, publish).

## Rules that apply everywhere

| Rule | Why |
|---|---|
| Company names (hiring partners) appear only in the partner chips, never again as a list or sentence in the placement text | They showed twice (LPU, VGU, Jamia, DY Patil) |
| Bank / lender names appear only in the Partner Banks chips, never again in the EMI text | They showed twice (UPES) |
| Partner chips hold company names only — not sectors ("BFSI", "IT (30%)"), stats or services | IMT showed sectors as partners |
| Stats ("500+ hiring partners", "INR 7-8 LPA average") stay in the placement text | Placement stats went missing |
| Text keeps the document's wording and formatting: no rewriting, no added bold | Exam text read as exaggerated / bolded (Parul, UPES) |
| Value fields (validity, EMI, counts, NIRF, fees) are empty unless the document gives the value | "Validity is also not Mentioned", "0 (Not offered)" |
| A field the live site doesn't have is never sent (publishing would fail) | Staging removed course `validity` |

## University page

| Section on the page | Field(s) | Content |
|---|---|---|
| Hero name / badge / chips | `university_name`, `ugc_approved`, `naac_grade`, `mode_of_learning`, `established_year`, `starting_fee` | Values from the document's Quick Facts block |
| Hero text | `hero_description` | Document's hero paragraph; AI-written only if the document has none |
| About | `about_heading`, `about_content` | |
| Pros / why choose | `why_choose_heading`, `why_choose_content` | |
| Facts section | `facts_heading`, `facts_content` | The document's **"<University> facts"** section — **not** the Quick Facts key-value block (that feeds the hero chips) |
| Accreditations | `accreditations_heading`, `accreditations` (cards) | ❓ **The intro paragraph has no field** on university pages. Please add `accreditation_paragraph` (as on course pages); the parser already extracts it and will send it as soon as the field exists |
| Programs offered | `programs_heading`, `programs_intro`, `programs_table` | `programs_intro` = the document's paragraph above the table; AI-written only if there is none |
| Admission | `admission_heading`, `admission_steps`, `admission_fee_note` | Steps as one numbered list. Text after the last step ("Additional information …") is shown **under the list** as its own short block. `admission_fee_note` is typed by the team (the app suggests text from the document) ❓ please style the block under the list so it lines up (Galgotias looked misaligned) |
| EMI | `emi_heading`, `emi_content`, `emi_interest_rate_value`, `partner_banks_names` | Bank names only in `partner_banks_names`. ❓ **SMU: what makes the university EMI box show?** There is no EMI-amount field on university pages; the EMI text was sent but nothing showed |
| Examination | `exam_heading`, `exam_content`, `examination_cards` | Document's wording |
| Faculty | `faculty_heading`, `faculty_intro`, `faculty_members` | |
| Placement | `placement_heading`, `placement_content`, `placement_highlights` (chips) | `placement_highlights` = **company names only** (the "Top Hiring Partners" chips) |
| Reviews, FAQs | `reviews_heading`, `reviews`, `faqs_heading`, `faqs` | |

## Course page

| Section on the page | Field(s) | Content |
|---|---|---|
| Hero / chips / glance | `program_name`, `ugc_status`, `naac_grade`, `mode`, `duration`, `program_duration`, `total_fee`, `best_price_value`, `emi_amount`, `num_specializations`, `program_validity` | `best_price_value` = lowest total fee. Empty values must be hidden, not shown as "N/A" ❓ (At a Glance shows "Validity N/A") |
| About, highlights | `about_*`, `highlights*` | |
| Accreditations | `accreditations_heading`, `accreditation_paragraph`, `course_accreditations` | |
| Specializations | `specializations_heading`, `specializations_intro`, `specialization` | Only this program's specializations; empty when it has none |
| Eligibility | `eligibility_heading`, `eligibility_criteria_paragraph`, `eligibility_content`, `eligibility_summary` | The green note only when it adds something (never a copy of a criterion) |
| Fee & EMI | `fee_heading`, `fee_structure_paragraph`, `fee_plans`, `semester/annual/one-time` amounts, `emi_amount`, `partner_banks_course`, `scholarship_facility` | ❓ The scholarship text in the EMI box is static on spec pages — please show `scholarship_facility` (course) and hide it when empty |
| Syllabus | `syllabus_heading`, `course_syllabus_description`, `course_academic_years` | |
| Admission | as university | ❓ **VGU BBA (6709): the steps are stored as a 5-step list but the section doesn't show** — please check the template |
| Placement | `placement_heading`, `placement_content`, `top_hiring_partners_course` | as university |
| Jobs | `jobs_heading`, `job_roles_&_salary_paragraph`, `job_profiles` | |

## Specialization page

| Section on the page | Field(s) | Content |
|---|---|---|
| Hero name | `spec_name` | "<program> in <specialization>", e.g. "Online MBA in Finance", "Online MSc in Applied Mathematics" |
| Fee & EMI | `fee_heading`, `fee_section_paragraph`, `fee_plans`, `total_fee`, `best_price_specialization`, `emi_amount`, `partner_banks_specialization` | |
| Other specializations | `other_specs_heading`, `other_specializations_section_paragraph`, `other_specs` | The program's specializations from its fee table |
| Syllabus | `syllabus_heading`, `syllabus_section_paragraph`, `academic_years` | |
| Jobs | `jobs_heading`, `job_profiles_section_paragraph`, `job_profiles` | ❓ The paragraph exists in two fields (`jobs_content`, `job_profiles_section_paragraph`) and both were shown. The parser now sends it **only** to `job_profiles_section_paragraph`; please show only that one |
| Placement | `placement_heading`, `placement_content`, `hiring_partners_specialization` | as university |
| Exam | `exam_heading`, `examination_content`, `examination_process` | |

## For the WordPress team (Nexevo)

1. Add `accreditation_paragraph` to the university page and show it under the accreditations heading.
2. Hide empty values instead of printing "N/A" (At a Glance: Validity, EMI From) and hide chips with no value (IMT: blank approval chip).
3. Show `scholarship_facility` in the EMI box instead of the static text; hide when empty.
4. Show only `job_profiles_section_paragraph` in the specialization job section (not also `jobs_content`).
5. Style the "additional information" block under the admission steps.
6. VGU BBA draft 6709: admission steps stored but not shown.
7. SMU university: what drives the EMI box on university pages?
8. LPU MSc and others: show fees in full ("₹74,240"), not compacted ("₹74.2K").
