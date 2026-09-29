"""
The company-editable pick-lists (Settings > Lists): payment terms, delivery
terms and supplier types.

`DEFAULT_LISTS` is what a new company starts with — the same values the app
used to hard-code — and `seed_defaults` writes them. Called wherever a
company is created (platform console onboarding, the demo seed); migration
c7e2a9f4b1d3 seeded the companies that existed before this module.
"""

from __future__ import annotations

from typing import Union
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.models.identity import COMPANY_LIST_KEYS

DEFAULT_LISTS: dict[str, list[str]] = {
    "payment_terms": ["Advance", "15 Days", "30 Days", "45 Days", "Cash on Delivery"],
    "delivery_terms": ["FOR", "Ex-Works", "Door Delivery", "To Pay"],
    "supplier_type": ["Manufacturer", "Distributor", "Online", "Local Supplier", "Importer"],
}
assert set(DEFAULT_LISTS) == set(COMPANY_LIST_KEYS)

#: Shown in Settings next to each list.
LIST_LABELS = {
    "payment_terms": "Payment terms",
    "delivery_terms": "Delivery terms",
    "supplier_type": "Supplier types",
}


async def seed_defaults(db: Union[AsyncSession, AsyncConnection], company_id: Union[UUID, str]) -> None:
    for key, values in DEFAULT_LISTS.items():
        for i, value in enumerate(values):
            await db.execute(
                text(
                    "INSERT INTO company_lists (company_id, list_key, value, sort_order) "
                    "VALUES (:c, :k, :v, :o) ON CONFLICT DO NOTHING"
                ),
                {"c": company_id, "k": key, "v": value, "o": i * 10},
            )
