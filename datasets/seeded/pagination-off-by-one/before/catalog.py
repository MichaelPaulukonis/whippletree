"""Product catalog helpers."""

from dataclasses import dataclass


@dataclass
class Product:
    sku: str
    name: str
    price_cents: int


def page(items, page_number, page_size):
    start = (page_number - 1) * page_size
    return items[start:start + page_size]


def total_cents(items):
    total = 0
    for item in items:
        total += item.price_cents
    return total
