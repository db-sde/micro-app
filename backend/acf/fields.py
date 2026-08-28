TEXT       = 'text'
HTML       = 'html'
TEXTAREA   = 'textarea'
JSON_ARRAY = 'json'
STAT       = 'stat'
IMAGE      = 'image'
RELATION   = 'relation'
FILE       = 'file'

ACF_FIELDS = {

    'university': [
        # Hero
        {'key': 'university_name',    'type': TEXT,     'embed': 'university name short brand name title'},
        {'key': 'university_full_name','type': TEXT,     'embed': 'university full official legal name complete'},
        {'key': 'hero_description',   'type': TEXTAREA, 'embed': 'hero description tagline short intro banner subtitle overview'},
        {'key': 'established_year',   'type': STAT,     'embed': 'established year founded since inception year est'},
        {'key': 'naac_grade',         'type': STAT,     'embed': 'naac grade accreditation rating A A+ score'},
        {'key': 'nirf_rank',          'type': STAT,     'embed': 'nirf rank ranking national institutional framework position number'},
        {'key': 'ugc_approved',       'type': TEXT,     'embed': 'ugc approved entitled status recognition approval'},
        {'key': 'mode_of_learning',   'type': TEXT,     'embed': 'mode of learning online offline distance hybrid delivery'},
        {'key': 'starting_fee',       'type': STAT,     'embed': 'starting fee lowest fee minimum fee per semester program'},
        {'key': 'num_programs',       'type': STAT,     'embed': 'number of programs total programs courses offered count'},
        # Images — populated only via /upload-image, never via docx text extraction
        {'key': 'hero_image',         'type': IMAGE,    'embed': ''},
        {'key': 'certificate_image',  'type': IMAGE,    'embed': ''},
        # Brochure PDF — populated only via /upload-brochure, optional
        {'key': 'brochure',           'type': FILE,     'embed': ''},
        # Headings
        {'key': 'about_heading',          'type': TEXT, 'embed': 'about heading section title'},
        {'key': 'why_choose_heading',     'type': TEXT, 'embed': 'why choose heading title pros benefits'},
        {'key': 'facts_heading',          'type': TEXT, 'embed': 'facts heading quick facts title'},
        {'key': 'accreditations_heading', 'type': TEXT, 'embed': 'accreditations heading rankings title'},
        {'key': 'programs_heading',       'type': TEXT, 'embed': 'programs heading fee structure title'},
        {'key': 'admission_heading',      'type': TEXT, 'embed': 'admission heading process title'},
        {'key': 'emi_heading',            'type': TEXT, 'embed': 'emi heading financial assistance title'},
        {'key': 'exam_heading',           'type': TEXT, 'embed': 'exam heading examination process title'},
        {'key': 'faculty_heading',        'type': TEXT, 'embed': 'faculty heading members title'},
        {'key': 'placement_heading',      'type': TEXT, 'embed': 'placement heading career services title'},
        {'key': 'reviews_heading',        'type': TEXT, 'embed': 'reviews heading student testimonials title'},
        {'key': 'faqs_heading',           'type': TEXT, 'embed': 'faqs heading frequently asked questions title'},
        # Content
        {'key': 'about_content',      'type': HTML,     'embed': 'about university description overview history background main content body'},
        {'key': 'why_choose_content', 'type': HTML,     'embed': 'why choose reasons benefits advantages pros highlights value proposition'},
        {'key': 'admission_steps',    'type': HTML,     'embed': 'admission process steps how to apply procedure enrollment registration'},
        {'key': 'admission_fee_note', 'type': TEXT,     'embed': 'admission fee note application fee charges'},
        {'key': 'emi_content',        'type': HTML,     'embed': 'emi no cost installment payment financing monthly bank scholarship'},
        {'key': 'exam_content',       'type': HTML,     'embed': 'exam pattern proctored online examination semester internal term end'},
        {'key': 'faculty_intro',      'type': TEXTAREA, 'embed': 'faculty introduction description overview teaching staff'},
        {'key': 'placement_content',  'type': HTML,     'embed': 'placement career services support partners recruiters hiring companies'},
        # Repeaters
        {'key': 'facts',              'type': JSON_ARRAY, 'embed': 'quick facts key facts highlights points bullet list',
         'sub_fields': [{'key': 'fact_title', 'type': TEXT}, {'key': 'fact_description', 'type': TEXT}]},
        {'key': 'accreditations',     'type': JSON_ARRAY, 'embed': 'accreditations approvals certifications recognitions naac ugc aicte nirf rankings',
         'sub_fields': [{'key': 'body_name', 'type': TEXT}, {'key': 'body_descriptor', 'type': TEXT}, {'key': 'body_detail', 'type': TEXT}]},
        {'key': 'programs_table',     'type': JSON_ARRAY, 'embed': 'programs table courses offered fee structure eligibility criteria list',
         'sub_fields': [{'key': 'program_name', 'type': TEXT}, {'key': 'program_fee', 'type': TEXT}, {'key': 'program_eligibility', 'type': TEXT}]},
        {'key': 'faculty_members',    'type': JSON_ARRAY, 'embed': 'faculty members professors teachers name qualification designation',
         'sub_fields': [{'key': 'member_name', 'type': TEXT}, {'key': 'member_program', 'type': TEXT}, {'key': 'member_designation', 'type': TEXT}, {'key': 'member_qualification', 'type': TEXT}]},
        {'key': 'reviews',            'type': JSON_ARRAY, 'embed': 'student reviews testimonials feedback ratings opinions experiences',
         'sub_fields': [{'key': 'review_text', 'type': TEXTAREA}, {'key': 'reviewer_name', 'type': TEXT}, {'key': 'reviewer_label', 'type': TEXT}]},
        {'key': 'faqs',               'type': JSON_ARRAY, 'embed': 'faqs frequently asked questions answers common queries',
         'sub_fields': [{'key': 'question', 'type': TEXT}, {'key': 'answer', 'type': TEXTAREA}]},
        # SEO
        {'key': 'seo_title',          'type': TEXT,     'embed': 'seo title meta title page title 50-60 chars'},
        {'key': 'meta_description',   'type': TEXTAREA, 'embed': 'meta description seo description search snippet 140-160 chars'},
        {'key': 'programs_intro',     'type': TEXT,     'embed': 'programs intro one line subtitle above programs table'},
    ],

    'course': [
        # Hero
        {'key': 'program_name',       'type': TEXT,     'embed': 'program name course name title mba mca bba'},
        {'key': 'university_name',    'type': TEXT,     'embed': 'university name institution brand'},
        {'key': 'linked_university',  'type': RELATION, 'embed': 'linked university post id relationship'},
        {'key': 'hero_description',   'type': TEXTAREA, 'embed': 'hero description tagline short program intro overview'},
        {'key': 'duration',           'type': STAT,     'embed': 'duration months years program length period'},
        {'key': 'mode',               'type': TEXT,     'embed': 'mode online offline hybrid learning delivery'},
        {'key': 'naac_grade',         'type': STAT,     'embed': 'naac grade accreditation A A+ score rating'},
        {'key': 'nirf_rank',          'type': STAT,     'embed': 'nirf rank ranking national institutional framework position number'},
        {'key': 'ugc_status',         'type': TEXT,     'embed': 'ugc status entitled approved recognition'},
        {'key': 'total_fee',          'type': STAT,     'embed': 'total fee best price complete course fee cost amount'},
        {'key': 'num_specializations','type': STAT,     'embed': 'number of specializations count available tracks options'},
        # Images — populated only via /upload-image, never via docx text extraction
        {'key': 'hero_image',         'type': IMAGE,    'embed': ''},
        {'key': 'certificate_image',  'type': IMAGE,    'embed': ''},
        # Brochure PDF — populated only via /upload-brochure, optional
        {'key': 'brochure',           'type': FILE,     'embed': ''},
        # Headings
        {'key': 'about_heading',           'type': TEXT, 'embed': 'about heading title'},
        {'key': 'highlights_heading',      'type': TEXT, 'embed': 'highlights heading program highlights title'},
        {'key': 'accreditations_heading',  'type': TEXT, 'embed': 'accreditations heading rankings title'},
        {'key': 'specializations_heading', 'type': TEXT, 'embed': 'specializations heading title'},
        {'key': 'fee_heading',             'type': TEXT, 'embed': 'fee heading structure emi title'},
        {'key': 'eligibility_heading',     'type': TEXT, 'embed': 'eligibility heading criteria title'},
        {'key': 'admission_heading',       'type': TEXT, 'embed': 'admission heading process title'},
        {'key': 'syllabus_heading',        'type': TEXT, 'embed': 'syllabus heading curriculum title'},
        {'key': 'placement_heading',       'type': TEXT, 'embed': 'placement heading career services title'},
        {'key': 'jobs_heading',            'type': TEXT, 'embed': 'jobs heading job profiles salary title'},
        {'key': 'faqs_heading',            'type': TEXT, 'embed': 'faqs heading frequently asked questions title'},
        # Content
        {'key': 'about_content',        'type': HTML,     'embed': 'about program description overview introduction body'},
        {'key': 'specializations_intro', 'type': TEXT,     'embed': 'specializations intro one line subtitle pick choose from'},
        {'key': 'eligibility_content',   'type': JSON_ARRAY, 'embed': 'eligibility criteria who can apply requirements qualification',
         'sub_fields': [{'key': 'eligibility_title', 'type': TEXT}, {'key': 'eligibility_description', 'type': TEXTAREA}]},
        {'key': 'admission_steps',       'type': HTML,     'embed': 'admission process steps how to apply procedure enrollment'},
        {'key': 'admission_fee_note',    'type': TEXT,     'embed': 'admission fee note application fee charges'},
        {'key': 'syllabus_content',      'type': HTML,     'embed': 'syllabus curriculum subjects semester year module topics'},
        {'key': 'placement_content',     'type': HTML,     'embed': 'placement career services support partners recruiters hiring'},
        {'key': 'certificate_description','type': TEXTAREA,'embed': 'certificate description degree credential earn completion'},
        # Sidebar
        {'key': 'validity',             'type': TEXT,     'embed': 'validity program valid years at a glance sidebar'},
        {'key': 'emi_amount',           'type': TEXT,     'embed': 'emi amount starting per month sidebar'},
        # Repeaters
        {'key': 'highlights',           'type': JSON_ARRAY, 'embed': 'highlights program highlights features benefits USPs',
         'sub_fields': [{'key': 'highlight_title', 'type': TEXT}, {'key': 'highlight_description', 'type': TEXT}]},
        # Matches WordPress's real field name/sub-field names exactly
        # (course_body_name/descriptor/detail) — no publish-time rename
        # needed. This is where bulleted accreditation content lives
        # (e.g. "Ranked #87 ... (NIRF)"), which nirf_rank is derived from
        # in enricher.py's _enrich_course_stats since it's rarely its own
        # separate heading in the source doc.
        {'key': 'course_accreditations', 'type': JSON_ARRAY, 'embed': 'course accreditations approvals certifications recognitions naac ugc aicte nirf rankings',
         'sub_fields': [{'key': 'course_body_name', 'type': TEXT}, {'key': 'course_body_descriptor', 'type': TEXT}, {'key': 'course_body_detail', 'type': TEXT}]},
        # Structured year -> semester breakdown of the syllabus, matching
        # WordPress's real field/sub-field names exactly (no publish-time
        # rename needed). Not extracted directly — derived deterministically
        # in enricher.py from syllabus_content's own <h3>Year</h3><h4>Semester</h4>
        # HTML structure, so it's always in sync with the flat text version.
        {'key': 'course_academic_years', 'type': JSON_ARRAY, 'embed': 'academic years semester wise syllabus year wise curriculum breakdown',
         'sub_fields': [{'key': 'course_year_title', 'type': TEXT}, {'key': 'course_semesters', 'type': JSON_ARRAY,
          'sub_fields': [{'key': 'course_semester_title', 'type': TEXT}, {'key': 'course_semester_subjects', 'type': HTML}]}]},
        {'key': 'fee_plans',            'type': JSON_ARRAY, 'embed': 'fee plans payment options semester annual one time total',
         'sub_fields': [{'key': 'plan_name', 'type': TEXT}, {'key': 'plan_amount', 'type': TEXT}, {'key': 'plan_total', 'type': TEXT}]},
        {'key': 'job_profiles',         'type': JSON_ARRAY, 'embed': 'job profiles roles career opportunities positions average salary',
         'sub_fields': [{'key': 'job_title', 'type': TEXT}, {'key': 'avg_salary', 'type': TEXT}]},
        {'key': 'reviews',              'type': JSON_ARRAY, 'embed': 'student reviews testimonials feedback ratings opinions',
         'sub_fields': [{'key': 'review_text', 'type': TEXTAREA}, {'key': 'reviewer_name', 'type': TEXT}, {'key': 'reviewer_label', 'type': TEXT}]},
        {'key': 'faqs',                 'type': JSON_ARRAY, 'embed': 'faqs frequently asked questions answers common queries',
         'sub_fields': [{'key': 'question', 'type': TEXT}, {'key': 'answer', 'type': TEXTAREA}]},
        # SEO
        {'key': 'seo_title',            'type': TEXT,     'embed': 'seo title meta title page title 50-60 chars'},
        {'key': 'meta_description',     'type': TEXTAREA, 'embed': 'meta description seo search snippet 140-160 chars'},
        {'key': 'starting_fee',         'type': TEXT,     'embed': 'starting fee per semester for comparison page'},
        {'key': 'eligibility_summary',  'type': TEXT,     'embed': 'eligibility summary short one line for comparison page'},
    ],

    'specialization': [
        # Hero
        {'key': 'spec_name',          'type': TEXT,     'embed': 'specialization name title marketing finance hr operations'},
        {'key': 'university_name',    'type': TEXT,     'embed': 'university name institution brand'},
        # AI-generated banner tagline — no docx section is tagged for this on
        # specialization pages, so it's filled entirely by generate_seo_and_intro().
        {'key': 'specialization_hero_description', 'type': TEXTAREA, 'embed': 'specialization hero description tagline short banner intro overview'},
        {'key': 'linked_university',  'type': RELATION, 'embed': 'linked university post id relationship'},
        {'key': 'linked_course',      'type': RELATION, 'embed': 'linked course post id relationship'},
        {'key': 'duration',           'type': STAT,     'embed': 'duration months years program length'},
        {'key': 'mode',               'type': TEXT,     'embed': 'mode online offline hybrid learning delivery'},
        {'key': 'naac_grade',         'type': STAT,     'embed': 'naac grade accreditation A A+ rating'},
        {'key': 'ugc_status',         'type': TEXT,     'embed': 'ugc status entitled approved recognition'},
        {'key': 'total_fee',          'type': TEXT,     'embed': 'total fee best price complete course fee cost semester breakdown'},
        # Images — populated only via /upload-image, never via docx text extraction
        {'key': 'hero_image',         'type': IMAGE,    'embed': ''},
        {'key': 'certificate_image',  'type': IMAGE,    'embed': ''},
        # Brochure PDF — populated only via /upload-brochure, optional
        {'key': 'brochure',           'type': FILE,     'embed': ''},
        # Headings
        {'key': 'about_heading',          'type': TEXT, 'embed': 'about heading title'},
        {'key': 'highlights_heading',     'type': TEXT, 'embed': 'highlights heading title'},
        {'key': 'eligibility_heading',    'type': TEXT, 'embed': 'eligibility heading criteria title'},
        {'key': 'fee_heading',            'type': TEXT, 'embed': 'fee heading structure emi title'},
        {'key': 'other_specs_heading',    'type': TEXT, 'embed': 'other specializations heading explore title'},
        {'key': 'syllabus_heading',       'type': TEXT, 'embed': 'syllabus heading curriculum title'},
        {'key': 'exam_heading',           'type': TEXT, 'embed': 'exam heading examination process title'},
        {'key': 'admission_heading',      'type': TEXT, 'embed': 'admission heading process title'},
        {'key': 'placement_heading',      'type': TEXT, 'embed': 'placement heading career services title'},
        {'key': 'jobs_heading',           'type': TEXT, 'embed': 'jobs heading profiles salary title'},
        {'key': 'certificate_heading',    'type': TEXT, 'embed': 'certificate heading certification title'},
        {'key': 'faqs_heading',           'type': TEXT, 'embed': 'faqs heading frequently asked questions title'},
        # Content
        {'key': 'about_content',        'type': HTML,     'embed': 'about specialization description overview introduction body'},
        {'key': 'eligibility_content',  'type': JSON_ARRAY, 'embed': 'eligibility criteria who can apply requirements qualification',
         'sub_fields': [{'key': 'eligibility_title', 'type': TEXT}, {'key': 'eligibility_description', 'type': TEXTAREA}]},
        {'key': 'syllabus_content',     'type': HTML,     'embed': 'syllabus curriculum subjects semester module topics'},
        {'key': 'exam_content',         'type': HTML,     'embed': 'exam pattern proctored examination semester internal term end'},
        {'key': 'admission_steps',      'type': HTML,     'embed': 'admission process steps how to apply procedure enrollment'},
        {'key': 'admission_fee_note',   'type': TEXT,     'embed': 'admission fee note application fee charges'},
        {'key': 'placement_content',    'type': HTML,     'embed': 'placement career services support partners recruiters hiring'},
        {'key': 'certificate_description','type': TEXTAREA,'embed': 'certificate description degree credential earn completion'},
        # Sidebar
        {'key': 'emi_amount',           'type': TEXT,     'embed': 'emi amount starting per month sidebar'},
        {'key': 'program_validity',     'type': TEXT,     'embed': 'program validity years valid period certificate lifetime'},
        # Repeaters
        {'key': 'highlights',           'type': JSON_ARRAY, 'embed': 'highlights program features benefits USPs key points',
         'sub_fields': [{'key': 'highlight_title', 'type': TEXT}, {'key': 'highlight_description', 'type': TEXT}]},
        # Structured year -> semester breakdown of the syllabus, matching
        # WordPress's real field/sub-field names exactly. Derived
        # deterministically in enricher.py from syllabus_content's own
        # <h3>Year</h3><h4>Semester</h4> HTML structure — see course's
        # course_academic_years for the same pattern.
        {'key': 'academic_years', 'type': JSON_ARRAY, 'embed': 'academic years semester wise syllabus year wise curriculum breakdown',
         'sub_fields': [{'key': 'year_title', 'type': TEXT}, {'key': 'semesters', 'type': JSON_ARRAY,
          'sub_fields': [{'key': 'semester_title', 'type': TEXT}, {'key': 'semester_subjects', 'type': HTML}]}]},
        {'key': 'fee_plans',            'type': JSON_ARRAY, 'embed': 'fee plans payment options semester annual one time total',
         'sub_fields': [{'key': 'plan_name', 'type': TEXT}, {'key': 'plan_amount', 'type': TEXT}, {'key': 'plan_total', 'type': TEXT}]},
        {'key': 'other_specs',          'type': JSON_ARRAY, 'embed': 'other specializations explore related alternatives list',
         'sub_fields': [{'key': 'other_spec_name', 'type': TEXT}, {'key': 'other_spec_fee', 'type': TEXT}]},
        {'key': 'job_profiles',         'type': JSON_ARRAY, 'embed': 'job profiles roles career opportunities average salary',
         'sub_fields': [{'key': 'job_title', 'type': TEXT}, {'key': 'avg_salary', 'type': TEXT}]},
        {'key': 'reviews',              'type': JSON_ARRAY, 'embed': 'student reviews testimonials feedback ratings opinions',
         'sub_fields': [{'key': 'review_text', 'type': TEXTAREA}, {'key': 'reviewer_name', 'type': TEXT}, {'key': 'reviewer_label', 'type': TEXT}]},
        {'key': 'faqs',                 'type': JSON_ARRAY, 'embed': 'faqs frequently asked questions answers',
         'sub_fields': [{'key': 'question', 'type': TEXT}, {'key': 'answer', 'type': TEXTAREA}]},
        # SEO
        {'key': 'seo_title',            'type': TEXT,     'embed': 'seo title meta title page title 50-60 chars'},
        {'key': 'meta_description',     'type': TEXTAREA, 'embed': 'meta description seo search snippet 140-160 chars'},
        {'key': 'eligibility_summary',  'type': TEXT,     'embed': 'eligibility summary short one line for comparison'},
    ],

    'blog': [
        # AI-generated summary and SEO fields — same structure for blog and category
        {'key': 'complete_page_summary', 'type': HTML, 'embed': 'complete page summary bullet points overview content highlights'},
        {'key': 'seo_title',             'type': TEXT, 'embed': 'seo title meta title page title search engine 50-60 chars'},
        {'key': 'meta_description',      'type': TEXTAREA, 'embed': 'meta description seo search snippet 140-160 chars'},
        {'key': 'reading_time',          'type': TEXT, 'embed': 'reading time minutes estimated read duration'},
    ],

    'category': [
        # AI-generated summary and SEO fields — same structure for blog and category
        {'key': 'complete_page_summary', 'type': HTML, 'embed': 'complete page summary bullet points overview content highlights'},
        {'key': 'seo_title',             'type': TEXT, 'embed': 'seo title meta title page title search engine 50-60 chars'},
        {'key': 'meta_description',      'type': TEXTAREA, 'embed': 'meta description seo search snippet 140-160 chars'},
    ],
}

# Fields that are purely structural or managed differently and should not be
# extracted from docx — currently just RELATION fields (linked_university,
# linked_course), which are WordPress post-ID references set manually in
# WordPress and can never come from document text. IMAGE fields are
# deliberately NOT included here: they ARE extractable (via /upload-image),
# so "missing" is a real, actionable signal until an image is uploaded.
SKIP_EXTRACTION_FIELDS = {
    f['key']
    for fields in ACF_FIELDS.values()
    for f in fields
    if f['type'] == RELATION
}

def get_all_valid_field_keys() -> set:
    keys = set()
    for fields in ACF_FIELDS.values():
        for f in fields:
            keys.add(f['key'])
    return keys

def get_valid_field_keys(page_type: str) -> set:
    """Field keys registered for a SPECIFIC page type only.

    Use this (not get_all_valid_field_keys) anywhere a tag/value needs to be
    validated against what's actually publishable for the current document —
    e.g. a `[fee_plans]` tag is a real field key, but only for "course", not
    "university" or "specialization"; accepting it globally lets content
    from the wrong page-type template silently pollute the payload with
    fields WordPress's ACF schema will reject on publish.
    """
    return {f['key'] for f in ACF_FIELDS.get(page_type, [])}

def get_field_type(field_key: str, page_type: str) -> str:
    for f in ACF_FIELDS.get(page_type, []):
        if f['key'] == field_key:
            return f['type']
    return 'text'

def get_first_sub_field_key(field_key: str, page_type: str) -> str | None:
    """First sub-field key of a JSON_ARRAY (repeater) field, if any."""
    for f in ACF_FIELDS.get(page_type, []):
        if f['key'] == field_key:
            sub_fields = f.get('sub_fields') or []
            return sub_fields[0]['key'] if sub_fields else None
    return None

# Field types that are never populated by docx text extraction/embedding —
# they're filled by dedicated flows instead (image/file upload, manual WP
# relation picking).
NON_EXTRACTABLE_TYPES = {IMAGE, RELATION, FILE}

def get_image_field_keys(page_type: str) -> set:
    """Return the set of IMAGE-type field keys valid for a given page type."""
    return {f['key'] for f in ACF_FIELDS.get(page_type, []) if f['type'] == IMAGE}

def get_file_field_keys(page_type: str) -> set:
    """Return the set of FILE-type field keys valid for a given page type."""
    return {f['key'] for f in ACF_FIELDS.get(page_type, []) if f['type'] == FILE}
