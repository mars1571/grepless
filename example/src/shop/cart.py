# @map shop.cart.model: the cart: its lines, adding and removing articles, and what it holds
from shop.prices import coupon_percent, line_discount, price


class Cart:
    """A cart of lines (code, quantity); a code added twice adds to its line."""

    def __init__(self):
        self.lines = {}
        self.coupon = None

    def add(self, code, quantity=1):
        price(code)                                    # unknown codes fail here, before the line exists
        self.lines[code] = self.lines.get(code, 0) + quantity

    def remove(self, code):
        self.lines.pop(code, None)

    def is_empty(self):
        return not self.lines
# @end shop.cart.model


# @map shop.cart.totals: the totals: each line's amount and discount, the coupon on the rest, and the sum in cents
def line_total(code, quantity):
    return price(code) * quantity - line_discount(code, quantity)


def total(cart):
    """The cart's total in cents: the lines after their discounts, then the coupon's percent off the rest."""
    subtotal = sum(line_total(code, q) for code, q in cart.lines.items())
    return subtotal - subtotal * coupon_percent(cart.coupon) // 100


def summary(cart):
    """[(code, quantity, amount in cents)] for the page, plus the total."""
    return [(code, q, line_total(code, q)) for code, q in cart.lines.items()], total(cart)
# @end shop.cart.totals
