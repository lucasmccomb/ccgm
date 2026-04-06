// health.go implements liveness checks for running agents.
package agent

import (
	"context"
	"fmt"
	"time"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/types"
)

// nowFunc is a package-level variable so tests can substitute a fake clock.
var nowFunc = func() time.Time { return time.Now() }

// StartHealthCheck runs periodic liveness checks in a background goroutine.
// It returns immediately; cancel ctx to stop the loop.
//
// For each registered agent the health check:
//   - Detects a process that has exited: marks it crashed and writes a run record.
//   - Detects a process that has produced no output for longer than the
//     configured HangingTimeout: marks it hanging.
func (m *AgentManager) StartHealthCheck(ctx context.Context) {
	interval := m.config.HealthCheckInterval
	if interval <= 0 {
		interval = 2 * time.Second
	}

	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()

		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				m.checkAllAgents()
			}
		}
	}()
}

// checkAllAgents inspects every registered agent once.
func (m *AgentManager) checkAllAgents() {
	// Snapshot the agents map under a read lock to avoid holding the lock
	// while doing potentially slow operations.
	m.mu.RLock()
	ids := make([]string, 0, len(m.agents))
	for id := range m.agents {
		ids = append(ids, id)
	}
	m.mu.RUnlock()

	for _, id := range ids {
		m.checkAgent(id)
	}
}

// checkAgent performs a single liveness check on the named agent.
func (m *AgentManager) checkAgent(agentID string) {
	m.mu.RLock()
	ma, ok := m.agents[agentID]
	m.mu.RUnlock()

	if !ok || ma.Process == nil {
		return
	}

	// Only check agents that we believe are running.
	m.mu.RLock()
	status := ma.State.Status
	m.mu.RUnlock()

	if status != types.StatusRunning && status != types.StatusHanging {
		return
	}

	if ma.Process.IsAlive() {
		// Process is still running. Check for hang: if no output has arrived
		// for longer than HangingTimeout, mark it hanging.
		//
		// Note: tracking "last output time" requires integrating with the log
		// collector. As a pragmatic initial implementation we check the wall
		// clock since start as a proxy when no log collector is wired up. The
		// TUI Epic will wire up the collector and update lastOutputAt on each
		// received line.
		m.mu.RLock()
		lastOutput := ma.State.StartedAt // fallback when no collector is wired
		if !ma.lastOutputAt.IsZero() {
			lastOutput = ma.lastOutputAt
		}
		hangTimeout := m.config.HangingTimeout
		currentStatus := ma.State.Status
		m.mu.RUnlock()

		if hangTimeout > 0 && nowFunc().Sub(lastOutput) > hangTimeout {
			if currentStatus != types.StatusHanging {
				m.mu.Lock()
				ma.State.Status = types.StatusHanging
				m.mu.Unlock()

				m.emit(AgentEvent{
					AgentID: agentID,
					Type:    EventHanging,
					Details: fmt.Sprintf("no output for %s", hangTimeout),
				})
			}
		}
		return
	}

	// Process is dead.
	m.mu.Lock()
	if ma.State.Status == types.StatusStopped {
		// Already handled by StopAgent/KillAgent.
		m.mu.Unlock()
		return
	}
	exitCode := ma.Process.ExitCode()
	ma.State.Status = types.StatusCrashed
	ma.State.ExitCode = exitCode
	stoppedAt := nowFunc()
	startedAt := ma.State.StartedAt
	restartCount := ma.State.RestartCount
	m.mu.Unlock()

	// Write a run record to history.
	record := &types.RunRecord{
		AgentID:      agentID,
		StartedAt:    startedAt,
		StoppedAt:    stoppedAt,
		ExitCode:     exitCode,
		RestartCount: restartCount,
	}
	_ = WriteRunRecord(m.dataDir, record) // best-effort; don't block health check on I/O errors

	m.emit(AgentEvent{
		AgentID: agentID,
		Type:    EventCrashed,
		Details: fmt.Sprintf("exit code %d", exitCode),
	})
}
