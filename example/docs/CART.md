# The cart

A cart holds lines of articles (`shop.cart.model`). Its total (`shop.cart.totals`) adds each line's
amount after its discount, then takes the coupon's percentage off the rest.

## Discounts

Two rules, both in `src/shop/prices.py`:

- **Bulk**: ten apples or more take 15 % off each apple.
- **Coupon**: `WELCOME` takes 5 % off the whole cart, after the bulk discounts.

## The page

The page (`web.cart.render`) draws one row per line and the total, and applies a coupon typed in the
field (`web.cart.events`).
