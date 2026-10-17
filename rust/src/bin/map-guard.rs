// @map map.guard.decide: the map-guard command: the hook for five agents, from the mapcore crate
fn main() {
    mapcore::guard::main(std::env::args().skip(1).collect());
}
// @end map.guard.decide
