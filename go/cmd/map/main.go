// @map map.cli.init: the map command: build, check, brief, ask and the rest, from the mapcore package
package main

import (
	"os"

	"github.com/mars1571/grepless/go/internal/mapcore"
)

func main() { mapcore.Main(os.Args[1:]) }
// @end map.cli.init
