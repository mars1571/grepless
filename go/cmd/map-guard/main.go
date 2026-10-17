// @map map.guard.decide: the map-guard command: the hook for five agents, from the guard package
package main

import (
	"os"

	"github.com/mars1571/grepless/go/internal/guard"
)

func main() { guard.Main(os.Args[1:]) }
// @end map.guard.decide
