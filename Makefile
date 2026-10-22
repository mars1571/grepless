# @map map.install: the four implementations built and tested from one place: go and rust compiled, the unit tests, the conformance of each, the whole suite once, the git hook set up, the benchmark
# On Windows (GNU make run from Git Bash) the compiled programs are name.exe, and the native programs (python3, node) read
# the repository's path as Windows writes it (C:/...), not as an MSYS make gives it (/c/...).
EXE :=
ROOT := $(CURDIR)
ifeq ($(OS),Windows_NT)
EXE := .exe
ROOT := $(shell cygpath -m '$(CURDIR)')
endif

.PHONY: help setup test conformance go rust bench map check

help:
	@echo "make setup        once per clone: git runs .githooks/pre-commit before each commit (the map written again and checked)"
	@echo "make test         the unit tests (Python) and the golden answers of the reference"
	@echo "make go           build go/bin/map, map-guard, map-coach, map-sessions (needs Go 1.22+)"
	@echo "make rust         build rust/target/release/map, map-guard, map-coach, map-sessions (needs cargo)"
	@echo "make conformance  the four implementations against the golden answers (Go and Rust once built)"
	@echo "make map          this repository's own map written and checked, and the example's checked"
	@echo "make check        the whole suite, once per task before the commit: test, map, go, rust, conformance"
	@echo "make bench        the four implementations timed on the synthetic corpus (writes article/data/languages.json)"

setup:
	chmod +x .githooks/pre-commit
	git config core.hooksPath .githooks
	@echo "git now runs .githooks/pre-commit before each commit"

test:
	python3 -m unittest discover -s tests
	python3 tests/conformance.py

go:
	cd go && for b in map map-guard map-coach map-sessions; do go build -o bin/$$b$(EXE) ./cmd/$$b || exit 1; done

rust:
	cd rust && cargo build --release

conformance:
	python3 tests/conformance.py
	python3 tests/conformance.py --impl "node $(ROOT)/node/map.mjs" --guard "node $(ROOT)/node/map-guard.mjs"
	@if [ -x go/bin/map$(EXE) ]; then python3 tests/conformance.py --impl "$(ROOT)/go/bin/map$(EXE)" --guard "$(ROOT)/go/bin/map-guard$(EXE)"; else echo "go: not built (make go)"; fi
	@if [ -x rust/target/release/map$(EXE) ]; then python3 tests/conformance.py --impl "$(ROOT)/rust/target/release/map$(EXE)" --guard "$(ROOT)/rust/target/release/map-guard$(EXE)"; else echo "rust: not built (make rust)"; fi

bench:
	python3 bench/run.py

map:
	python3 python/map.py build && python3 python/map.py check
	cd example && python3 ../python/map.py check

check: go rust
	python3 -m unittest discover -s tests
	$(MAKE) --no-print-directory map conformance
# @end map.install
