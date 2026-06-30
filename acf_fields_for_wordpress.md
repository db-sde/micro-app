# ACF Field Configuration for WordPress Developer

This document lists **ALL** the Advanced Custom Fields (ACF) that need to be created in WordPress, strictly matching the Python backend parser's configuration. Categorized by the Post Type (University, Course, Specialization).

### Important Setup Notes:
- For any field marked as **`repeater`**, you MUST create it as an ACF Repeater field and add the listed **Sub-fields** inside it exactly as spelled.
- The field names (keys) listed below must exactly match the `Field Name` in ACF (e.g. `university_name`).

## University Fields

| Field Name (Key) | ACF Field Type | Sub-fields (For Repeaters) |
|------------------|----------------|----------------------------|
| `university_name` | text | - |
| `university_full_name` | text | - |
| `hero_description` | textarea | - |
| `established_year` | text | - |
| `naac_grade` | text | - |
| `ugc_approved` | text | - |
| `mode_of_learning` | text | - |
| `starting_fee` | text | - |
| `num_programs` | text | - |
| `about_heading` | text | - |
| `why_choose_heading` | text | - |
| `facts_heading` | text | - |
| `accreditations_heading` | text | - |
| `programs_heading` | text | - |
| `admission_heading` | text | - |
| `emi_heading` | text | - |
| `exam_heading` | text | - |
| `faculty_heading` | text | - |
| `placement_heading` | text | - |
| `reviews_heading` | text | - |
| `faqs_heading` | text | - |
| `about_content` | wysiwyg | - |
| `why_choose_content` | wysiwyg | - |
| `admission_steps` | wysiwyg | - |
| `admission_fee_note` | text | - |
| `emi_content` | wysiwyg | - |
| `exam_content` | wysiwyg | - |
| `faculty_intro` | textarea | - |
| `placement_content` | wysiwyg | - |
| `facts` | repeater | `fact_title` (text)<br>`fact_description` (text) |
| `accreditations` | repeater | `body_name` (text)<br>`body_descriptor` (text)<br>`body_detail` (text) |
| `programs_table` | repeater | `program_name` (text)<br>`program_fee` (text)<br>`program_eligibility` (text) |
| `faculty_members` | repeater | `member_name` (text)<br>`member_program` (text)<br>`member_designation` (text)<br>`member_qualification` (text) |
| `reviews` | repeater | `review_text` (textarea)<br>`reviewer_name` (text)<br>`reviewer_label` (text) |
| `faqs` | repeater | `question` (text)<br>`answer` (textarea) |
| `seo_title` | text | - |
| `meta_description` | textarea | - |
| `programs_intro` | text | - |

## Course Fields

| Field Name (Key) | ACF Field Type | Sub-fields (For Repeaters) |
|------------------|----------------|----------------------------|
| `program_name` | text | - |
| `university_name` | text | - |
| `linked_university` | relationship / post object | - |
| `hero_description` | textarea | - |
| `duration` | text | - |
| `mode` | text | - |
| `naac_grade` | text | - |
| `ugc_status` | text | - |
| `total_fee` | text | - |
| `num_specializations` | text | - |
| `about_heading` | text | - |
| `highlights_heading` | text | - |
| `accreditations_heading` | text | - |
| `specializations_heading` | text | - |
| `fee_heading` | text | - |
| `eligibility_heading` | text | - |
| `admission_heading` | text | - |
| `syllabus_heading` | text | - |
| `placement_heading` | text | - |
| `jobs_heading` | text | - |
| `faqs_heading` | text | - |
| `about_content` | wysiwyg | - |
| `specializations_intro` | text | - |
| `eligibility_content` | wysiwyg | - |
| `admission_steps` | wysiwyg | - |
| `admission_fee_note` | text | - |
| `syllabus_content` | wysiwyg | - |
| `placement_content` | wysiwyg | - |
| `certificate_description` | textarea | - |
| `validity` | text | - |
| `emi_amount` | text | - |
| `highlights` | repeater | `highlight_title` (text)<br>`highlight_description` (text) |
| `fee_plans` | repeater | `plan_name` (text)<br>`plan_amount` (text)<br>`plan_total` (text) |
| `job_profiles` | repeater | `job_title` (text)<br>`avg_salary` (text) |
| `reviews` | repeater | `review_text` (textarea)<br>`reviewer_name` (text)<br>`reviewer_label` (text) |
| `faqs` | repeater | `question` (text)<br>`answer` (textarea) |
| `seo_title` | text | - |
| `meta_description` | textarea | - |
| `starting_fee` | text | - |
| `eligibility_summary` | text | - |

## Specialization Fields

| Field Name (Key) | ACF Field Type | Sub-fields (For Repeaters) |
|------------------|----------------|----------------------------|
| `spec_name` | text | - |
| `university_name` | text | - |
| `linked_university` | relationship / post object | - |
| `linked_course` | relationship / post object | - |
| `duration` | text | - |
| `mode` | text | - |
| `naac_grade` | text | - |
| `ugc_status` | text | - |
| `total_fee` | text | - |
| `about_heading` | text | - |
| `highlights_heading` | text | - |
| `eligibility_heading` | text | - |
| `fee_heading` | text | - |
| `other_specs_heading` | text | - |
| `syllabus_heading` | text | - |
| `exam_heading` | text | - |
| `admission_heading` | text | - |
| `placement_heading` | text | - |
| `jobs_heading` | text | - |
| `certificate_heading` | text | - |
| `faqs_heading` | text | - |
| `about_content` | wysiwyg | - |
| `eligibility_content` | wysiwyg | - |
| `syllabus_content` | wysiwyg | - |
| `exam_content` | wysiwyg | - |
| `admission_steps` | wysiwyg | - |
| `admission_fee_note` | text | - |
| `placement_content` | wysiwyg | - |
| `certificate_description` | textarea | - |
| `emi_amount` | text | - |
| `highlights` | repeater | `highlight_title` (text)<br>`highlight_description` (text) |
| `other_specs` | repeater | `other_spec_name` (text)<br>`other_spec_fee` (text) |
| `job_profiles` | repeater | `job_title` (text)<br>`avg_salary` (text) |
| `reviews` | repeater | `review_text` (textarea)<br>`reviewer_name` (text)<br>`reviewer_label` (text) |
| `faqs` | repeater | `question` (text)<br>`answer` (textarea) |
| `seo_title` | text | - |
| `meta_description` | textarea | - |
| `eligibility_summary` | text | - |

