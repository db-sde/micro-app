from acf.fields import SKIP_EXTRACTION_FIELDS

def build_json_output(validated_fields, document_title, page_type):
    """
    Build the final JSON payload containing extracted and validated field data.
    Ensures skip-extraction fields are explicitly set to null.
    """
    payload = {
        "_meta": {
            "document_title": document_title,
            "page_type": page_type,
            "generated_by": "DegreeBaba Content Publisher",
        }
    }
    for field in validated_fields:
        key = field['field_key']
        if key in SKIP_EXTRACTION_FIELDS:
            payload[key] = None   # always null — set manually in WordPress
        else:
            payload[key] = field['value']
    return payload
