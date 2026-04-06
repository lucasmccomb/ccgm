// Package tui implements the Bubble Tea TUI for ccgm-agents.
// app.go defines the root AppModel and wires together all sub-views.
package tui

import (
	"context"
	"fmt"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/agent"
	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/config"
	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/types"
)

// tickMsg is sent on each 500ms refresh tick to poll the AgentManager.
type tickMsg struct{}

// agentEventMsg wraps an AgentEvent for delivery into the Bubble Tea loop.
type agentEventMsg struct {
	event agent.AgentEvent
}

const refreshInterval = 500 * time.Millisecond

// AppModel is the root Bubble Tea model. It owns all sub-components and
// orchestrates layout and lifecycle actions. The logs panel has been removed
// since agents run in visible tmux panes alongside the dashboard.
type AppModel struct {
	agentList    AgentListModel
	commandBar   CommandBarModel
	help         HelpModel
	launch       LaunchModel
	detail       DetailModel

	agentManager *agent.AgentManager
	config       *config.GlobalConfig
	cancel       context.CancelFunc

	width    int
	height   int
	quitting bool
}

// NewApp constructs an AppModel.
func NewApp(mgr *agent.AgentManager, cfg *config.GlobalConfig) AppModel {
	keys := DefaultKeyMap
	m := AppModel{
		agentList:    NewAgentListModel(),
		commandBar:   NewCommandBarModel(keys),
		help:         NewHelpModel(keys),
		launch:       NewLaunchModel(),
		detail:       NewDetailModel(),
		agentManager: mgr,
		config:       cfg,
	}
	m.agentList.SetFocused(true)
	m.commandBar.SetContext(ContextAgentList)
	return m
}

// Init starts the health checker and schedules the first refresh tick.
func (m AppModel) Init() tea.Cmd {
	ctx, cancel := context.WithCancel(context.Background())
	m.cancel = cancel
	m.agentManager.StartHealthCheck(ctx)

	return tea.Batch(
		drainEventsCmd(ctx, m.agentManager.Events()),
		tickCmd(),
	)
}

// Update handles all incoming messages.
func (m AppModel) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	var cmds []tea.Cmd

	switch msg := msg.(type) {

	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		m.help.SetSize(m.width, m.height)
		m.launch.SetSize(m.width, m.height)
		m.detail.SetSize(m.width, m.height)
		availH := m.height - 2
		if availH < 1 {
			availH = 1
		}
		m.agentList.SetSize(m.width, availH)
		m.commandBar.SetWidth(m.width)

	case tickMsg:
		m.agentList.SetAgents(m.snapshotAgents())
		cmds = append(cmds, tickCmd())

	case agentEventMsg:
		cmds = append(cmds, m.handleAgentEvent(msg.event)...)

	case LaunchSubmitMsg:
		m.launch.SetVisible(false)
		m.commandBar.SetContext(ContextAgentList)
		cmds = append(cmds, m.spawnAgent(msg.Config)...)

	case StatusMsg:
		cb, cmd := m.commandBar.Update(msg)
		m.commandBar = cb
		cmds = append(cmds, cmd)

	case ClearStatusMsg:
		cb, cmd := m.commandBar.Update(msg)
		m.commandBar = cb
		cmds = append(cmds, cmd)

	case tea.KeyMsg:
		// Help overlay consumes all keys when visible.
		if m.help.Visible() {
			h, cmd := m.help.Update(msg)
			m.help = h
			cmds = append(cmds, cmd)
			return m, tea.Batch(cmds...)
		}

		// Launch modal consumes all keys when visible.
		if m.launch.Visible() {
			launch, cmd := m.launch.Update(msg)
			m.launch = launch
			if !m.launch.Visible() {
				m.commandBar.SetContext(ContextAgentList)
			}
			cmds = append(cmds, cmd)
			return m, tea.Batch(cmds...)
		}

		// Detail modal consumes all keys when visible.
		if m.detail.Visible() {
			detail, cmd := m.detail.Update(msg)
			m.detail = detail
			cmds = append(cmds, cmd)
			return m, tea.Batch(cmds...)
		}

		switch msg.String() {
		case "q", "ctrl+c":
			m.quitting = true
			if m.cancel != nil {
				m.cancel()
			}
			return m, tea.Quit

		case "?":
			m.help.Toggle()
			m.help.SetSize(m.width, m.height)
			return m, tea.Batch(cmds...)

		case "n":
			m.launch.SetProjectsDir(m.config.ProjectsDir, m.config.DefaultModel)
			m.launch.SetVisible(true)
			m.launch.SetSize(m.width, m.height)
			m.launch.Reset()
			m.commandBar.SetContext(ContextModal)
			return m, tea.Batch(cmds...)

		case "a", "enter":
			if sel, ok := m.agentList.SelectedAgent(); ok {
				if ma, ok := m.agentManager.GetAgent(sel.ID); ok {
					if ma.TmuxPaneID != "" && agent.TmuxPaneIsAlive(ma.TmuxPaneID) {
						if err := agent.TmuxSelectPane(ma.TmuxPaneID); err != nil {
							return m, sendStatus(fmt.Sprintf("focus failed: %v", err), true)
						}
						return m, sendStatus(fmt.Sprintf("focused %s (ctrl-b ← to return)", sel.Name), false)
					}
					return m, sendStatus(fmt.Sprintf("%s is not running", sel.Name), true)
				}
			}
			return m, tea.Batch(cmds...)

		case "s":
			cmds = append(cmds, m.doStop()...)
			return m, tea.Batch(cmds...)

		case "r":
			cmds = append(cmds, m.doRestart()...)
			return m, tea.Batch(cmds...)

		case "x":
			cmds = append(cmds, m.doKill()...)
			return m, tea.Batch(cmds...)

		case "d":
			if sel, ok := m.agentList.SelectedAgent(); ok {
				if ma, ok := m.agentManager.GetAgent(sel.ID); ok {
					m.detail.SetAgent(ma)
					m.detail.SetSize(m.width, m.height)
				}
			}
			return m, tea.Batch(cmds...)
		}

		// Forward to agent list for navigation keys.
		al, cmd := m.agentList.Update(msg)
		m.agentList = al
		cmds = append(cmds, cmd)
	}

	return m, tea.Batch(cmds...)
}

// View renders the full TUI screen.
func (m AppModel) View() string {
	if m.quitting {
		return "Goodbye.\n"
	}

	if m.help.Visible() {
		return m.help.View()
	}

	// Title bar.
	titleBar := titleBarStyle(m.width).Render(" ccgm-agents  " + currentTimeStr())

	// Agent list takes the full width.
	availH := m.height - 2
	if availH < 1 {
		availH = 1
	}
	m.agentList.SetSize(m.width, availH)
	agentPanel := m.agentList.View()

	// Command bar.
	m.commandBar.SetWidth(m.width)
	cmdBar := m.commandBar.View()

	screen := lipgloss.JoinVertical(lipgloss.Left, titleBar, agentPanel, cmdBar)

	// Overlay modals.
	if m.launch.Visible() {
		return overlayCenter(screen, m.launch.View(), m.width, m.height)
	}
	if m.detail.Visible() {
		return overlayCenter(screen, m.detail.View(), m.width, m.height)
	}

	return screen
}

// --- helpers -----------------------------------------------------------------

func (m AppModel) snapshotAgents() []AgentListItem {
	now := time.Now()
	managed := m.agentManager.ListAgents()
	items := make([]AgentListItem, 0, len(managed))
	for _, ma := range managed {
		uptime := time.Duration(0)
		if ma.State.Status == types.StatusRunning && !ma.State.StartedAt.IsZero() {
			uptime = now.Sub(ma.State.StartedAt)
		}
		items = append(items, AgentListItem{
			ID:           ma.Config.ID,
			Name:         ma.Config.Name,
			Status:       ma.State.Status,
			Uptime:       uptime,
			PID:          ma.State.PID,
			RestartCount: ma.State.RestartCount,
		})
	}
	return items
}

func (m AppModel) handleAgentEvent(evt agent.AgentEvent) []tea.Cmd {
	var msg string
	switch evt.Type {
	case agent.EventStarted:
		msg = fmt.Sprintf("Agent %q started", evt.AgentID)
	case agent.EventStopped:
		msg = fmt.Sprintf("Agent %q stopped", evt.AgentID)
	case agent.EventCrashed:
		msg = fmt.Sprintf("Agent %q crashed: %s", evt.AgentID, evt.Details)
	case agent.EventRestarted:
		msg = fmt.Sprintf("Agent %q restarted: %s", evt.AgentID, evt.Details)
	}
	if msg != "" {
		isErr := evt.Type == agent.EventCrashed
		return []tea.Cmd{sendStatus(msg, isErr)}
	}
	return nil
}

func (m AppModel) doStop() []tea.Cmd {
	sel, ok := m.agentList.SelectedAgent()
	if !ok {
		return []tea.Cmd{sendStatus("no agent selected", true)}
	}
	if err := m.agentManager.StopAgent(sel.ID); err != nil {
		return []tea.Cmd{sendStatus(fmt.Sprintf("stop failed: %v", err), true)}
	}
	return []tea.Cmd{sendStatus(fmt.Sprintf("stopped %q", sel.Name), false)}
}

func (m AppModel) doKill() []tea.Cmd {
	sel, ok := m.agentList.SelectedAgent()
	if !ok {
		return []tea.Cmd{sendStatus("no agent selected", true)}
	}
	if err := m.agentManager.KillAgent(sel.ID); err != nil {
		return []tea.Cmd{sendStatus(fmt.Sprintf("kill failed: %v", err), true)}
	}
	return []tea.Cmd{sendStatus(fmt.Sprintf("killed %q", sel.Name), false)}
}

func (m AppModel) doRestart() []tea.Cmd {
	sel, ok := m.agentList.SelectedAgent()
	if !ok {
		return []tea.Cmd{sendStatus("no agent selected", true)}
	}
	ma, found := m.agentManager.GetAgent(sel.ID)
	if !found {
		return []tea.Cmd{sendStatus("agent not found", true)}
	}
	cfg := ma.Config
	_ = m.agentManager.StopAgent(sel.ID)
	if err := m.agentManager.StartAgent(&cfg); err != nil {
		return []tea.Cmd{sendStatus(fmt.Sprintf("restart failed: %v", err), true)}
	}
	return []tea.Cmd{sendStatus(fmt.Sprintf("restarted %q", sel.Name), false)}
}

func (m AppModel) spawnAgent(cfg types.AgentConfig) []tea.Cmd {
	if err := m.agentManager.StartAgent(&cfg); err != nil {
		return []tea.Cmd{sendStatus(fmt.Sprintf("launch failed: %v", err), true)}
	}
	return []tea.Cmd{sendStatus(fmt.Sprintf("launched %q", cfg.Name), false)}
}

func sendStatus(text string, isErr bool) tea.Cmd {
	return func() tea.Msg {
		return StatusMsg{Text: text, IsError: isErr}
	}
}

func tickCmd() tea.Cmd {
	return tea.Tick(refreshInterval, func(_ time.Time) tea.Msg {
		return tickMsg{}
	})
}

func drainEventsCmd(ctx context.Context, eventCh <-chan agent.AgentEvent) tea.Cmd {
	return func() tea.Msg {
		select {
		case evt, ok := <-eventCh:
			if !ok {
				return nil
			}
			return agentEventMsg{event: evt}
		case <-ctx.Done():
			return nil
		}
	}
}

func overlayCenter(base, overlay string, w, h int) string {
	return lipgloss.Place(w, h, lipgloss.Center, lipgloss.Center,
		overlay,
		lipgloss.WithWhitespaceChars(" "),
		lipgloss.WithWhitespaceForeground(lipgloss.AdaptiveColor{Light: "0", Dark: "0"}),
	)
}

func titleBarStyle(w int) lipgloss.Style {
	return lipgloss.NewStyle().
		Background(lipgloss.Color("62")).
		Foreground(lipgloss.Color("15")).
		Bold(true).
		Width(w)
}

func currentTimeStr() string {
	return time.Now().Format("15:04:05")
}
