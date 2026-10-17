// @map map.cli.init: the map command: build, check, brief, ask and the rest, from the mapcore crate
fn main() {
    mapcore::cli::main(std::env::args().skip(1).collect());
}
// @end map.cli.init
