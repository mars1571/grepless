// @map tests.format.money: money text with two decimals and the currency, units in the singular and the plural
import assert from 'node:assert';
import { money, units } from '../src/web/format.js';

assert.equal(money(1234), '$12.34');
assert.equal(units(1), '1 unit');
assert.equal(units(3), '3 units');
console.log('format ok');
// @end tests.format.money
