"""
Payload validator — checks extracted payload against required fields and
computes a quality score.

Returns a validation report with:
  - summary: total_required, mapped, thin, missing, quality_score
  - field_report: per-field status list
"""

from __future__ import annotations

from typing import Any

from schemas import REQUIRED_BY_TYPE


def validate_payload(payload: dict[str, Any], page_type: str) -> dict[str, Any]:
    """Validate the extracted payload and return a quality report.

    Parameters
    ----------
    payload : dict
        Mapping of field_key → extracted value.
    page_type : str
        One of ``"university"``, ``"course"``, ``"specialization"``.

    Returns
    -------
    dict
        ``{"summary": {…}, "field_report": [{…}, …]}``
    """
    required_fields = REQUIRED_BY_TYPE.get(page_type, [])
    total_required = len(required_fields)

    mapped = 0
    thin = 0
    missing = 0
    field_report: list[dict[str, Any]] = []

    for field_key in required_fields:
        value = payload.get(field_key)

        if value is None or field_key not in payload:
            status = "missing"
            missing += 1
        elif _is_thin(value):
            status = "thin"
            thin += 1
        else:
            status = "mapped"
            mapped += 1

        field_report.append(
            {
                "field_key": field_key,
                "status": status,
                "has_value": value is not None and field_key in payload,
                "value_preview": _preview(value),
            }
        )

    # Quality score: mapped counts 1.0, thin counts 0.5, missing counts 0
    quality_score = 0.0
    if total_required > 0:
        quality_score = round(
            (mapped * 1.0 + thin * 0.5) / total_required * 100, 2
        )

    return {
        "summary": {
            "total_required": total_required,
            "mapped": mapped,
            "thin": thin,
            "missing": missing,
            "quality_score": quality_score,
        },
        "field_report": field_report,
    }


# ────────────────────────── helpers ──────────────────────────


def _is_thin(value: Any) -> bool:
    """Return True if *value* exists but is too small to be useful."""
    if isinstance(value, str):
        return len(value.strip()) < 80
    if isinstance(value, list):
        return len(value) < 2
    if isinstance(value, dict):
        # A dict with only a "value" key whose content is thin
        inner = value.get("value")
        if inner is not None:
            return _is_thin(inner)
        return False
    # Numbers, booleans, etc. — not thin
    return False


def _preview(value: Any, max_len: int = 120) -> str | None:
    """Return a short preview string of a value for the report."""
    if value is None:
        return None
    if isinstance(value, str):
        return value[:max_len] + ("…" if len(value) > max_len else "")
    if isinstance(value, list):
        return f"[{len(value)} items]"
    if isinstance(value, dict):
        inner = value.get("value")
        if inner is not None:
            return _preview(inner, max_len)
        return f"{{dict with {len(value)} keys}}"
    return str(value)[:max_len]
