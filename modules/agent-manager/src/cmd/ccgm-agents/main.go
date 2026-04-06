// cmd/ccgm-agents/main.go is the entry point for the ccgm-agents binary.
package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"

	tea "github.com/charmbracelet/bubbletea"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/agent"
	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/config"
	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/tui"
)

// version is set at build time via -ldflags="-X main.version=<version>".
var version = "dev"

func main() {
	cfgPath := flag.String("config", "", "path to config file (default: ~/.ccgm/agent-manager/config.json)")
	showVersion := flag.Bool("version", false, "print version and exit")
	flag.Parse()

	if *showVersion {
		fmt.Fprintf(os.Stdout, "ccgm-agents %s\n", version)
		os.Exit(0)
	}

	// Resolve config path.
	if *cfgPath == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			home = "."
		}
		*cfgPath = filepath.Join(home, ".ccgm", "agent-manager", "config.json")
	}

	// Load or create default config.
	cfg, err := config.LoadConfig(*cfgPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "ccgm-agents: load config: %v\n", err)
		os.Exit(1)
	}

	// Initialize data directories.
	if err := config.InitDataDir(cfg.DataDir); err != nil {
		fmt.Fprintf(os.Stderr, "ccgm-agents: init data dir: %v\n", err)
		os.Exit(1)
	}

	// Create the agent manager and attempt re-attachment.
	mgr := agent.NewAgentManager(cfg.DataDir, cfg)
	if err := mgr.ReattachFromState(); err != nil {
		// Non-fatal: log and continue.
		fmt.Fprintf(os.Stderr, "ccgm-agents: reattach warning: %v\n", err)
	}

	// Build and run the TUI.
	app := tui.NewApp(mgr, cfg)
	p := tea.NewProgram(app, tea.WithAltScreen())
	if _, err := p.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "ccgm-agents: %v\n", err)
		os.Exit(1)
	}

	// On clean exit: save agent state for future re-attachment.
	if err := mgr.SaveState(); err != nil {
		fmt.Fprintf(os.Stderr, "ccgm-agents: save state: %v\n", err)
	}
}
