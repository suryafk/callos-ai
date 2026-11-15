"""Deterministic mock catalog and customer list (loaded from /data)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass(frozen=True)
class Product:
    product_id: str
    name: str
    unit: str
    unit_price_inr: int
    unit_cost_inr: int
    inventory: int
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class Customer:
    customer_id: str
    name: str
    city: str
    aliases: tuple[str, ...]


def _norm(text: str) -> str:
    return " ".join(text.lower().strip().split())


class Catalog:
    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        products = json.loads((data_dir / "products.json").read_text())
        customers = json.loads((data_dir / "customers.json").read_text())
        self.products = {
            p["product_id"]: Product(**{**p, "aliases": tuple(p.get("aliases", []))})
            for p in products
        }
        self.customers = {
            c["customer_id"]: Customer(**{**c, "aliases": tuple(c.get("aliases", []))})
            for c in customers
        }

    def find_product(self, product_id: Optional[str] = None, name: Optional[str] = None) -> Optional[Product]:
        if product_id:
            p = self.products.get(_norm(product_id))
            if p:
                return p
            name = name or product_id  # model may put a name in product_id
        if name:
            n = _norm(name)
            for p in self.products.values():
                if n == _norm(p.name) or n in (_norm(a) for a in p.aliases):
                    return p
        return None

    def find_customer(self, customer_id: Optional[str] = None, name: Optional[str] = None) -> Optional[Customer]:
        if customer_id:
            c = self.customers.get(_norm(customer_id))
            if c:
                return c
            name = name or customer_id
        if name:
            n = _norm(name)
            for c in self.customers.values():
                if n == _norm(c.name) or n in (_norm(a) for a in c.aliases):
                    return c
        return None

    def product_names(self) -> str:
        return ", ".join(f"{p.name} at {p.unit_price_inr} rupees" for p in self.products.values())

    def customer_names(self) -> str:
        return ", ".join(c.name for c in self.customers.values())


catalog = Catalog()
