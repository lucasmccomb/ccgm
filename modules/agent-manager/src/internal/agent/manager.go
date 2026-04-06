// Package agent provides process lifecycle management for Claude Code agents.
// manager.go handles config persistence (CRUD) and runtime process management.
package agent

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"sync"
	"time"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/config"
	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/fileutil"
	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/types"
)

// ---- Config persistence (CRUD) -----------------------------------------------

// agentsDir returns the path to the agents config directory within dataDir.
func agentsDir(dataDir string) string {
	return filepath.Join(dataDir, "agents")
}

// agentPath returns the JSON file path for a given agentID within dataDir.
// The caller must validate agentID before calling this function.
func agentPath(dataDir, agentID string) string {
	return filepath.Join(agentsDir(dataDir), agentID+".json")
}

// LoadAgentConfig reads and returns the AgentConfig for agentID from dataDir.
// Returns os.ErrNotExist (wrapped) if the agent does not exist.
func LoadAgentConfig(dataDir, agentID string) (*types.AgentConfig, error) {
	if err := types.ValidateID(agentID); err != nil {
		return nil, fmt.Errorf("load agent config: %w", err)
	}
	path := agentPath(dataDir, agentID)
	var cfg types.AgentConfig
	if err := fileutil.ReadJSON(path, &cfg); err != nil {
		return nil, fmt.Errorf("load agent config %s: %w", agentID, err)
	}
	return &cfg, nil
}

// SaveAgentConfig persists cfg to dataDir/agents/<cfg.ID>.json using an atomic
// write with 0600 permissions. cfg.Validate() must pass before saving.
func SaveAgentConfig(dataDir string, cfg *types.AgentConfig) error {
	if err := cfg.Validate(); err != nil {
		return fmt.Errorf("save agent config: %w", err)
	}
	dir := agentsDir(dataDir)
	if err := os.MkdirAll(dir, 0700); err != nil {
		return fmt.Errorf("save agent config: create agents dir: %w", err)
	}
	path := agentPath(dataDir, cfg.ID)
	if err := fileutil.AtomicWriteJSON(path, cfg, 0600); err != nil {
		return fmt.Errorf("save agent config %s: %w", cfg.ID, err)
	}
	return nil
}

// DeleteAgentConfig removes the persisted config for agentID from dataDir.
// Returns nil if the file does not exist (idempotent delete).
func DeleteAgentConfig(dataDir, agentID string) error {
	if err := types.ValidateID(agentID); err != nil {
		return fmt.Errorf("delete agent config: %w", err)
	}
	path := agentPath(dataDir, agentID)
	if err := os.Remove(path); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("delete agent config %s: %w", agentID, err)
	}
	return nil
}

// ListAgentConfigs returns all AgentConfigs persisted in dataDir/agents/.
// The order of results is not guaranteed.
func ListAgentConfigs(dataDir string) ([]*types.AgentConfig, error) {
	dir := agentsDir(dataDir)
	entries, err := os.ReadDir(dir)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("list agent configs: %w", err)
	}

	var configs []*types.AgentConfig
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		if filepath.Ext(entry.Name()) != ".json" {
			continue
		}
		id := fileutil.Basename(entry.Name())
		// Skip files whose names are not valid IDs (e.g. stray .tmp files).
		if err := types.ValidateID(id); err != nil {
			continue
		}
		cfg, err := LoadAgentConfig(dataDir, id)
		if err != nil {
			return nil, fmt.Errorf("list agent configs: %w", err)
		}
		configs = append(configs, cfg)
	}
	return configs, nil
}

// ---- Runtime agent management ------------------------------------------------

// AgentEventType describes the kind of lifecycle event that occurred.
type AgentEventType string

const (
	EventStarted   AgentEventType = "started"
	EventStopped   AgentEventType = "stopped"
	EventCrashed   AgentEventType = "crashed"
	EventHanging   AgentEventType = "hanging"
	EventRestarted AgentEventType = "restarted"
)

// AgentEvent carries a lifecycle notification from the manager to the TUI.
type AgentEvent struct {
	AgentID string
	Type    AgentEventType
	Details string
}

// ManagedAgent pairs a persisted AgentConfig with its live runtime state.
type ManagedAgent struct {
	Config       types.AgentConfig
	State        types.AgentState
	TmuxSession  string    // legacy tmux session name
	TmuxPaneID   string    // tmux pane ID (e.g., "%5") for pane-based layout
	Process      *Process  // only used by tests with DirectSpawn
	lastOutputAt time.Time // updated by the log collector when output is received
}

// AgentManager supervises one or more running agent processes. Config CRUD
// functions at the top of this file operate on disk; the AgentManager tracks
// the in-memory runtime state of processes it has spawned.
type AgentManager struct {
	dataDir       string
	config        *config.GlobalConfig
	agents        map[string]*ManagedAgent // ID -> agent
	mu            sync.RWMutex
	notifyCh      chan AgentEvent // buffered; events for TUI consumption
	RestartEngine *RestartEngine // manages crash recovery and restart scheduling
	DirectSpawn   bool           // if true, use os/exec instead of tmux (for tests)
}

const eventChannelBuffer = 64

// NewAgentManager constructs an AgentManager. Call ReattachFromState after
// creation to reconnect to any agents that survived a manager restart.
func NewAgentManager(dataDir string, cfg *config.GlobalConfig) *AgentManager {
	m := &AgentManager{
		dataDir:  dataDir,
		config:   cfg,
		agents:   make(map[string]*ManagedAgent),
		notifyCh: make(chan AgentEvent, eventChannelBuffer),
	}
	m.RestartEngine = NewRestartEngine(m)
	return m
}

// Events returns the read-only channel on which lifecycle events are published.
// The TUI should drain this channel continuously.
func (m *AgentManager) Events() <-chan AgentEvent {
	return m.notifyCh
}

// emit sends an event without blocking. If the channel is full, the event is
// dropped (prevents deadlock when the TUI is slow).
func (m *AgentManager) emit(evt AgentEvent) {
	select {
	case m.notifyCh <- evt:
	default:
	}
}

// StartAgent validates cfg, launches the agent (via tmux or direct spawn),
// registers it, and emits EventStarted.
func (m *AgentManager) StartAgent(agentCfg *types.AgentConfig) error {
	if err := agentCfg.Validate(); err != nil {
		return fmt.Errorf("start agent: %w", err)
	}

	// Check for already-running agent.
	m.mu.Lock()
	if existing, ok := m.agents[agentCfg.ID]; ok {
		alive := false
		if existing.TmuxSession != "" {
			alive = TmuxIsAlive(existing.TmuxSession)
		} else if existing.Process != nil {
			alive = existing.Process.IsAlive()
		}
		if existing.State.Status == types.StatusRunning && alive {
			m.mu.Unlock()
			return fmt.Errorf("start agent %q: already running", agentCfg.ID)
		}
	}
	m.mu.Unlock()

	// Direct spawn mode (tests).
	if m.DirectSpawn {
		proc, err := SpawnProcess(agentCfg)
		if err != nil {
			return fmt.Errorf("start agent %q: %w", agentCfg.ID, err)
		}
		ma := &ManagedAgent{
			Config:  *agentCfg,
			Process: proc,
			State: types.AgentState{
				Config:    *agentCfg,
				PID:       proc.PID(),
				Status:    types.StatusRunning,
				StartedAt: nowFunc(),
			},
		}
		m.mu.Lock()
		m.agents[agentCfg.ID] = ma
		m.mu.Unlock()
		m.emit(AgentEvent{AgentID: agentCfg.ID, Type: EventStarted, Details: fmt.Sprintf("PID %d", proc.PID())})
		return nil
	}

	// Tmux pane mode (production).
	paneInfo, err := TmuxLaunchPane(agentCfg)
	if err != nil {
		return fmt.Errorf("start agent %q: %w", agentCfg.ID, err)
	}

	ma := &ManagedAgent{
		Config:     *agentCfg,
		TmuxPaneID: paneInfo.PaneID,
		State: types.AgentState{
			Config:    *agentCfg,
			Status:    types.StatusRunning,
			StartedAt: nowFunc(),
		},
	}

	m.mu.Lock()
	m.agents[agentCfg.ID] = ma
	m.mu.Unlock()

	m.emit(AgentEvent{AgentID: agentCfg.ID, Type: EventStarted, Details: fmt.Sprintf("pane:%s", paneInfo.PaneID)})
	return nil
}

// StopAgent kills the tmux session for the agent and emits EventStopped.
func (m *AgentManager) StopAgent(agentID string) error {
	m.mu.RLock()
	ma, ok := m.agents[agentID]
	m.mu.RUnlock()

	if !ok {
		return fmt.Errorf("stop agent %q: not found", agentID)
	}

	// Try tmux pane kill first, then session, then direct process.
	if ma.TmuxPaneID != "" {
		if err := TmuxKillPane(ma.TmuxPaneID); err != nil {
			return fmt.Errorf("stop agent %q: %w", agentID, err)
		}
	} else if ma.TmuxSession != "" {
		if err := TmuxKill(ma.TmuxSession); err != nil {
			return fmt.Errorf("stop agent %q: %w", agentID, err)
		}
	} else if ma.Process != nil {
		const gracePeriod = 5e9
		if err := ma.Process.Stop(gracePeriod); err != nil {
			return fmt.Errorf("stop agent %q: %w", agentID, err)
		}
	} else {
		return fmt.Errorf("stop agent %q: no session or process attached", agentID)
	}

	m.mu.Lock()
	ma.State.Status = types.StatusStopped
	m.mu.Unlock()

	m.RestartEngine.ResetRetryCount(agentID)
	m.emit(AgentEvent{AgentID: agentID, Type: EventStopped})
	return nil
}

// KillAgent immediately kills the agent's tmux session.
func (m *AgentManager) KillAgent(agentID string) error {
	// For tmux-based agents, kill and stop are equivalent.
	return m.StopAgent(agentID)
}

// GetAgent returns the ManagedAgent for agentID, or false if not found.
func (m *AgentManager) GetAgent(agentID string) (*ManagedAgent, bool) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	ma, ok := m.agents[agentID]
	return ma, ok
}

// ListAgents returns a snapshot of all registered agents sorted by name.
func (m *AgentManager) ListAgents() []*ManagedAgent {
	m.mu.RLock()
	defer m.mu.RUnlock()
	out := make([]*ManagedAgent, 0, len(m.agents))
	for _, ma := range m.agents {
		out = append(out, ma)
	}
	sort.Slice(out, func(i, j int) bool {
		return out[i].Config.Name < out[j].Config.Name
	})
	return out
}
