// commandbar.go renders the bottom bar with contextual key binding hints and status messages.
package tui

import (
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

// BarContext identifies which panel is currently focused, controlling which
// hints the command bar displays.
type BarContext string

const (
	ContextAgentList BarContext = "agent-list"
	ContextLogViewer BarContext = "log-viewer"
	ContextModal     BarContext = "modal"
)

const statusClearDelay = 3 * time.Second

// StatusMsg carries a status message to display in the command bar.
type StatusMsg struct {
	Text    string
	IsError bool
}

// ClearStatusMsg signals that the current status message should be cleared.
type ClearStatusMsg struct{}

// CommandBarModel is a Bubble Tea component that renders a contextual command
// bar at the bottom of the screen.
type CommandBarModel struct {
	keys        KeyMap
	context     BarContext
	message     string
	messageErr  bool
	messageTime time.Time
	width       int
}

// NewCommandBarModel returns a CommandBarModel with DefaultKeyMap and the
// agent-list context active.
func NewCommandBarModel(keys KeyMap) CommandBarModel {
	return CommandBarModel{
		keys:    keys,
		context: ContextAgentList,
	}
}

// Init satisfies the tea.Model interface. No I/O is needed on startup.
func (m CommandBarModel) Init() tea.Cmd {
	return nil
}

// Update handles messages relevant to the command bar: window resize, status
// messages, and the auto-clear tick.
func (m CommandBarModel) Update(msg tea.Msg) (CommandBarModel, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width

	case StatusMsg:
		m.message = msg.Text
		m.messageErr = msg.IsError
		m.messageTime = time.Now()
		return m, tea.Tick(statusClearDelay, func(t time.Time) tea.Msg {
			return ClearStatusMsg{}
		})

	case ClearStatusMsg:
		m.message = ""
		m.messageErr = false
	}
	return m, nil
}

// View renders the command bar as a full-width string.
func (m CommandBarModel) View() string {
	bg := lipgloss.NewStyle().
		Background(lipgloss.Color("236")).
		Width(m.width)

	// If there is a status message, show it instead of keybinding hints.
	if m.message != "" {
		color := lipgloss.Color("2") // green for success
		if m.messageErr {
			color = lipgloss.Color("1") // red for error
		}
		msgStyle := lipgloss.NewStyle().
			Background(lipgloss.Color("236")).
			Foreground(color).
			Bold(true).
			PaddingLeft(1)
		return bg.Render(msgStyle.Render(m.message))
	}

	hints := m.hintsForContext()
	return bg.Render(renderHints(hints, m.width))
}

// SetContext updates the focused panel context so the correct hints are shown.
func (m *CommandBarModel) SetContext(ctx BarContext) {
	m.context = ctx
}

// SetMessage displays a status message in the command bar. Callers should also
// send a StatusMsg through the Bubble Tea update loop to trigger auto-clear.
func (m *CommandBarModel) SetMessage(msg string) {
	m.message = msg
	m.messageTime = time.Now()
}

// SetWidth updates the render width (called on terminal resize).
func (m *CommandBarModel) SetWidth(width int) {
	m.width = width
}

// hint is a single key/description pair rendered in the command bar.
type hint struct {
	key  string
	desc string
}

func (m CommandBarModel) hintsForContext() []hint {
	switch m.context {
	case ContextLogViewer:
		return []hint{
			{key: "j/k", desc: "scroll"},
			{key: "e", desc: "export"},
			{key: "tab", desc: "agents"},
			{key: "?", desc: "help"},
			{key: "q", desc: "quit"},
		}
	case ContextModal:
		return []hint{
			{key: "enter", desc: "confirm"},
			{key: "esc", desc: "cancel"},
		}
	default: // ContextAgentList
		return []hint{
			{key: "n", desc: "new"},
			{key: "a", desc: "focus"},
			{key: "s", desc: "stop"},
			{key: "r", desc: "restart"},
			{key: "x", desc: "kill"},
			{key: "/", desc: "filter"},
			{key: "?", desc: "help"},
			{key: "q", desc: "quit"},
		}
	}
}

// renderHints builds the hint string from key/desc pairs using Lip Gloss styles.
func renderHints(hints []hint, width int) string {
	keyStyle := lipgloss.NewStyle().
		Bold(true).
		Foreground(lipgloss.Color("0")).
		Background(lipgloss.Color("62")).
		PaddingLeft(1).
		PaddingRight(1)

	descStyle := lipgloss.NewStyle().
		Foreground(lipgloss.Color("252")).
		Background(lipgloss.Color("236")).
		PaddingRight(1)

	var parts []string
	for _, h := range hints {
		parts = append(parts, keyStyle.Render(h.key)+descStyle.Render(h.desc))
	}

	content := " " + strings.Join(parts, " ")
	_ = width // width is applied by the outer bg style
	return content
}
