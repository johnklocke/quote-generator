"""Turns requested line items into a priced quote.

All math happens here, in plain Python, from the price list. The AI only
decides WHICH services and quantities apply; it never sets a price.
"""
from dataclasses import dataclass, field

from .catalog import Catalog


@dataclass
class Line:
    code: str
    name: str
    quantity: float
    unit: str
    unit_price: float
    amount: float
    recurring: bool
    note: str = ""


@dataclass
class PricedQuote:
    lines: list[Line]
    subtotal: float
    discount: float
    discount_label: str
    minimum_adjustment: float
    tax: float
    total: float
    notes: list[str] = field(default_factory=list)


def money(x: float) -> float:
    return round(x + 1e-9, 2)


def price_items(items: list[dict], catalog: Catalog) -> PricedQuote:
    """items: [{"code": "RX", "quantity": 12, "note": "..."}]"""
    rules = catalog.pricing
    lines, notes, seen = [], [], set()
    for item in items:
        service = catalog.services.get(item["code"])
        if service is None or item["code"] in seen:
            continue  # unknown or duplicate code: skip rather than guess
        seen.add(item["code"])
        qty = 1.0 if service.unit == "flat" else max(float(item.get("quantity") or 1), 1.0)
        lines.append(Line(
            code=service.code, name=service.name, quantity=qty, unit=service.unit,
            unit_price=service.price, amount=money(qty * service.price),
            recurring=service.recurring, note=item.get("note", ""),
        ))

    subtotal = money(sum(line.amount for line in lines))

    discount, discount_label = 0.0, ""
    bundle = rules.get("bundle_discount") or {}
    if bundle and len(lines) >= bundle.get("min_services", 99):
        one_time = sum(line.amount for line in lines if not line.recurring)
        discount = money(one_time * bundle["percent"] / 100)
        discount_label = f"Bundle discount ({bundle['percent']}% off one-time services)"

    after_discount = subtotal - discount
    minimum = float(rules.get("minimum_job", 0))
    minimum_adjustment = 0.0
    if lines and after_discount < minimum:
        minimum_adjustment = money(minimum - after_discount)
        notes.append(f"Minimum job charge of ${minimum:,.2f} applied.")

    taxable = after_discount + minimum_adjustment
    tax = money(taxable * float(rules.get("tax_rate", 0)))
    total = money(taxable + tax)
    return PricedQuote(lines, subtotal, discount, discount_label, minimum_adjustment, tax, total, notes)
