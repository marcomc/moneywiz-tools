"""W09 plans require exact identities and a reviewed fuzzy decision."""

from __future__ import annotations

import csv
import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from write_payees import _approval_from_map, build_merge_plan
from write_plan import PlanValidationError, validate_plan, validate_result


def inventory(*, fuzzy: bool = False) -> dict:
    uuid = "fixture-store"
    return {
        "owner_uri": f"x-coredata://{uuid}/User/p1",
        "source": {"gid": "source", "numeric_id": "2",
                   "name": "Merchant East" if fuzzy else "MERCHANT",
                   "object_uri": f"x-coredata://{uuid}/Payee/p2"},
        "survivor": {"gid": "survivor", "numeric_id": "3", "name": "Merchant",
                     "object_uri": f"x-coredata://{uuid}/Payee/p3"},
        "references": [{"relationship": "transactions", "entity": "WithdrawTransaction",
                        "object_uri": f"x-coredata://{uuid}/WithdrawTransaction/p5"}],
    }


def plan(*, fuzzy: bool = False, approval: dict | None = None) -> dict:
    return build_merge_plan(
        inventory(fuzzy=fuzzy), store_uuid="fixture-store",
        app_identity={"bundle_id": "com.moneywiz.personalfinance",
                      "version": "2026.37.1", "path": "/Applications/MoneyWiz.app",
                      "model_path": "/Applications/MoneyWiz.app/model-48.mom"},
        model_checksum="+6BY8eaTke2jfAd5Bzt5D49JRMZld5o8ZoUW+4G2ElQ=",
        kind="merge_approved_fuzzy_payee" if fuzzy else "merge_exact_payee",
        evidence_note="Reviewed synthetic pair", approval=approval,
    )


def fuzzy_approval() -> dict:
    return {
        "user_id": 1, "left_id": "2", "left_name": "Merchant East",
        "right_id": "3", "right_name": "Merchant",
        "review_decision": "approved", "approved_canonical_id": "3",
        "review_notes": "Same merchant", "map_sha256": "a" * 64,
    }


def test_exact_plan_and_receipt() -> None:
    expected = plan()
    assert validate_plan(expected) == expected
    merge = expected["merge"]
    receipt = {
        "contract_version": 2, "plan_id": expected["plan_id"],
        "plan_digest": expected["plan_digest"], "classification": "applied",
        "verified": True,
        "operations": [{"operation_id": merge["operation_id"], "status": "applied",
                        "source_payee_gid": merge["source"]["gid"],
                        "survivor_payee_gid": merge["survivor"]["gid"],
                        "moved_references": merge["expected_references"],
                        "source_absent": True, "survivor_present": True}],
    }
    assert validate_result(expected, receipt) == receipt
    receipt["operations"][0]["moved_references"] = []
    with pytest.raises(PlanValidationError, match="complete merge"):
        validate_result(expected, receipt)


@pytest.mark.parametrize("fuzzy,source_name", [
    (False, " MERCHANT "), (True, " Merchant East "),
])
def test_plan_preserves_untrimmed_payee_names(fuzzy: bool, source_name: str) -> None:
    selected = inventory(fuzzy=fuzzy)
    selected["source"]["name"] = source_name
    approval = fuzzy_approval() if fuzzy else None
    if approval is not None:
        approval["left_name"] = source_name
    expected = build_merge_plan(
        selected, store_uuid="fixture-store",
        app_identity={"bundle_id": "com.moneywiz.personalfinance",
                      "version": "2026.37.1", "path": "/Applications/MoneyWiz.app",
                      "model_path": "/Applications/MoneyWiz.app/model-48.mom"},
        model_checksum="+6BY8eaTke2jfAd5Bzt5D49JRMZld5o8ZoUW+4G2ElQ=",
        kind="merge_approved_fuzzy_payee" if fuzzy else "merge_exact_payee",
        evidence_note="Reviewed synthetic pair", approval=approval,
    )
    assert validate_plan(expected)["merge"]["source"]["name"] == source_name


@pytest.mark.parametrize("role", ["source", "survivor"])
def test_plan_rejects_whitespace_only_payee_name(role: str) -> None:
    changed = deepcopy(plan())
    changed.pop("plan_digest")
    changed["merge"][role]["name"] = " \t "
    with pytest.raises(PlanValidationError, match=f"merge.{role}.name must be a nonblank"):
        validate_plan(changed)


@pytest.mark.parametrize("change", [
    lambda value: value["merge"]["source"].update(name="Other"),
    lambda value: value["merge"]["source"].update(object_uri="x-coredata://other/Payee/p2"),
    lambda value: value["merge"]["expected_references"].append(
        value["merge"]["expected_references"][0]),
    lambda value: value["merge"].update(approval=fuzzy_approval()),
])
def test_exact_plan_rejects_changed_identity_or_shape(change) -> None:
    value = deepcopy(plan())
    value.pop("plan_digest")
    change(value)
    with pytest.raises(PlanValidationError):
        validate_plan(value)


def test_fuzzy_plan_requires_approved_exact_pair() -> None:
    expected = plan(fuzzy=True, approval=fuzzy_approval())
    assert validate_plan(expected) == expected
    for field, value in (("review_decision", "pending"),
                         ("approved_canonical_id", "2"),
                         ("right_name", "Other")):
        changed = deepcopy(expected)
        changed.pop("plan_digest")
        changed["merge"]["approval"][field] = value
        with pytest.raises(PlanValidationError, match="fuzzy map"):
            validate_plan(changed)


@pytest.mark.parametrize("field", ["left_id", "right_id", "approved_canonical_id"])
def test_fuzzy_plan_rejects_numeric_approval_ids(field: str) -> None:
    changed = deepcopy(plan(fuzzy=True, approval=fuzzy_approval()))
    changed.pop("plan_digest")
    changed["merge"]["approval"][field] = int(changed["merge"]["approval"][field])
    with pytest.raises(PlanValidationError, match="fuzzy map"):
        validate_plan(changed)


@pytest.mark.parametrize("decision,expected", [
    ("approved", True), ("pending", False), ("rejected", False),
])
def test_review_map_admits_only_approved_row(tmp_path: Path,
                                             decision: str, expected: bool) -> None:
    path = tmp_path / "review.csv"
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=(
            "user_id", "similarity", "reason", "left_id", "left_name",
            "right_id", "right_name", "review_decision", "approved_canonical_id",
            "review_notes",
        ))
        writer.writeheader()
        writer.writerow({"user_id": "1", "similarity": "0.9", "reason": "similarity",
                         "left_id": "2", "left_name": "Merchant East",
                         "right_id": "3", "right_name": "Merchant",
                         "review_decision": decision,
                         "approved_canonical_id": "3" if expected else "",
                         "review_notes": "Same merchant" if expected else ""})
    approval = _approval_from_map(path, inventory(fuzzy=True))
    assert (approval is not None) is expected
