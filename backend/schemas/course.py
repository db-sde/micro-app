"""
Course page schema: Pydantic model, field descriptions for embedding,
field type mapping, and required-field list.
"""

from typing import Any, Optional
from pydantic import BaseModel


class CourseSchema(BaseModel):
    course_name: Optional[Any] = None
    course_about: Optional[Any] = None
    course_accreditations: Optional[Any] = None
    eligibility: Optional[Any] = None
    course_facts: Optional[Any] = None
    admission_process: Optional[Any] = None
    specializations: Optional[Any] = None
    specialization_fees: Optional[Any] = None
    fee_structure: Optional[Any] = None
    syllabus: Optional[Any] = None
    placement_partners: Optional[Any] = None
    job_roles: Optional[Any] = None
    faqs: Optional[Any] = None
    duration: Optional[Any] = None
    total_fee: Optional[Any] = None
    emi_amount: Optional[Any] = None


# ── Embedding descriptions per field ──

COURSE_FIELDS: dict[str, str] = {
    "course_name": (
        "name of the course program title degree qualification"
    ),
    "course_about": (
        "about the course overview introduction program description what is this course "
        "program summary background course details main content course information body"
    ),
    "course_accreditations": (
        "accreditations approvals rankings recognitions course approvals "
        "NAAC UGC AICTE certified grade regulatory bodies course certifications affiliations"
    ),
    "eligibility": (
        "eligibility criteria admission requirements qualification needed who can apply "
        "minimum qualification entry requirements graduation marks required prerequisites "
        "academic requirements educational qualification"
    ),
    "course_facts": (
        "course facts key facts highlights program highlights quick facts at a glance "
        "important statistics course statistics badge facts key information overview points"
    ),
    "admission_process": (
        "admission process how to apply enrollment steps registration procedure "
        "application guide join steps entry process sign up application steps"
    ),
    "specializations": (
        "specializations offered specialization options available tracks streams "
        "electives branches available specializations choose a specialization domains"
    ),
    "specialization_fees": (
        "specialization wise fees cost per specialization fee table specialization pricing "
        "fee by specialization track wise fees branch fees specialization fee structure"
    ),
    "fee_structure": (
        "fee structure semester fee total cost payment plan course fee annual fee "
        "tuition fee program cost full fee fee breakdown fee details fee schedule"
    ),
    "syllabus": (
        "syllabus curriculum subjects semester wise course structure year wise topics "
        "academic plan study plan modules units course content semester topics subjects list"
    ),
    "placement_partners": (
        "placement partners hiring partners recruiters career services top recruiters "
        "recruiting companies employer network MNC partners industry partners placements "
        "campus recruitment companies hiring organizations"
    ),
    "job_roles": (
        "job roles salary career opportunities positions after course job profiles "
        "career paths career scope employment roles designation salaries average salary "
        "career options post graduation jobs"
    ),
    "faqs": (
        "frequently asked questions FAQs common queries questions and answers "
        "common doubts student queries Q and A help section people also ask"
    ),
    "duration": (
        "course duration program length years months time to complete "
        "how long is the course program duration years of study"
    ),
    "total_fee": (
        "total fee complete course cost full amount total course fee "
        "program total fee total tuition complete payment aggregate fee"
    ),
    "emi_amount": (
        "EMI monthly installment amount per month monthly payment easy EMI "
        "no cost EMI installment plan monthly fee deferred payment amount"
    ),
}


# ── ACF field type per key ──

COURSE_FIELD_TYPES: dict[str, str] = {
    "course_name": "text",
    "course_about": "wysiwyg",
    "course_accreditations": "bullet",
    "eligibility": "wysiwyg",
    "course_facts": "bullet",
    "admission_process": "wysiwyg",
    "specializations": "bullet",
    "specialization_fees": "table",
    "fee_structure": "table",
    "syllabus": "table",
    "placement_partners": "bullet",
    "job_roles": "table",
    "faqs": "faq",
    "duration": "stat",
    "total_fee": "stat",
    "emi_amount": "stat",
}


# ── Required fields (14) ──

COURSE_REQUIRED: list[str] = [
    "course_name",
    "course_about",
    "course_accreditations",
    "eligibility",
    "course_facts",
    "admission_process",
    "specializations",
    "fee_structure",
    "syllabus",
    "placement_partners",
    "job_roles",
    "faqs",
    "duration",
    "total_fee",
]
