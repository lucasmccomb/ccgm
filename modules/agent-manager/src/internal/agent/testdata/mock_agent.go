// mock_agent is a test helper binary used by the agent package tests.
//
// Usage:
//
//	mock_agent [--exit-code N] [--delay DURATION] [--lines N]
//
// It prints N lines to stdout (and one line to stderr), waits delay, then
// exits with exit-code.
//
// Default: 5 lines, 0 delay, exit code 0.
package main

import (
	"flag"
	"fmt"
	"os"
	"time"
)

func main() {
	exitCode := flag.Int("exit-code", 0, "process exit code")
	delay := flag.Duration("delay", 0, "delay before exit (e.g. 100ms, 2s)")
	lines := flag.Int("lines", 5, "number of lines to print to stdout")
	flag.Parse()

	for i := 0; i < *lines; i++ {
		fmt.Fprintf(os.Stdout, "line %d\n", i+1)
	}
	fmt.Fprintln(os.Stderr, "mock_agent: stderr line")

	if *delay > 0 {
		time.Sleep(*delay)
	}

	os.Exit(*exitCode)
}
