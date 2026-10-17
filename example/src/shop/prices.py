# @map shop.prices.list: the price of each article, by its code, in cents
PRICES = {
    'apple': 120,
    'bread': 250,
    'milk': 180,
    'cheese': 640,
}


def price(code):
    """The price of an article in cents; a KeyError when the code is unknown."""
    return PRICES[code]
# @end shop.prices.list


# @map shop.prices.discounts: the discount rules: a percentage past a quantity, and a coupon on the whole cart
BULK = {'apple': (10, 15)}        # code: (from this quantity, percent off each)
COUPONS = {'WELCOME': 5}          # coupon: percent off the whole cart


def line_discount(code, quantity):
    """Cents taken off a line: the bulk percentage once the quantity is reached, else nothing."""
    if code in BULK and quantity >= BULK[code][0]:
        return price(code) * quantity * BULK[code][1] // 100
    return 0


def coupon_percent(coupon):
    return COUPONS.get((coupon or '').upper(), 0)
# @end shop.prices.discounts
