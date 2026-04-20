import re

from app import db
from app.models import ExtractionJob, ExtractionResult, utc_now
from app.services.package_readiness import normalize_classification_text, normalize_document_type


SUPPORTED_STRUCTURED_TYPES = {"w2", "1099_int", "1099_div", "1099_b", "1098", "k1"}

MONEY_PATTERN = r"\$?\s*([0-9]+(?:[\s,][0-9]{3})*(?:\.\d{1,2})?)"


def _clean_value(value):
    if value is None:
        return None
    return re.sub(r"\s+", " ", str(value)).strip(" :-")


def canonical_structured_type(document_type):
    normalized = normalize_document_type(document_type)
    aliases = {
        "w_2": "w2",
        "k_1": "k1",
        "1098_mortgage_interest": "1098",
    }
    return aliases.get(normalized, normalized)


def _money_value(value):
    cleaned = _clean_value(value)
    if not cleaned:
        return None
    return cleaned.replace(",", "").replace(" ", "")


def _find_first(text, patterns):
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _clean_value(match.group(1))
    return None


def _find_amount(text, patterns):
    value = _find_first(text, patterns)
    return _money_value(value)


def _field(value, confidence=0.75):
    return {"value": value, "confidence": confidence}


def _field_count_confidence(found_count, expected_count):
    if found_count >= max(3, expected_count // 2):
        return "high", 0.92
    if found_count >= 2:
        return "medium", 0.76
    if found_count >= 1:
        return "low", 0.55
    return "low", 0.35


def _result_payload(document_type, fields, expected_count, success_note, partial_note, empty_note):
    found_count = len(fields)
    confidence_label, confidence_score = _field_count_confidence(found_count, expected_count)
    if not fields:
        notes = empty_note
    elif found_count < expected_count:
        notes = partial_note
    else:
        notes = success_note

    return {
        "document_type": document_type,
        "fields": fields,
        "notes": notes,
        "confidence_label": confidence_label,
        "confidence_score": confidence_score,
        "validation_status": "passed" if fields else "needs_review",
    }


def _label_value_patterns(label, amount=True):
    value_pattern = MONEY_PATTERN if amount else r"([a-z0-9&.,' -]{2,80})"
    label_pattern = re.escape(label).replace(r"\ ", r"\s+")
    return [
        rf"{label_pattern}\s*[:#-]?\s*{value_pattern}",
        rf"{label_pattern}\s+(?:box\s*)?\d*[a-z]?\s*{value_pattern}",
    ]


def extract_w2_fields(text):
    normalized = normalize_classification_text(text)
    fields = {}

    field_patterns = {
        "employer_name": [
            r"employer(?:'s)?\s+name\s*[:#-]?\s*([a-z0-9&.,' -]{2,80})",
            r"employer\s+([a-z0-9&.,' -]{2,80})\s+ein",
        ],
        "employee_name": [
            r"employee(?:'s)?\s+name\s*[:#-]?\s*([a-z0-9&.,' -]{2,80})",
            r"employee\s+([a-z0-9&.,' -]{2,80})\s+ssn",
        ],
        "wages_box_1": [
            rf"(?:box\s*)?1\s+wages(?: tips and other compensation)?\s*[:#-]?\s*{MONEY_PATTERN}",
            rf"wages(?: tips and other compensation)?\s*[:#-]?\s*{MONEY_PATTERN}",
        ],
        "federal_withholding_box_2": [
            rf"(?:box\s*)?2\s+federal income tax withheld\s*[:#-]?\s*{MONEY_PATTERN}",
            rf"federal income tax withheld\s*[:#-]?\s*{MONEY_PATTERN}",
        ],
        "social_security_wages_box_3": [
            rf"(?:box\s*)?3\s+social security wages\s*[:#-]?\s*{MONEY_PATTERN}",
            rf"social security wages\s*[:#-]?\s*{MONEY_PATTERN}",
        ],
        "social_security_tax_box_4": [
            rf"(?:box\s*)?4\s+social security tax withheld\s*[:#-]?\s*{MONEY_PATTERN}",
            rf"social security tax withheld\s*[:#-]?\s*{MONEY_PATTERN}",
        ],
        "medicare_wages_box_5": [
            rf"(?:box\s*)?5\s+medicare wages(?: and tips)?\s*[:#-]?\s*{MONEY_PATTERN}",
            rf"medicare wages(?: and tips)?\s*[:#-]?\s*{MONEY_PATTERN}",
        ],
        "medicare_tax_box_6": [
            rf"(?:box\s*)?6\s+medicare tax withheld\s*[:#-]?\s*{MONEY_PATTERN}",
            rf"medicare tax withheld\s*[:#-]?\s*{MONEY_PATTERN}",
        ],
        "state_wages_box_16": [
            rf"(?:box\s*)?16\s+state wages(?: tips etc.)?\s*[:#-]?\s*{MONEY_PATTERN}",
            rf"state wages\s*[:#-]?\s*{MONEY_PATTERN}",
        ],
        "state_tax_box_17": [
            rf"(?:box\s*)?17\s+state income tax\s*[:#-]?\s*{MONEY_PATTERN}",
            rf"state income tax\s*[:#-]?\s*{MONEY_PATTERN}",
        ],
    }

    for field_name, patterns in field_patterns.items():
        value = _find_amount(normalized, patterns) if "name" not in field_name else _find_first(normalized, patterns)
        if value:
            confidence = 0.88 if "name" in field_name else 0.90
            fields[field_name] = _field(value, confidence)

    return _result_payload(
        "w2",
        fields,
        expected_count=9,
        success_note="Structured W-2 fields extracted.",
        partial_note="Partial W-2 extraction.",
        empty_note="Document classified as W-2, but no structured fields were extracted.",
    )


def extract_1099_int_fields(text):
    normalized = normalize_classification_text(text)
    fields = {}
    patterns = {
        "payer_name": [
            r"payer(?:'s)?\s+name\s*[:#-]?\s*([a-z0-9&.,' -]{2,80})",
            r"payer\s+([a-z0-9&.,' -]{2,80})\s+recipient",
        ],
        "interest_income_box_1": [
            rf"(?:box\s*)?1\s+interest income\s*[:#-]?\s*{MONEY_PATTERN}",
            rf"interest income\s*[:#-]?\s*{MONEY_PATTERN}",
        ],
        "early_withdrawal_penalty_box_2": [
            rf"(?:box\s*)?2\s+early withdrawal penalty\s*[:#-]?\s*{MONEY_PATTERN}",
            rf"early withdrawal penalty\s*[:#-]?\s*{MONEY_PATTERN}",
        ],
        "us_savings_bonds_box_3": [
            rf"(?:box\s*)?3\s+interest on u\.?s\.? savings bonds.*?\s*{MONEY_PATTERN}",
            rf"u\.?s\.? savings bonds.*?\s*{MONEY_PATTERN}",
        ],
        "federal_withholding_box_4": [
            rf"(?:box\s*)?4\s+federal income tax withheld\s*[:#-]?\s*{MONEY_PATTERN}",
            rf"federal income tax withheld\s*[:#-]?\s*{MONEY_PATTERN}",
        ],
        "tax_exempt_interest_box_8": [
            rf"(?:box\s*)?8\s+tax-exempt interest\s*[:#-]?\s*{MONEY_PATTERN}",
            rf"tax exempt interest\s*[:#-]?\s*{MONEY_PATTERN}",
        ],
    }
    for field_name, field_patterns in patterns.items():
        value = _find_first(normalized, field_patterns) if field_name == "payer_name" else _find_amount(normalized, field_patterns)
        if value:
            fields[field_name] = _field(value, 0.88)
    return _result_payload(
        "1099_int",
        fields,
        expected_count=6,
        success_note="Structured 1099-INT fields extracted.",
        partial_note="Partial 1099-INT extraction.",
        empty_note="Document classified as 1099-INT, but no structured fields were extracted.",
    )


def extract_1099_div_fields(text):
    normalized = normalize_classification_text(text)
    fields = {}
    patterns = {
        "payer_name": [
            r"payer(?:'s)?\s+name\s*[:#-]?\s*([a-z0-9&.,' -]{2,80})",
            r"payer\s+([a-z0-9&.,' -]{2,80})\s+recipient",
        ],
        "ordinary_dividends_box_1a": [
            rf"(?:box\s*)?1a\s+total ordinary dividends\s*[:#-]?\s*{MONEY_PATTERN}",
            rf"ordinary dividends\s*[:#-]?\s*{MONEY_PATTERN}",
        ],
        "qualified_dividends_box_1b": [
            rf"(?:box\s*)?1b\s+qualified dividends\s*[:#-]?\s*{MONEY_PATTERN}",
            rf"qualified dividends\s*[:#-]?\s*{MONEY_PATTERN}",
        ],
        "capital_gain_distributions_box_2a": [
            rf"(?:box\s*)?2a\s+total capital gain distributions\s*[:#-]?\s*{MONEY_PATTERN}",
            rf"capital gain distributions\s*[:#-]?\s*{MONEY_PATTERN}",
        ],
        "federal_withholding_box_4": [
            rf"(?:box\s*)?4\s+federal income tax withheld\s*[:#-]?\s*{MONEY_PATTERN}",
            rf"federal income tax withheld\s*[:#-]?\s*{MONEY_PATTERN}",
        ],
    }
    for field_name, field_patterns in patterns.items():
        value = _find_first(normalized, field_patterns) if field_name == "payer_name" else _find_amount(normalized, field_patterns)
        if value:
            fields[field_name] = _field(value, 0.88)
    return _result_payload(
        "1099_div",
        fields,
        expected_count=5,
        success_note="Structured 1099-DIV fields extracted.",
        partial_note="Partial 1099-DIV extraction.",
        empty_note="Document classified as 1099-DIV, but no structured fields were extracted.",
    )


def extract_1099_b_fields(text):
    normalized = normalize_classification_text(text)
    fields = {}
    patterns = {
        "payer_name": [
            r"payer(?:'s)?\s+name\s*[:#-]?\s*([a-z0-9&.,' -]{2,80})",
            r"broker\s*[:#-]?\s*([a-z0-9&.,' -]{2,80})",
        ],
        "proceeds": [
            rf"proceeds\s*[:#-]?\s*{MONEY_PATTERN}",
            rf"gross proceeds\s*[:#-]?\s*{MONEY_PATTERN}",
        ],
        "cost_basis": [
            rf"cost(?: or other)? basis\s*[:#-]?\s*{MONEY_PATTERN}",
            rf"basis reported to irs\s*[:#-]?\s*{MONEY_PATTERN}",
        ],
        "federal_withholding_box_4": [
            rf"(?:box\s*)?4\s+federal income tax withheld\s*[:#-]?\s*{MONEY_PATTERN}",
            rf"federal income tax withheld\s*[:#-]?\s*{MONEY_PATTERN}",
        ],
    }
    for field_name, field_patterns in patterns.items():
        value = _find_first(normalized, field_patterns) if field_name == "payer_name" else _find_amount(normalized, field_patterns)
        if value:
            fields[field_name] = _field(value, 0.86)
    if "short term" in normalized:
        fields["short_or_long_term_indicator"] = _field("short term", 0.80)
    elif "long term" in normalized:
        fields["short_or_long_term_indicator"] = _field("long term", 0.80)
    return _result_payload(
        "1099_b",
        fields,
        expected_count=5,
        success_note="Structured 1099-B fields extracted.",
        partial_note="Partial 1099-B extraction.",
        empty_note="Document classified as 1099-B, but no structured fields were extracted.",
    )


def extract_1098_fields(text):
    normalized = normalize_classification_text(text)
    fields = {}
    patterns = {
        "lender_name": [
            r"lender(?:'s)?\s+name\s*[:#-]?\s*([a-z0-9&.,' -]{2,80})",
            r"recipient(?:'s)?\s+lender\s*[:#-]?\s*([a-z0-9&.,' -]{2,80})",
        ],
        "mortgage_interest_box_1": [
            rf"(?:box\s*)?1\s+mortgage interest received.*?\s*{MONEY_PATTERN}",
            rf"mortgage interest(?: received)?\s*[:#-]?\s*{MONEY_PATTERN}",
        ],
        "outstanding_mortgage_principal_box_2": [
            rf"(?:box\s*)?2\s+outstanding mortgage principal\s*[:#-]?\s*{MONEY_PATTERN}",
            rf"outstanding mortgage principal\s*[:#-]?\s*{MONEY_PATTERN}",
        ],
        "points_box_6": [
            rf"(?:box\s*)?6\s+points paid.*?\s*{MONEY_PATTERN}",
            rf"points paid.*?\s*{MONEY_PATTERN}",
        ],
    }
    for field_name, field_patterns in patterns.items():
        value = _find_first(normalized, field_patterns) if field_name == "lender_name" else _find_amount(normalized, field_patterns)
        if value:
            fields[field_name] = _field(value, 0.86)
    return _result_payload(
        "1098",
        fields,
        expected_count=4,
        success_note="Structured 1098 mortgage interest fields extracted.",
        partial_note="Partial 1098 mortgage interest extraction.",
        empty_note="Document classified as 1098 Mortgage Interest, but no structured fields were extracted.",
    )


def extract_k1_fields(text):
    normalized = normalize_classification_text(text)
    fields = {}
    entity_name = _find_first(
        normalized,
        [
            r"entity(?:'s)?\s+name\s*[:#-]?\s*([a-z0-9&.,' -]{2,80})",
            r"partnership(?:'s)?\s+name\s*[:#-]?\s*([a-z0-9&.,' -]{2,80})",
            r"corporation(?:'s)?\s+name\s*[:#-]?\s*([a-z0-9&.,' -]{2,80})",
            r"estate or trust(?:'s)?\s+name\s*[:#-]?\s*([a-z0-9&.,' -]{2,80})",
        ],
    )
    if entity_name:
        fields["entity_name"] = _field(entity_name, 0.75)

    ein = _find_first(normalized, [r"\b(\d{2}-\d{7})\b", r"ein\s*[:#-]?\s*(\d{2}-\d{7})"])
    if ein:
        fields["ein"] = _field(ein, 0.88)

    if "partnership" in normalized:
        fields["entity_type"] = _field("partnership", 0.78)
    elif "s corporation" in normalized or "s-corp" in normalized or "1120-s" in normalized:
        fields["entity_type"] = _field("s_corp", 0.78)
    elif "estate" in normalized or "trust" in normalized:
        fields["entity_type"] = _field("trust", 0.78)

    if fields:
        fields["notes"] = _field("K-1 classified; limited structured extraction available.", 0.65)

    return _result_payload(
        "k1",
        fields,
        expected_count=4,
        success_note="Structured K-1 fields extracted.",
        partial_note="K-1 classified; limited structured extraction available.",
        empty_note="Document classified as K-1, but no structured fields were extracted.",
    )


def extract_structured_fields(document_type, text):
    normalized_type = canonical_structured_type(document_type)
    extractors = {
        "w2": extract_w2_fields,
        "1099_int": extract_1099_int_fields,
        "1099_div": extract_1099_div_fields,
        "1099_b": extract_1099_b_fields,
        "1098": extract_1098_fields,
        "k1": extract_k1_fields,
    }
    extractor = extractors.get(normalized_type)
    if not extractor or not text:
        return None
    return extractor(text)


def run_structured_extraction_for_document(document):
    document_type = canonical_structured_type(document.detected_document_type or document.document_type)
    if document_type not in SUPPORTED_STRUCTURED_TYPES or not document.extracted_text:
        return None

    payload = extract_structured_fields(document_type, document.extracted_text)
    if not payload:
        return None

    now = utc_now()
    job = ExtractionJob(
        document=document,
        tax_return=document.tax_return,
        job_type="structured_extract",
        status="completed",
        attempt_count=1,
        max_attempts=1,
        started_at=now,
        completed_at=now,
    )
    db.session.add(job)
    db.session.flush()

    result = ExtractionResult(
        extraction_job=job,
        document=document,
        tax_return=document.tax_return,
        document_type_detected=payload["document_type"],
        confidence_score=payload["confidence_score"],
        validation_status=payload["validation_status"],
        is_ready_for_review=True,
        extracted_json={
            "fields": payload["fields"],
            "metadata": {
                "extractor": "deterministic_text_rules",
                "confidence_label": payload["confidence_label"],
                "source_text": "document.extracted_text",
            },
        },
        validation_messages_json=[payload["notes"]],
        model_name="deterministic-structured-v1",
    )
    db.session.add(result)
    db.session.flush()
    return result
