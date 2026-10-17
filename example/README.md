# Example: a tagged shop

A small project, tagged, to try the map on. From this folder:

```sh
python3 ../python/map.py build                      # map.yaml and map/<area>.yaml
python3 ../python/map.py check                      # the rules; exit 1 when the map is out of date
python3 ../python/map.py brief cart discount        # where a task about discounts starts
python3 ../python/map.py ask shop.cart.totals total 'src/web/cart.js' 'docs/CART.md#discounts'
python3 ../python/map.py recipe new-discount        # the steps of a change across layers
python3 -m unittest discover -s tests        # the shop's tests (the page's: node tests/format.test.js)
```
