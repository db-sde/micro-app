"""
Specialization page schema: Pydantic model, field descriptions for embedding,
field type mapping, and required-field list.
"""

from typing import Any, Optional
from pydantic import BaseModel


class SpecializationSchema(BaseModel):
    spec_name: Optional[Any] = None
    spec_about: Optional[Any] = None
    spec_facts: Optional[Any] = None
    eligibility: Optional[Any] = None
    spec_fee_table: Optional[Any] = None
    admission_process: Optional[Any] = None
    emi_details: Optional[Any] = None
    syllabus: Optional[Any] = None
    exam_pattern: Optional[Any] = None
    placement: Optional[Any] = None
    faqs: Optional[Any] = None
    reviews: Optional[Any] = None
    spec_total_fee: Optional[Any] = None
    spec_emi: Optional[Any] = None


# ── Embedding descriptions per field ──

SPECIALIZATION_FIELDS: dict[str, str] = {
    "spec_name": (
        "specialization name title track stream domain elective branch"
    ),
    "spec_about": (
        "about specialization course details overview introduction program description "
        "what is this specialization specialization summary background main content body"
    ),
    "spec_facts": (
        "specialization facts key facts highlights quick facts at a glance "
        "important statistics badge facts key information overview points course facts"
    ),
    "eligibility": (
        "eligibility criteria admission requirements qualification needed who can apply "
        "minimum qualification entry requirements graduation marks prerequisites "
        "academic requirements educational qualifications"
    ),
    "spec_fee_table": (
        "specialization fee course fee fee table payment fee structure "
        "fee breakdown semester fee fee details pricing cost total tuition"
    ),
    "admission_process": (
        "admission process how to apply enrollment steps registration procedure "
        "application guide join steps entry process sign up application steps"
    ),
    "emi_details": (
        "EMI installment monthly payment financial aid no cost EMI fee payment "
        "easy EMI pay in installments deferred payment banking partners loan facility"
    ),
    "syllabus": (
        "syllabus curriculum subjects year wise semester wise course structure "
        "academic plan study plan modules units topics subjects list course content"
    ),
    "exam_pattern": (
        "examination pattern assessment internal marks term end exam "
        "grading pattern evaluation scheme marks distribution exam structure "
        "assessment pattern exam process how exam works"
    ),
    "placement": (
        "placement career hiring partners career services job placement recruitment "
        "top recruiters placement partners career outcomes placement drive "
        "industry connections job assistance career support"
    ),
    "faqs": (
        "frequently asked questions FAQs common queries questions and answers "
        "common doubts student queries Q and A help section people also ask"
    ),
    "reviews": (
        "reviews testimonials student feedback student experiences student speak "
        "what students say alumni reviews ratings opinions success stories"
    ),
    "spec_total_fee": (
        "total fee complete amount full cost total specialization fee "
        "aggregate fee complete payment total tuition full program cost"
    ),
    "spec_emi": (
        "EMI monthly installment amount per month monthly payment no cost EMI "
        "installment plan monthly fee deferred payment easy EMI amount"
    ),
}


# ── ACF field type per key ──

SPECIALIZATION_FIELD_TYPES: dict[str, str] = {
    "spec_name": "text",
    "spec_about": "wysiwyg",
    "spec_facts": "bullet",
    "eligibility": "wysiwyg",
    "spec_fee_table": "table",
    "admission_process": "wysiwyg",
    "emi_details": "wysiwyg",
    "syllabus": "table",
    "exam_pattern": "wysiwyg",
    "placement": "wysiwyg",
    "faqs": "faq",
    "reviews": "bullet",
    "spec_total_fee": "stat",
    "spec_emi": "stat",
}


# ── Required fields (14) ──

SPECIALIZATION_REQUIRED: list[str] = [
    "spec_name",
    "spec_about",
    "spec_facts",
    "eligibility",
    "spec_fee_table",
    "admission_process",
    "emi_details",
    "syllabus",
    "exam_pattern",
    "placement",
    "faqs",
    "reviews",
    "spec_total_fee",
    "spec_emi",
]
