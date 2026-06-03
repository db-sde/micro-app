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
    "spec_name": "specialization name title",
    "spec_about": "about specialization course details overview introduction",
    "spec_facts": "specialization facts key facts highlights",
    "eligibility": "eligibility criteria requirements",
    "spec_fee_table": "specialization fee course fee fee table payment",
    "admission_process": "admission process how to apply",
    "emi_details": "EMI installment monthly payment financial aid",
    "syllabus": "syllabus curriculum subjects year wise",
    "exam_pattern": "examination pattern assessment internal marks term end",
    "placement": "placement career hiring partners",
    "faqs": "frequently asked questions",
    "reviews": "reviews testimonials student feedback",
    "spec_total_fee": "total fee complete amount full cost",
    "spec_emi": "EMI monthly installment amount",
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
