def calculate_discount(price: float, discount_percent: float) -> float:
    """Apply a percentage discount to a price."""
    if discount_percent > 100:
        raise ValueError("Discount cannot exceed 100 percent")
    if discount_percent < 0:
        raise ValueError("Discount cannot be negative")
    return price - (price * discount_percent / 100)