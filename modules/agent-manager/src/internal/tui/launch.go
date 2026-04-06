// launch.go implements a directory picker modal for launching new agents.
// The user picks a project directory from a configurable base path.
// Name and model are derived automatically. If a Claude session is already
// running in the selected directory, a warning is shown.
package tui

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/agent"
	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/types"
)

// LaunchSubmitMsg is emitted when the user selects a directory to launch in.
type LaunchSubmitMsg struct {
	Config types.AgentConfig
}

// launchState tracks which screen the launch modal is on.
type launchState int

const (
	statePicking  launchState = iota // directory picker
	stateWarning                     // conflict warning
)

// LaunchModel is a Bubble Tea component that renders a directory picker modal.
type LaunchModel struct {
	dirs         []string // directory names (basenames)
	filtered     []string // filtered subset
	cursor       int
	filter       string
	filtering    bool
	visible      bool
	width        int
	height       int
	projectsDir  string // base directory to scan
	defaultModel string // default model (e.g., "opus")

	// Conflict warning state.
	state       launchState
	conflictDir string
	conflictPID int
	pendingCfg  types.AgentConfig
}

// NewLaunchModel returns a LaunchModel. Call SetProjectsDir before showing.
func NewLaunchModel() LaunchModel {
	return LaunchModel{}
}

// Init satisfies tea.Model.
func (m LaunchModel) Init() tea.Cmd {
	return nil
}

// Update handles keyboard events within the launch modal.
func (m LaunchModel) Update(msg tea.Msg) (LaunchModel, tea.Cmd) {
	if !m.visible {
		return m, nil
	}

	switch msg := msg.(type) {
	case tea.KeyMsg:
		key := msg.String()

		// Warning screen: simple yes/no.
		if m.state == stateWarning {
			switch key {
			case "y", "Y", "enter":
				m.visible = false
				m.state = statePicking
				cfg := m.pendingCfg
				return m, func() tea.Msg {
					return LaunchSubmitMsg{Config: cfg}
				}
			case "n", "N", "esc":
				m.state = statePicking
				return m, nil
			}
			return m, nil
		}

		// Filter input mode.
		if m.filtering {
			switch key {
			case "esc":
				m.filtering = false
				m.filter = ""
				m.applyFilter()
				return m, nil
			case "enter":
				m.filtering = false
				return m, nil
			case "backspace":
				if len(m.filter) > 0 {
					m.filter = m.filter[:len(m.filter)-1]
					m.applyFilter()
				}
				return m, nil
			default:
				if len(key) == 1 {
					m.filter += key
					m.applyFilter()
				}
			}
			return m, nil
		}

		// Directory picker.
		switch key {
		case "esc", "q":
			m.visible = false
			return m, nil

		case "j", "down":
			if m.cursor < len(m.filtered)-1 {
				m.cursor++
			}
			return m, nil

		case "k", "up":
			if m.cursor > 0 {
				m.cursor--
			}
			return m, nil

		case "/":
			m.filtering = true
			m.filter = ""
			return m, nil

		case "enter":
			if len(m.filtered) > 0 && m.cursor < len(m.filtered) {
				return m.tryLaunch()
			}
			return m, nil
		}
	}
	return m, nil
}

// View renders the directory picker or conflict warning.
func (m LaunchModel) View() string {
	if !m.visible {
		return ""
	}

	if m.state == stateWarning {
		return m.viewWarning()
	}
	return m.viewPicker()
}

func (m LaunchModel) viewPicker() string {
	titleStyle := lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("62"))
	selectedStyle := lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("0")).Background(lipgloss.Color("62")).PaddingRight(1)
	normalStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("252"))
	dimStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("243"))
	filterStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("214")).Bold(true)
	hintKeyStyle := lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("0")).Background(lipgloss.Color("62")).PaddingLeft(1).PaddingRight(1)
	hintDescStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("252")).PaddingRight(1)
	boxStyle := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(lipgloss.Color("62")).
		Padding(1, 2).
		Background(lipgloss.Color("235")).
		Width(60)

	var sb strings.Builder
	sb.WriteString(titleStyle.Render("Launch New Agent"))
	sb.WriteString("\n")
	sb.WriteString(dimStyle.Render("Select a project directory from " + m.projectsDir))
	sb.WriteString("\n\n")

	if m.filtering {
		sb.WriteString(filterStyle.Render("/ " + m.filter + "█"))
		sb.WriteString("\n\n")
	} else if m.filter != "" {
		sb.WriteString(dimStyle.Render("filter: " + m.filter))
		sb.WriteString("\n\n")
	}

	if len(m.filtered) == 0 {
		sb.WriteString(dimStyle.Render("  (no directories found)"))
		sb.WriteString("\n")
	} else {
		maxVisible := 15
		if m.height > 0 {
			maxVisible = m.height/2 - 8
			if maxVisible < 5 {
				maxVisible = 5
			}
		}

		start := 0
		if m.cursor >= maxVisible {
			start = m.cursor - maxVisible + 1
		}
		end := start + maxVisible
		if end > len(m.filtered) {
			end = len(m.filtered)
		}

		for i := start; i < end; i++ {
			if i == m.cursor {
				sb.WriteString("  " + selectedStyle.Render(" "+m.filtered[i]))
			} else {
				sb.WriteString("  " + normalStyle.Render(" "+m.filtered[i]))
			}
			sb.WriteString("\n")
		}

		if len(m.filtered) > maxVisible {
			shown := end - start
			total := len(m.filtered)
			sb.WriteString(dimStyle.Render(fmt.Sprintf("    showing %d of %d", shown, total)))
			sb.WriteString("\n")
		}
	}

	sb.WriteString("\n")
	sb.WriteString(
		hintKeyStyle.Render("j/k") + hintDescStyle.Render("navigate") + " " +
			hintKeyStyle.Render("enter") + hintDescStyle.Render("select") + " " +
			hintKeyStyle.Render("/") + hintDescStyle.Render("filter") + " " +
			hintKeyStyle.Render("esc") + hintDescStyle.Render("cancel"),
	)

	return boxStyle.Render(sb.String())
}

func (m LaunchModel) viewWarning() string {
	warnStyle := lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("214"))
	dimStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("252"))
	hintKeyStyle := lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("0")).Background(lipgloss.Color("62")).PaddingLeft(1).PaddingRight(1)
	hintDescStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("252")).PaddingRight(1)
	boxStyle := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(lipgloss.Color("214")).
		Padding(1, 3).
		Background(lipgloss.Color("235")).
		Width(60)

	var sb strings.Builder
	sb.WriteString(warnStyle.Render("⚠  Claude Already Running"))
	sb.WriteString("\n\n")
	sb.WriteString(dimStyle.Render(fmt.Sprintf("A Claude session is already active in:")))
	sb.WriteString("\n")
	sb.WriteString(dimStyle.Render(fmt.Sprintf("  %s", m.conflictDir)))
	sb.WriteString("\n")
	sb.WriteString(dimStyle.Render(fmt.Sprintf("  PID: %d", m.conflictPID)))
	sb.WriteString("\n\n")
	sb.WriteString(dimStyle.Render("Launch another session in this directory?"))
	sb.WriteString("\n\n")
	sb.WriteString(
		hintKeyStyle.Render("y") + hintDescStyle.Render("yes, launch") + " " +
			hintKeyStyle.Render("n") + hintDescStyle.Render("cancel"),
	)

	return boxStyle.Render(sb.String())
}

// SetVisible shows or hides the modal.
func (m *LaunchModel) SetVisible(v bool) {
	m.visible = v
	if !v {
		m.state = statePicking
	}
}

// Visible reports whether the modal is currently shown.
func (m LaunchModel) Visible() bool {
	return m.visible
}

// SetSize stores terminal dimensions.
func (m *LaunchModel) SetSize(w, h int) {
	m.width = w
	m.height = h
}

// SetProjectsDir sets the base directory to scan and the default model.
func (m *LaunchModel) SetProjectsDir(dir, defaultModel string) {
	m.projectsDir = dir
	m.defaultModel = defaultModel
}

// Reset scans the projects directory and resets selection state.
func (m *LaunchModel) Reset() {
	m.cursor = 0
	m.filter = ""
	m.filtering = false
	m.state = statePicking
	m.dirs = scanDirs(m.projectsDir)
	m.filtered = m.dirs
}

// applyFilter updates the filtered list based on the current filter string.
func (m *LaunchModel) applyFilter() {
	if m.filter == "" {
		m.filtered = m.dirs
	} else {
		lower := strings.ToLower(m.filter)
		m.filtered = nil
		for _, d := range m.dirs {
			if strings.Contains(strings.ToLower(d), lower) {
				m.filtered = append(m.filtered, d)
			}
		}
	}
	if m.cursor >= len(m.filtered) {
		m.cursor = len(m.filtered) - 1
	}
	if m.cursor < 0 {
		m.cursor = 0
	}
}

// tryLaunch checks for conflicts and either shows a warning or submits.
func (m LaunchModel) tryLaunch() (LaunchModel, tea.Cmd) {
	dirName := m.filtered[m.cursor]
	fullPath := filepath.Join(m.projectsDir, dirName)
	id := sanitizeID(dirName)

	cfg := types.AgentConfig{
		ID:         id,
		Name:       dirName,
		Command:    "claude",
		WorkingDir: fullPath,
		Model:      m.defaultModel,
		RestartPolicy: types.RestartPolicy{
			Type: "never",
		},
	}

	// Check for existing Claude process in this directory.
	if procs, err := agent.DiscoverClaudeProcesses(); err == nil {
		for _, p := range procs {
			if p.WorkingDir == fullPath || strings.HasPrefix(p.WorkingDir, fullPath+"/") {
				m.state = stateWarning
				m.conflictDir = p.WorkingDir
				m.conflictPID = p.PID
				m.pendingCfg = cfg
				return m, nil
			}
		}
	}

	// No conflict - launch directly.
	m.visible = false
	return m, func() tea.Msg {
		return LaunchSubmitMsg{Config: cfg}
	}
}

// scanDirs reads the immediate subdirectories of dir and returns their names sorted.
func scanDirs(dir string) []string {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil
	}

	var dirs []string
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		name := e.Name()
		if strings.HasPrefix(name, ".") {
			continue
		}
		dirs = append(dirs, name)
	}
	sort.Strings(dirs)
	return dirs
}

// sanitizeID converts a display name to a valid agent ID.
func sanitizeID(name string) string {
	name = strings.ToLower(name)
	var sb strings.Builder
	for _, r := range name {
		switch {
		case r >= 'a' && r <= 'z':
			sb.WriteRune(r)
		case r >= '0' && r <= '9':
			sb.WriteRune(r)
		case r == '-' || r == '_':
			sb.WriteRune(r)
		default:
			sb.WriteRune('-')
		}
	}
	id := strings.Trim(sb.String(), "-")
	if id == "" {
		id = "agent"
	}
	return id
}
