Trả góp:
- `installment_remaining("2026-06-01", customer=...)`: tiền góp chưa trả, gồm kỳ chưa tới hạn. `installment_overdue("2026-06-01")`: tiền kỳ quá hạn. `overdue_customers("2026-06-01")`: số khách quá hạn. `installments_due("Tên khách", "2026-06-01")`: số kỳ đã tới hạn.
- `debt_at`, `debtor_count`, `debtors`, `debt_aged` đã gồm sổ nợ và sổ góp.
