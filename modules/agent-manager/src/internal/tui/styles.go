// styles.go defines lipgloss styles used throughout the TUI.
package tui

import "github.com/charmbracelet/lipgloss"

var (
	// Panel borders
	ActiveBorderStyle   = lipgloss.NewStyle().Border(lipgloss.RoundedBorder()).BorderForeground(lipgloss.Color("62"))
	InactiveBorderStyle = lipgloss.NewStyle().Border(lipgloss.RoundedBorder()).BorderForeground(lipgloss.Color("240"))

	// Status colors
	StatusRunning    = lipgloss.NewStyle().Foreground(lipgloss.Color("42"))  // green
	StatusHanging    = lipgloss.NewStyle().Foreground(lipgloss.Color("214")) // yellow/orange
	StatusCrashed    = lipgloss.NewStyle().Foreground(lipgloss.Color("196")) // red
	StatusStopped    = lipgloss.NewStyle().Foreground(lipgloss.Color("240")) // gray
	StatusRestarting = lipgloss.NewStyle().Foreground(lipgloss.Color("33"))  // blue

	// Table
	HeaderStyle   = lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("252"))
	SelectedStyle = lipgloss.NewStyle().Background(lipgloss.Color("237")).Bold(true)

	// Title
	TitleStyle = lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("62")).Padding(0, 1)
)
