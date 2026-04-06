// help.go implements the help overlay that shows all keybindings organized by category.
package tui

import (
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

// HelpModel is a Bubble Tea component that renders a centered modal overlay
// listing all keybindings grouped by category. The parent model is responsible
// for layering this on top of other content when Visible() returns true.
type HelpModel struct {
	keys    KeyMap
	visible bool
	width   int
	height  int
}

// NewHelpModel returns a HelpModel with the given key map. The overlay starts hidden.
func NewHelpModel(keys KeyMap) HelpModel {
	return HelpModel{keys: keys}
}

// Update handles keyboard messages to toggle or dismiss the overlay.
func (m HelpModel) Update(msg tea.Msg) (HelpModel, tea.Cmd) {
	if !m.visible {
		return m, nil
	}
	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch msg.String() {
		case "?", "esc":
			m.visible = false
		}
	}
	return m, nil
}

// View renders the centered help modal. If the overlay is not visible it
// returns an empty string.
func (m HelpModel) View() string {
	if !m.visible {
		return ""
	}

	titleStyle := lipgloss.NewStyle().
		Bold(true).
		Foreground(lipgloss.Color("12")).
		MarginBottom(1)

	categoryStyle := lipgloss.NewStyle().
		Bold(true).
		Foreground(lipgloss.Color("11"))

	keyStyle := lipgloss.NewStyle().
		Bold(true).
		Foreground(lipgloss.Color("15"))

	descStyle := lipgloss.NewStyle().
		Foreground(lipgloss.Color("244"))

	boxStyle := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(lipgloss.Color("62")).
		Padding(1, 3).
		Background(lipgloss.Color("235"))

	var sb strings.Builder

	sb.WriteString(titleStyle.Render("Keybindings"))
	sb.WriteString("\n")

	type entry struct {
		key  string
		desc string
	}
	type category struct {
		name    string
		entries []entry
	}

	categories := []category{
		{
			name: "Navigation",
			entries: []entry{
				{"j/↓", "Move down"},
				{"k/↑", "Move up"},
				{"tab", "Switch panel"},
				{"/", "Filter agents"},
				{"esc", "Cancel/back"},
			},
		},
		{
			name: "Agent Actions",
			entries: []entry{
				{"n", "New agent"},
				{"s", "Stop agent"},
				{"r", "Restart agent"},
				{"x", "Kill agent"},
			},
		},
		{
			name: "Log Actions",
			entries: []entry{
				{"e", "Export logs"},
			},
		},
		{
			name: "General",
			entries: []entry{
				{"?", "Toggle help"},
				{"q", "Quit"},
			},
		},
	}

	for i, cat := range categories {
		if i > 0 {
			sb.WriteString("\n")
		}
		sb.WriteString(categoryStyle.Render(cat.name))
		sb.WriteString("\n")
		for _, e := range cat.entries {
			sb.WriteString("  ")
			sb.WriteString(keyStyle.Render(padKey(e.key, 6)))
			sb.WriteString(" ")
			sb.WriteString(descStyle.Render(e.desc))
			sb.WriteString("\n")
		}
	}

	content := strings.TrimRight(sb.String(), "\n")
	box := boxStyle.Render(content)

	// Center the box in the available terminal space.
	return lipgloss.Place(m.width, m.height, lipgloss.Center, lipgloss.Center, box)
}

// Toggle flips the visible state of the overlay.
func (m *HelpModel) Toggle() {
	m.visible = !m.visible
}

// Visible reports whether the overlay is currently shown.
func (m HelpModel) Visible() bool {
	return m.visible
}

// SetSize stores the terminal dimensions used to center the overlay.
func (m *HelpModel) SetSize(width, height int) {
	m.width = width
	m.height = height
}

// padKey right-pads a key string to the given width for column alignment.
func padKey(s string, width int) string {
	if len(s) >= width {
		return s
	}
	return s + strings.Repeat(" ", width-len(s))
}
