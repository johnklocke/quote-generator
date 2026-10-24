"""Builds a complete quote: parse notes, price items, assign a number and dates."""
import secrets
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

from .catalog import Catalog
from .parser import parse_notes
from .pricing import PricedQuote, price_items


@dataclass
class Customer:
    name: str
    email: str = ""
    address: str = ""


@dataclass
class Quote:
    number: str
    issued: str
    valid_until: str
    customer: Customer
    notes: str
    scope_summary: str
    assumptions: list[str]
    questions: list[str]
    priced: PricedQuote
    source: str  # "claude" or "rules"
    terms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def build_quote(customer: Customer, notes: str, catalog: Catalog, today: date | None = None) -> Quote:
    today = today or date.today()
    parsed = parse_notes(notes, catalog)
    priced = price_items(parsed["items"], catalog)
    return Quote(
        number=f"Q-{today:%Y%m%d}-{secrets.token_hex(2).upper()}",
        issued=today.isoformat(),
        valid_until=(today + timedelta(days=int(catalog.pricing.get("valid_days", 30)))).isoformat(),
        customer=customer,
        notes=notes,
        scope_summary=parsed["scope_summary"],
        assumptions=parsed["assumptions"] + priced.notes,
        questions=parsed["questions"],
        priced=priced,
        source=parsed["source"],
        terms=catalog.terms,
    )
