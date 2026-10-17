# @map tests.cart.totals: a cart's total adds the lines and takes the discounts off
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from shop.cart import Cart, total  # noqa: E402


class Totals(unittest.TestCase):
    def test_lines_add_up(self):
        cart = Cart()
        cart.add('apple', 2)
        cart.add('bread')
        self.assertEqual(total(cart), 2 * 120 + 250)

    def test_unknown_code_is_refused(self):
        with self.assertRaises(KeyError):
            Cart().add('caviar')
# @end tests.cart.totals


# @map tests.cart.discounts: the bulk discount past the quantity, and the coupon on the whole cart
class Discounts(unittest.TestCase):
    def test_bulk_apples(self):
        cart = Cart()
        cart.add('apple', 10)
        self.assertEqual(total(cart), 1200 - 180)

    def test_coupon(self):
        cart = Cart()
        cart.add('cheese')
        cart.coupon = 'welcome'
        self.assertEqual(total(cart), 640 - 32)


if __name__ == '__main__':
    unittest.main()
# @end tests.cart.discounts
