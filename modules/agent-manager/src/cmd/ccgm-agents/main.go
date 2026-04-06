// cmd/ccgm-agents/main.go is the entry point for the ccgm-agents binary.
// It prints version info and exits. In future epics, it will launch the TUI.
package main

import (
	"fmt"
	"os"

	tea "github.com/charmbracelet/bubbletea"
)

// version is set at build time via -ldflags="-X main.version=<version>".
var version = "dev"

func main() {
	// Suppress tea import being flagged as unused during scaffold phase.
	_ = tea.NewProgram

	fmt.Fprintf(os.Stdout, "ccgm-agents %s\n", version)
	fmt.Fprintln(os.Stdout, "Claude Code Agent Manager")
	fmt.Fprintln(os.Stdout, "TUI coming in Epic 2.")
}
