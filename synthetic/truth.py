"""Ground truth helpers for the household eval: truth -> extractions, and planted vs detected issues.

Needs backend/ on sys.path.
"""

from dataclasses import dataclass, field
from typing import Any

from schemas.documents import FIELD_MODELS, DocumentExtraction
from schemas.issues import Issue
from vision.text import mask_identity_number

# Detected issue types that correspond to planted errors (others are reported separately).
SCORED_TYPES = {"name_mismatch", "dob_mismatch", "not_on_ration_card", "missing_document", "expired"}


def extractions_from_truth(gt: dict[str, Any]) -> list[DocumentExtraction]:
    """What a perfect reader would return for a household's documents (identity numbers masked)."""
    out = []
    for d in gt["documents"]:
        fields = dict(d["fields"])
        if "id_number" in fields:
            fields["id_number"] = mask_identity_number(fields["id_number"])
        if d["type"] == "ration_card":
            fields.setdefault("card_colour", None)
        out.append(DocumentExtraction(document_id=d["id"], doc_type=d["type"],
                                      fields=FIELD_MODELS[d["type"]].model_validate(fields)))
    return out


def member_map(gt: dict[str, Any]) -> dict[str, str]:
    """Household member id (r1, r2, ... in ration-card order) -> ground-truth member id."""
    card = next((d for d in gt["documents"] if d["type"] == "ration_card"), None)
    if card is None:
        return {}
    by_name = {f"{m['given']['en']} {m['middle']['en']} {m['surname']['en']}": m["id"] for m in gt["members"]}
    return {f"r{i}": by_name.get(row["name_en"], "?") for i, row in enumerate(card["fields"]["members"], 1)}


@dataclass
class IssueMatch:
    caught: list[tuple[dict[str, Any], Issue]] = field(default_factory=list)  # (planted, detected)
    missed: list[dict[str, Any]] = field(default_factory=list)
    false_alarms: list[Issue] = field(default_factory=list)
    other: list[Issue] = field(default_factory=list)  # unreadable, duplicate_merged, info notes


def _matches(p: dict[str, Any], i: Issue, members: dict[str, str]) -> bool:
    if p["type"] != i.type:
        return False
    if p["type"] == "missing_document":
        if i.severity != "blocker" or i.evidence.get("document_type") != p["expected"]:
            return False
        return p["expected"] == "income_certificate" or members.get(i.member_id or "") == p["member_id"]
    if p["type"] == "name_mismatch":
        return p["documents"][0] in i.documents  # the document with the variant spelling
    return bool(set(p["documents"]) & set(i.documents))


def match_issues(gt: dict[str, Any], issues: list[Issue]) -> IssueMatch:
    members = member_map(gt)
    result = IssueMatch()
    used: set[int] = set()
    for p in gt["planted_errors"]:
        hit = next((k for k, i in enumerate(issues) if k not in used and _matches(p, i, members)), None)
        if hit is None:
            result.missed.append(p)
        else:
            used.add(hit)
            result.caught.append((p, issues[hit]))
    for k, i in enumerate(issues):
        if k in used:
            continue
        if i.type in SCORED_TYPES and i.severity in ("blocker", "warning"):
            result.false_alarms.append(i)
        else:
            result.other.append(i)
    return result
