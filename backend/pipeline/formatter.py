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
    relationship_hints = {}
    for field in validated_fields:
        key = field['field_key']
        if key in SKIP_EXTRACTION_FIELDS:
            # linked_university / linked_course / category_page are real
            # WordPress post-ID references, so the field itself always
            # stays null here — an ID is never written in a document.
            # But some docs DO write the target's friendly *name*, e.g. a
            # "Linked_university - UPES Online" line in a Quick Facts
            # block, caught by kv_parser same as any other KV pair. That
            # text is a strong, author-supplied signal for the name-match
            # lookup in wordpress_client._derive_relationships — stash it
            # in _meta instead of discarding it, rather than making that
            # matcher fall back to a much noisier guess (filename, or a
            # university_name/spec_name field that may itself be a
            # filename fallback).
            value = field['value']
            if value:
                relationship_hints[key] = value
            payload[key] = None   # always null — resolved to real IDs at publish time
        else:
            payload[key] = field['value']
    if relationship_hints:
        payload["_meta"]["relationship_hints"] = relationship_hints
    return payload
