"""Product catalog helpers."""

from dataclasses import dataclass


@dataclass
class Product:
    sku: str
    name: str
    price_cents: int
    in_stock: bool = True


def page(items, page_number, page_size):
    """Return one 1-indexed page of items."""
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    start = page_number * page_size
    return items[start:start + page_size]


def total_cents(items):
    return sum(item.price_cents for item in items)


def in_stock(items):
    return [item for item in items if item.in_stock]


def search(items, text):
    needle = text.lower()
    return [item for item in items if needle in item.name.lower()]
