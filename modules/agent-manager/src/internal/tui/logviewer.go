// logviewer.go renders the scrollable log stream for the selected agent.
// It uses bubbles/viewport for scrollable content and maintains a ring buffer
// to cap memory usage regardless of how much output an agent produces.
package tui

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/bubbles/viewport"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

const defaultMaxLines = 10_000

// logViewerStyles holds all Lip Gloss styles used by LogViewerModel.
// Styles are derived once and reused to avoid per-render allocations.
var logViewerStyles = struct {
	title      lipgloss.Style
	border     lipgloss.Style
	stderr     lipgloss.Style
	timestamp  lipgloss.Style
	empty      lipgloss.Style
	scrollHint lipgloss.Style
}{
	title: lipgloss.NewStyle().
		Bold(true).
		Foreground(lipgloss.Color("212")),
	border: lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(lipgloss.Color("241")),
	stderr: lipgloss.NewStyle().
		Foreground(lipgloss.Color("196")),
	timestamp: lipgloss.NewStyle().
		Foreground(lipgloss.Color("243")),
	empty: lipgloss.NewStyle().
		Foreground(lipgloss.Color("243")).
		Italic(true),
	scrollHint: lipgloss.NewStyle().
		Foreground(lipgloss.Color("243")),
}

// LogLinesMsg is dispatched (typically by a log collector goroutine) to deliver
// new log lines for a specific agent. The TUI root model should forward this
// message to LogViewerModel.Update.
type LogLinesMsg struct {
	AgentID string
	Lines   []LogDisplayLine
}

// LogViewerModel is a Bubble Tea component that renders a scrollable,
// auto-following log panel for the currently selected agent.
type LogViewerModel struct {
	agentID    string
	agentName  string
	buf        *RingBuffer
	viewport   viewport.Model
	autoScroll bool
	focused    bool
	width      int
	height     int
}

// NewLogViewerModel returns a LogViewerModel with sensible defaults.
// Call SetSize before the first render to give the viewport real dimensions.
func NewLogViewerModel() LogViewerModel {
	vp := viewport.New(80, 24)
	vp.KeyMap = viewport.DefaultKeyMap()
	return LogViewerModel{
		buf:        NewRingBuffer(defaultMaxLines),
		viewport:   vp,
		autoScroll: true,
	}
}

// Init satisfies tea.Model. No initial command is needed.
func (m LogViewerModel) Init() tea.Cmd {
	return nil
}

// Update handles keyboard input, incoming log lines, and window resize events.
func (m LogViewerModel) Update(msg tea.Msg) (LogViewerModel, tea.Cmd) {
	var cmds []tea.Cmd

	switch msg := msg.(type) {
	case tea.KeyMsg:
		if !m.focused {
			break
		}
		wasAtBottom := m.viewport.AtBottom()
		var vpCmd tea.Cmd
		m.viewport, vpCmd = m.viewport.Update(msg)
		if vpCmd != nil {
			cmds = append(cmds, vpCmd)
		}
		// If the user scrolled up, disable auto-scroll.
		// If they reached the bottom again, re-enable it.
		if !wasAtBottom || !m.viewport.AtBottom() {
			m.autoScroll = m.viewport.AtBottom()
		}

	case tea.WindowSizeMsg:
		m.SetSize(msg.Width, msg.Height)

	case LogLinesMsg:
		if msg.AgentID != m.agentID {
			break
		}
		m.buf.Add(msg.Lines...)
		m.refreshViewport()
		if m.autoScroll {
			m.viewport.GotoBottom()
		}
	}

	return m, tea.Batch(cmds...)
}

// View renders the log panel, including the title bar and scrollable content.
func (m LogViewerModel) View() string {
	titleStr := m.titleString()
	hint := m.scrollHint()

	// Reserve vertical space: 2 lines for title and scroll-hint, border consumes 2 more.
	innerH := m.height - 4
	if innerH < 1 {
		innerH = 1
	}
	innerW := m.width - 4 // account for 2-char border on each side
	if innerW < 1 {
		innerW = 1
	}

	content := m.viewport.View()

	body := logViewerStyles.border.
		Width(innerW).
		Height(innerH).
		Render(content)

	return lipgloss.JoinVertical(lipgloss.Left, titleStr, body, hint)
}

// AgentID returns the ID of the agent currently being viewed.
func (m LogViewerModel) AgentID() string {
	return m.agentID
}

// SetAgent switches the viewer to display logs for a different agent.
// Call ClearLogs separately if you want to flush the previous agent's buffer.
func (m *LogViewerModel) SetAgent(agentID, name string) {
	m.agentID = agentID
	m.agentName = name
}

// ClearLogs empties the log buffer and resets the viewport content.
func (m *LogViewerModel) ClearLogs() {
	m.buf.Clear()
	m.viewport.SetContent("")
	m.autoScroll = true
}

// SetSize updates the viewer dimensions and resizes the viewport accordingly.
func (m *LogViewerModel) SetSize(width, height int) {
	m.width = width
	m.height = height
	// Inner viewport dims: subtract 2 for border on each axis, 2 for title+hint.
	vpW := width - 4
	vpH := height - 4
	if vpW < 1 {
		vpW = 1
	}
	if vpH < 1 {
		vpH = 1
	}
	m.viewport.Width = vpW
	m.viewport.Height = vpH
	m.refreshViewport()
}

// SetFocused marks whether this panel should handle keyboard events.
func (m *LogViewerModel) SetFocused(focused bool) {
	m.focused = focused
}

// Focused reports whether the panel currently has keyboard focus.
func (m LogViewerModel) Focused() bool {
	return m.focused
}

// refreshViewport rebuilds the viewport content string from the current buffer.
// It must be called after any change to m.buf or m.viewport dimensions.
func (m *LogViewerModel) refreshViewport() {
	lines := m.buf.Lines()
	if len(lines) == 0 {
		m.viewport.SetContent(logViewerStyles.empty.Render("(no output yet)"))
		return
	}

	w := m.viewport.Width
	if w < 1 {
		w = 80
	}

	var sb strings.Builder
	for i, line := range lines {
		rendered := renderLine(line, w)
		sb.WriteString(rendered)
		if i < len(lines)-1 {
			sb.WriteByte('\n')
		}
	}
	m.viewport.SetContent(sb.String())
}

// renderLine formats a single LogDisplayLine as "[HH:MM:SS] text", applying
// the error color to stderr lines and wrapping at width.
func renderLine(line LogDisplayLine, width int) string {
	ts := logViewerStyles.timestamp.Render(fmt.Sprintf("[%s]", line.Timestamp.Format("15:04:05")))
	prefix := ts + " "
	prefixLen := lipgloss.Width(prefix)

	text := line.Text
	if line.IsStderr {
		text = logViewerStyles.stderr.Render(text)
	}

	// Combine and let lipgloss wrap at width.
	full := prefix + text
	wrapped := lipgloss.NewStyle().Width(width).MaxWidth(width).Render(full)

	// If the line is stderr and wrapping split it, re-apply color to continuation lines.
	_ = prefixLen // retained for potential future indent-aware wrapping
	return wrapped
}

// titleString builds the title bar string for the panel.
func (m LogViewerModel) titleString() string {
	if m.agentID == "" {
		return logViewerStyles.title.Render("Logs: (no agent selected)")
	}
	name := m.agentName
	if name == "" {
		name = m.agentID
	}
	lineCount := m.buf.Len()
	return logViewerStyles.title.Render(fmt.Sprintf("Logs: %s  [%d lines]", name, lineCount))
}

// scrollHint returns a footer line with scroll position and key hints.
func (m LogViewerModel) scrollHint() string {
	pct := int(m.viewport.ScrollPercent() * 100)
	follow := ""
	if m.autoScroll {
		follow = " [follow]"
	}
	hint := fmt.Sprintf("%d%%%s  j/k scroll  PgUp/PgDn page", pct, follow)
	return logViewerStyles.scrollHint.Render(hint)
}
