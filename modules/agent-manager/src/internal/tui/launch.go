// launch.go implements a directory picker modal for launching new agents.
// Instead of typing fields manually, the user picks a project directory
// from a configurable base path. Name and model are derived automatically.
package tui

import (
	"os"
	"path/filepath"
	"sort"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/types"
)

// LaunchSubmitMsg is emitted when the user selects a directory to launch in.
type LaunchSubmitMsg struct {
	Config types.AgentConfig
}

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
		if m.filtering {
			switch msg.String() {
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
				if len(msg.String()) == 1 {
					m.filter += msg.String()
					m.applyFilter()
					return m, nil
				}
			}
			return m, nil
		}

		switch msg.String() {
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
				return m.submit()
			}
			return m, nil
		}
	}
	return m, nil
}

// View renders the directory picker modal.
func (m LaunchModel) View() string {
	if !m.visible {
		return ""
	}

	titleStyle := lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("62"))
	selectedStyle := lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("0")).Background(lipgloss.Color("62"))
	normalStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("252"))
	dimStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("243"))
	filterStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("214")).Bold(true)
	hintStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("243"))
	boxStyle := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(lipgloss.Color("62")).
		Padding(1, 2).
		Background(lipgloss.Color("235")).
		Width(60)

	var sb strings.Builder
	sb.WriteString(titleStyle.Render("Launch New Agent"))
	sb.WriteString("\n")
	sb.WriteString(dimStyle.Render("Select a project directory"))
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
		// Show a scrollable window of directories.
		maxVisible := 15
		if m.height > 0 {
			maxVisible = m.height/2 - 6
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
			prefix := "  "
			style := normalStyle
			if i == m.cursor {
				prefix = "▸ "
				style = selectedStyle
			}
			sb.WriteString(prefix + style.Render(m.filtered[i]))
			sb.WriteString("\n")
		}

		if len(m.filtered) > maxVisible {
			sb.WriteString(dimStyle.Render(
				strings.Repeat(" ", 2) +
					"(" + strings.Repeat("·", len(m.filtered)-maxVisible) + ")",
			))
			sb.WriteString("\n")
		}
	}

	sb.WriteString("\n")
	sb.WriteString(hintStyle.Render("j/k navigate   enter select   / filter   esc cancel"))

	return boxStyle.Render(sb.String())
}

// SetVisible shows or hides the modal.
func (m *LaunchModel) SetVisible(v bool) {
	m.visible = v
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

// submit creates an AgentConfig from the selected directory.
func (m LaunchModel) submit() (LaunchModel, tea.Cmd) {
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
		// Skip hidden directories.
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
