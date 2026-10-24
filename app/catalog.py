"""Loads the company profile and price list from data/company.yaml."""
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).parent.parent / "data" / "company.yaml"


@dataclass
class Service:
    code: str
    name: str
    unit: str
    price: float
    keywords: list[str] = field(default_factory=list)
    qty_words: list[str] = field(default_factory=list)
    recurring: bool = False


@dataclass
class Catalog:
    company: dict
    pricing: dict
    terms: list[str]
    services: dict[str, Service]


@lru_cache
def load_catalog(path: str | None = None) -> Catalog:
    raw = yaml.safe_load(Path(path or os.getenv("CATALOG_PATH", DEFAULT_PATH)).read_text())
    services = {s["code"]: Service(**s) for s in raw["services"]}
    return Catalog(company=raw["company"], pricing=raw["pricing"], terms=raw.get("terms", []), services=services)
