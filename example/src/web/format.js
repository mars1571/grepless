// @map web.format.money: cents as money text in the shop's currency, and a quantity with its unit
export function money(cents) {
  return (cents / 100).toLocaleString('en-US', { style: 'currency', currency: 'USD' });
}

export function units(quantity) {
  return quantity === 1 ? '1 unit' : `${quantity} units`;
}
// @end web.format.money
