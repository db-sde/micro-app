"""
DegreeBaba document processing pipeline.
"""

from pipeline.docx_parser import parse_docx
from pipeline.page_detector import detect_page_type
from pipeline.embedder import match_headings_to_fields, initialize_field_index
from pipeline.extractor import extract_field, confirm_mapping, resolve_ambiguous
from pipeline.validator import validate_payload
