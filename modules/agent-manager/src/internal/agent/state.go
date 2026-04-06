// state.go handles persistence of running-agent state to disk so the manager
// can re-attach to agents that survived a manager restart.
package agent

import (
	"fmt"
	"os"
	"path/filepath"
	"syscall"
	"time"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/fileutil"
	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/types"
)

const runningStateFile = "running.json"

// RunningAgentState captures the minimal information needed to re-attach to
// an agent process after the manager restarts.
type RunningAgentState struct {
	Config    types.AgentConfig `json:"config"`
	PID       int               `json:"pid"`
	StartedAt time.Time         `json:"started_at"`
}

// RunningState is the top-level structure written to state/running.json.
type RunningState struct {
	Agents  []RunningAgentState `json:"agents"`
	SavedAt time.Time           `json:"saved_at"`
}

// statePath returns the path to state/running.json within dataDir.
func statePath(dataDir string) string {
	return filepath.Join(dataDir, "state", runningStateFile)
}

// SaveRunningState serialises the state of all agents to disk atomically.
func SaveRunningState(dataDir string, agents map[string]*ManagedAgent) error {
	stateDir := filepath.Join(dataDir, "state")
	if err := os.MkdirAll(stateDir, 0700); err != nil {
		return fmt.Errorf("save running state: create state dir: %w", err)
	}

	rs := RunningState{
		SavedAt: nowFunc(),
		Agents:  make([]RunningAgentState, 0, len(agents)),
	}
	for _, ma := range agents {
		if ma.Process == nil {
			continue
		}
		rs.Agents = append(rs.Agents, RunningAgentState{
			Config:    ma.Config,
			PID:       ma.Process.PID(),
			StartedAt: ma.State.StartedAt,
		})
	}

	if err := fileutil.AtomicWriteJSON(statePath(dataDir), rs, 0600); err != nil {
		return fmt.Errorf("save running state: %w", err)
	}
	return nil
}

// LoadRunningState reads state/running.json from dataDir.
// Returns a zero-value RunningState (not an error) if the file does not exist.
func LoadRunningState(dataDir string) (*RunningState, error) {
	path := statePath(dataDir)
	if _, err := os.Stat(path); os.IsNotExist(err) {
		return &RunningState{}, nil
	}
	var rs RunningState
	if err := fileutil.ReadJSON(path, &rs); err != nil {
		return nil, fmt.Errorf("load running state: %w", err)
	}
	return &rs, nil
}

// SaveState is a convenience method that persists the manager's current agent
// registry to disk.
func (m *AgentManager) SaveState() error {
	m.mu.RLock()
	// Copy the map so we can release the lock before doing I/O.
	snapshot := make(map[string]*ManagedAgent, len(m.agents))
	for k, v := range m.agents {
		snapshot[k] = v
	}
	m.mu.RUnlock()

	return SaveRunningState(m.dataDir, snapshot)
}

// ReattachFromState loads state/running.json and reconnects to any agents
// whose PIDs are still alive on this machine.
//
// Limitation (macOS / no /proc): we cannot reopen the stdout/stderr pipes of
// an already-running process. Re-attached agents are registered as running but
// will have no log streaming until they are stopped and restarted.
func (m *AgentManager) ReattachFromState() error {
	rs, err := LoadRunningState(m.dataDir)
	if err != nil {
		return fmt.Errorf("reattach: %w", err)
	}

	for _, ras := range rs.Agents {
		alive := pidIsAlive(ras.PID)

		status := types.StatusStopped
		if alive {
			status = types.StatusRunning
		}

		ma := &ManagedAgent{
			Config: ras.Config,
			State: types.AgentState{
				Config:    ras.Config,
				PID:       ras.PID,
				Status:    status,
				StartedAt: ras.StartedAt,
			},
			// Process is nil for re-attached agents - we cannot reconstruct
			// the pipe handles. The agent is "alive but log-blind".
			Process: nil,
		}

		m.mu.Lock()
		m.agents[ras.Config.ID] = ma
		m.mu.Unlock()
	}

	return nil
}

// SaveRunningStateRaw writes rs directly to state/running.json. It is used by
// tests that need to inject a specific state without spawning real processes.
func SaveRunningStateRaw(dataDir string, rs *RunningState) error {
	stateDir := filepath.Join(dataDir, "state")
	if err := os.MkdirAll(stateDir, 0700); err != nil {
		return fmt.Errorf("save running state raw: create state dir: %w", err)
	}
	if err := fileutil.AtomicWriteJSON(statePath(dataDir), rs, 0600); err != nil {
		return fmt.Errorf("save running state raw: %w", err)
	}
	return nil
}

// pidIsAlive uses signal 0 to test whether pid still exists on this machine.
func pidIsAlive(pid int) bool {
	if pid <= 0 {
		return false
	}
	err := syscall.Kill(pid, 0)
	return err == nil
}
