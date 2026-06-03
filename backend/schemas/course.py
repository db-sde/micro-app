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
    "course_name": "name of the course program title",
    "course_about": "about the course overview introduction program description what is this course",
    "course_accreditations": "accreditations approvals rankings recognitions",
    "eligibility": "eligibility criteria admission requirements qualification needed who can apply",
    "course_facts": "course facts key facts highlights program highlights quick facts",
    "admission_process": "admission process how to apply enrollment steps",
    "specializations": "specializations offered specialization options available tracks",
    "specialization_fees": "specialization wise fees cost per specialization fee table",
    "fee_structure": "fee structure semester fee total cost payment plan course fee",
    "syllabus": "syllabus curriculum subjects semester wise course structure year wise topics",
    "placement_partners": "placement partners hiring partners recruiters career services",
    "job_roles": "job roles salary career opportunities positions after course",
    "faqs": "frequently asked questions common queries",
    "duration": "course duration program length years months",
    "total_fee": "total fee complete course cost full amount",
    "emi_amount": "EMI monthly installment amount per month",
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
