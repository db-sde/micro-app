"""
University page schema: Pydantic model, field descriptions for embedding,
field type mapping, and required-field list.
"""

from typing import Any, Optional
from pydantic import BaseModel


class UniversitySchema(BaseModel):
    university_name: Optional[Any] = None
    about_content: Optional[Any] = None
    key_highlights: Optional[Any] = None
    accreditations: Optional[Any] = None
    stat_students: Optional[Any] = None
    stat_alumni: Optional[Any] = None
    stat_hiring_partners: Optional[Any] = None
    stat_years: Optional[Any] = None
    stat_programs: Optional[Any] = None
    admission_process: Optional[Any] = None
    emi_details: Optional[Any] = None
    courses_table: Optional[Any] = None
    faculty_table: Optional[Any] = None
    placement_content: Optional[Any] = None
    faqs: Optional[Any] = None
    reviews: Optional[Any] = None
    pros_content: Optional[Any] = None


# ── Embedding descriptions per field (used by the embedder to build the vector index) ──

UNIVERSITY_FIELDS: dict[str, str] = {
    "university_name": (
        "name of the university full title institution college"
    ),
    "about_content": (
        "about university overview history background introduction who we are "
        "legacy heritage establishment story mission vision main content body description "
        "short description hero description brief intro about page intro text"
    ),
    "key_highlights": (
        "key highlights facts quick facts university facts at a glance key numbers "
        "achievements notable points important statistics badge features at a glance"
    ),
    "accreditations": (
        "accreditations approvals recognitions certifications rankings affiliations "
        "NAAC UGC AICTE approved grade accredited certifications regulatory bodies"
    ),
    "stat_students": (
        "total students enrolled learner count student strength number of learners "
        "student base active students community size registered students"
    ),
    "stat_alumni": (
        "alumni count total alumni network former students graduates alumni base "
        "alumni community past students successful alumni number of graduates"
    ),
    "stat_hiring_partners": (
        "number count badge stat total how many hiring corporate partners "
        "hero stat badge number 100+ 200+ recruiters count total figure"
    ),
    "stat_years": (
        "years of excellence experience established legacy years of operation age "
        "founded since establishment year decades of experience years serving"
    ),
    "stat_programs": (
        "total programs courses offered number of programs count of courses "
        "programs available program catalog total offerings academic programs"
    ),
    "admission_process": (
        "admission process how to apply enrollment steps registration procedure "
        "application steps join now entry process sign up admission guide"
    ),
    "emi_details": (
        "EMI fee payment installments monthly payment financial aid scholarships "
        "loan facility banking partners no cost EMI pay in installments easy EMI "
        "deferred payment fee structure payment options"
    ),
    "courses_table": (
        "courses programs offered university courses table list of programs "
        "available courses program list all programs offered catalog degree options"
    ),
    "faculty_table": (
        "faculty members professors instructors teaching staff academic team "
        "our faculty expert faculty meet the faculty staff directory educators"
    ),
    "placement_content": (
        "placement partners career services job placement recruitment "
        "career outcomes placement record support placement drive "
        "industry connections job assistance list of companies top recruiters "
        "hiring partners company names recruiters who hire our students"
    ),
    "faqs": (
        "frequently asked questions FAQs common queries questions and answers "
        "common doubts Q and A people also ask student queries help"
    ),
    "reviews": (
        "reviews testimonials student feedback student experiences student speak "
        "what students say alumni reviews ratings opinions success stories"
    ),
    "pros_content": (
        "pros advantages benefits why choose reasons to choose why us "
        "why opt for this university key benefits distinguishing features"
    ),
}


# ── ACF field type per key (controls extraction prompt style) ──

UNIVERSITY_FIELD_TYPES: dict[str, str] = {
    "university_name": "text",
    "about_content": "wysiwyg",
    "key_highlights": "bullet",
    "accreditations": "bullet",
    "stat_students": "stat",
    "stat_alumni": "stat",
    "stat_hiring_partners": "stat",
    "stat_years": "stat",
    "stat_programs": "stat",
    "admission_process": "wysiwyg",
    "emi_details": "wysiwyg",
    "courses_table": "table",
    "faculty_table": "table",
    "placement_content": "wysiwyg",
    "faqs": "faq",
    "reviews": "bullet",
    "pros_content": "bullet",
}


# ── Required fields — these determine the quality score ──

UNIVERSITY_REQUIRED: list[str] = [
    "university_name",
    "about_content",
    "key_highlights",
    "accreditations",
    "stat_students",
    "stat_hiring_partners",
    "stat_years",
    "stat_programs",
    "admission_process",
    "emi_details",
    "courses_table",
    "faculty_table",
    "placement_content",
    "faqs",
    "reviews",
]
