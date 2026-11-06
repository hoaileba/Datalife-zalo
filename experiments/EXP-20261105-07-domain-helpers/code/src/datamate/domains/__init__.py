from __future__ import annotations

import json
from pathlib import Path

from .baby import BABY_HELPERS, BabyMixin
from .delivery import DELIVERY_HELPERS, DeliveryMixin
from .pharmacy import PHARMACY_HELPERS, PharmacyMixin
from .phone import PHONE_HELPERS, PhoneMixin
from .repair import REPAIR_HELPERS, RepairMixin

DOMAIN_HELPERS = DELIVERY_HELPERS + PHARMACY_HELPERS + PHONE_HELPERS + REPAIR_HELPERS + BABY_HELPERS
DOMAIN_MIXINS = (DeliveryMixin, PharmacyMixin, PhoneMixin, RepairMixin, BabyMixin)
DOMAIN_REQUIREMENTS = {
    "delivery": ("delivery_round", "delivery_date"),
    "pharmacy": ("lot_sold",),
    "phone": ("machine_id",),
    "installment": ("installment_terms", "installment_monthly"),
    "warranty": ("warranty_fault", "machine_id"),
    "repair": ("vehicle", "repair_job"),
    "baby": ("item_size",),
}


def domains_of(norm_dir: Path) -> tuple[str, ...]:
    """Các ngành shop có đủ khái niệm, đọc từ concepts.json."""
    path = Path(norm_dir) / "concepts.json"
    concepts = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return tuple(name for name, needed in DOMAIN_REQUIREMENTS.items() if any(all(item in found for item in needed) for found in concepts.values()))
