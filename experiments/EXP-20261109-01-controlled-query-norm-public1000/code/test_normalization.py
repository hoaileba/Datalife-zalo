from __future__ import annotations

import json
import unittest
from datetime import date

from datamate_agent.question_normalize import Edit, apply_edits, normalize_question


class NormalizationContracts(unittest.TestCase):
    def test_expands_abbreviations_without_rebuilding_question(self) -> None:
        text = apply_edits("Hnay tổng bnhiu đh z?", (Edit(source="Hnay", replacement="Hôm nay"), Edit(source="bnhiu", replacement="bao nhiêu"), Edit(source="đh", replacement="đơn hàng")), names=(), as_of=date(2026, 11, 9))
        self.assertEqual(text, "Hôm nay tổng bao nhiêu đơn hàng z?")

    def test_rejects_order_count_changed_to_money(self) -> None:
        with self.assertRaisesRegex(ValueError, "semantic marker"):
            apply_edits("bnhiu đh", (Edit(source="đh", replacement="doanh thu"),), names=())

    def test_rejects_ambiguous_source_instead_of_changing_both_occurrences(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly once"):
            apply_edits("bnhiu ly, bnhiu đĩa", (Edit(source="bnhiu", replacement="bao nhiêu"),), names=())

    def test_preserves_diacritic_free_spelling_of_named_product(self) -> None:
        with self.assertRaisesRegex(ValueError, "protected name"):
            apply_edits("bnhiu Tien Mat Coffee", (Edit(source="Tien Mat", replacement="tiền mặt"),), names=("Tiền Mặt Coffee",))

    def test_rejects_number_changes(self) -> None:
        with self.assertRaisesRegex(ValueError, "numeric fragment"):
            apply_edits("top 3 món", (Edit(source="3", replacement="5"),), names=())

    def test_rejects_partial_edits_of_identifier(self) -> None:
        with self.assertRaises(ValueError):
            apply_edits("NV007 bán bnhiu", (Edit(source="NV", replacement="nhân viên"),), names=())

    def test_rejects_overlapping_edits(self) -> None:
        with self.assertRaisesRegex(ValueError, "overlap"):
            apply_edits("hôm nay bán bnhiu", (Edit(source="hôm nay", replacement="hôm nay"), Edit(source="nay", replacement="nay")), names=())

    def test_rejects_negation_dropped(self) -> None:
        with self.assertRaisesRegex(ValueError, "semantic marker"):
            apply_edits("không tính hàng trả", (Edit(source="không", replacement="có"),), names=())

    def test_rejects_explicit_unit_replacement(self) -> None:
        with self.assertRaisesRegex(ValueError, "units dropped"):
            apply_edits("bao nhiêu đĩa", (Edit(source="đĩa", replacement="ly"),), names=())

    def test_rejects_added_measure(self) -> None:
        with self.assertRaisesRegex(ValueError, "semantic marker"):
            apply_edits("bnhiu", (Edit(source="bnhiu", replacement="bao nhiêu doanh thu"),), names=())

    def test_rejects_added_negation(self) -> None:
        with self.assertRaisesRegex(ValueError, "semantic marker"):
            apply_edits("bnhiu", (Edit(source="bnhiu", replacement="không bao nhiêu"),), names=())

    def test_rejects_subtraction_reinterpreted_as_supplier(self) -> None:
        with self.assertRaisesRegex(ValueError, "semantic marker"):
            apply_edits("nhập tru bán", (Edit(source="tru", replacement="từ đâu"),), names=())

    def test_rejects_removing_one_of_two_negations(self) -> None:
        with self.assertRaisesRegex(ValueError, "semantic marker"):
            apply_edits("không phải không bán", (Edit(source="không phải không", replacement="không"),), names=())

    def test_rejected_proposal_keeps_original_and_exposes_problem(self) -> None:
        row = {"id": "synthetic", "question": "bnhiu đh", "as_of_date": "2026-11-09"}
        reply = json.dumps({"edits": [{"source": "đh", "replacement": "doanh thu"}], "shape": "number", "count": None, "needs": []})
        result = normalize_question(row, names=(), complete=lambda messages: reply, model="synthetic-test")
        self.assertEqual(result.rewritten, row["question"])
        self.assertIsNotNone(result.problem)
        self.assertIsNone(result.shape)

    def test_valid_metadata_keeps_existing_agent_contract(self) -> None:
        row = {"id": "synthetic", "question": "bnhiu đh", "as_of_date": "2026-11-09"}
        reply = json.dumps({"edits": [{"source": "bnhiu", "replacement": "bao nhiêu"}, {"source": "đh", "replacement": "đơn hàng"}], "shape": "number", "count": None, "needs": []})
        result = normalize_question(row, names=(), complete=lambda messages: reply, model="synthetic-test")
        self.assertEqual(result.rewritten, "bao nhiêu đơn hàng")
        self.assertEqual(result.shape, "number")
        self.assertIsNone(result.problem)


if __name__ == "__main__":
    unittest.main()
