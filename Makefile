# @map map.install: the four implementations built and tested from one place: go and rust compiled, the unit tests, the conformance of each, the benchmark
.PHONY: help test conformance go rust bench map check

help:
	@echo "make test         the unit tests (Python) and the golden answers of the reference"
	@echo "make go           build go/bin/map, map-guard, map-coach, map-sessions (needs Go 1.22+)"
	@echo "make rust         build rust/target/release/map, map-guard, map-coach, map-sessions (needs cargo)"
	@echo "make conformance  every built implementation against the golden answers"
	@echo "make bench        the four implementations timed on the synthetic corpus (article/data/languages.json)"
	@echo "make map          this repository's own map written and checked"

test:
	python3 -m unittest discover -s tests
	python3 tests/conformance.py

go:
	cd go && go build -o bin/map ./cmd/map && go build -o bin/map-guard ./cmd/map-guard && go build -o bin/map-coach ./cmd/map-coach && go build -o bin/map-sessions ./cmd/map-sessions

rust:
	cd rust && cargo build --release

conformance:
	python3 tests/conformance.py --impl "node $(CURDIR)/node/map.mjs" --guard "node $(CURDIR)/node/map-guard.mjs"
	@[ ! -x go/bin/map ] || python3 tests/conformance.py --impl "$(CURDIR)/go/bin/map" --guard "$(CURDIR)/go/bin/map-guard"
	@[ ! -x rust/target/release/map ] || python3 tests/conformance.py --impl "$(CURDIR)/rust/target/release/map" --guard "$(CURDIR)/rust/target/release/map-guard"

bench:
	python3 bench/run.py

map:
	python3 python/map.py build && python3 python/map.py check
# @end map.install
