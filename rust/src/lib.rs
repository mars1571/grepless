// @map map.core.rules: the Rust crate: the core modules of the map and the guard, shared by the four binaries
//! The Rust version of the code map: python/map.py's commands with the same answers (tests/conformance.py), and
//! map-guard's refusals for five agents. `map`, `map-guard`, `map-coach` and `map-sessions` are the binaries.
pub mod ask;
pub mod brief;
pub mod cli;
pub mod config;
pub mod decl;
pub mod files;
pub mod guard;
pub mod imports;
pub mod parse;
pub mod query;
pub mod recipes;
pub mod write;
// @end map.core.rules
