// @map web.cart.render: the cart drawn on the page: one row per line, the total, and the coupon field
import { money, units } from './format.js';

export function render(summary, total) {
  const rows = summary.map(([code, quantity, amount]) =>
    `<tr><td>${code}</td><td>${units(quantity)}</td><td class="amount">${money(amount)}</td></tr>`);
  document.getElementById('cart-lines').innerHTML = rows.join('');
  document.getElementById('cart-total').textContent = money(total);
}

export function readCoupon() {
  return document.getElementById('coupon').value.trim();
}
// @end web.cart.render

// @map web.cart.events: what the page does on a click: the coupon applied, the cart drawn again
export function wire(apply) {
  document.getElementById('apply-coupon').addEventListener('click', () => apply(readCoupon()));
}
// @end web.cart.events
