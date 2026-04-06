// integration_test.go tests full agent lifecycle scenarios end-to-end.
package agent_test

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/agent"
	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/config"
	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/session"
	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/types"
)

// buildIntegrationManager constructs a fresh AgentManager backed by a temp directory.
func buildIntegrationManager(t *testing.T) (*agent.AgentManager, string) {
	t.Helper()
	dir := t.TempDir()
	cfg := &config.GlobalConfig{
		DataDir:             dir,
		HealthCheckInterval: 50 * time.Millisecond,
		HangingTimeout:      0,
	}
	mgr := agent.NewAgentManager(dir, cfg); mgr.DirectSpawn = true
	// Ensure the history dir is cleaned up to avoid TempDir-cleanup failures.
	t.Cleanup(func() {
		os.RemoveAll(filepath.Join(dir, "history"))
	})
	return mgr, dir
}

// TestLifecycle_StartStopVerify tests the happy path: start -> verify running -> stop -> verify stopped.
func TestLifecycle_StartStopVerify(t *testing.T) {
	if mockAgentBin == "" {
		t.Skip("mock_agent binary not available")
	}

	mgr, _ := buildIntegrationManager(t)

	cfg := &types.AgentConfig{
		ID:         "lifecycle-agent",
		Name:       "Lifecycle Agent",
		Command:    mockAgentBin,
		Args:       []string{"--lines", "0", "--delay", "10s"},
		WorkingDir: t.TempDir(),
		RestartPolicy: types.RestartPolicy{
			Type: "never",
		},
	}

	// Start.
	if err := mgr.StartAgent(cfg); err != nil {
		t.Fatalf("StartAgent: %v", err)
	}

	// Drain the started event.
	drainUntil(t, mgr.Events(), func(e agent.AgentEvent) bool {
		return e.AgentID == "lifecycle-agent" && e.Type == agent.EventStarted
	}, 2*time.Second)

	// Verify running.
	ma, ok := mgr.GetAgent("lifecycle-agent")
	if !ok {
		t.Fatal("agent not found after start")
	}
	if ma.State.Status != types.StatusRunning {
		t.Errorf("expected StatusRunning, got %q", ma.State.Status)
	}
	if ma.State.PID <= 0 {
		t.Errorf("expected positive PID, got %d", ma.State.PID)
	}

	// Stop.
	if err := mgr.StopAgent("lifecycle-agent"); err != nil {
		t.Fatalf("StopAgent: %v", err)
	}

	// Drain the stopped event.
	drainUntil(t, mgr.Events(), func(e agent.AgentEvent) bool {
		return e.AgentID == "lifecycle-agent" && e.Type == agent.EventStopped
	}, 10*time.Second)

	// Verify stopped.
	ma, ok = mgr.GetAgent("lifecycle-agent")
	if !ok {
		t.Fatal("agent not found after stop")
	}
	if ma.State.Status != types.StatusStopped {
		t.Errorf("expected StatusStopped, got %q", ma.State.Status)
	}
}

// TestCrashAndRestart tests that an agent that crashes is restarted by the engine.
func TestCrashAndRestart(t *testing.T) {
	if mockAgentBin == "" {
		t.Skip("mock_agent binary not available")
	}

	mgr, _ := buildIntegrationManager(t)

	cfg := &types.AgentConfig{
		ID:         "crash-restart-agent",
		Name:       "Crash Restart Agent",
		Command:    mockAgentBin,
		Args:       []string{"--lines", "1", "--delay", "80ms", "--exit-code", "1"},
		WorkingDir: t.TempDir(),
		RestartPolicy: types.RestartPolicy{
			Type:       "on-crash",
			MaxRetries: 2,
			BaseDelay:  50 * time.Millisecond,
		},
	}

	if err := mgr.StartAgent(cfg); err != nil {
		t.Fatalf("StartAgent: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	mgr.StartHealthCheck(ctx)

	// Wait for a restart event - confirms crash was detected and restart policy fired.
	drainUntil(t, mgr.Events(), func(e agent.AgentEvent) bool {
		return e.AgentID == "crash-restart-agent" && e.Type == agent.EventRestarted
	}, 8*time.Second)

	if got := mgr.RestartEngine.RetryCount("crash-restart-agent"); got < 1 {
		t.Errorf("expected retry count >= 1, got %d", got)
	}

	// Clean up the restarted agent.
	mgr.KillAgent("crash-restart-agent") //nolint:errcheck
}

// TestSessionLaunch creates a session with two agents and verifies both start.
func TestSessionLaunch(t *testing.T) {
	if mockAgentBin == "" {
		t.Skip("mock_agent binary not available")
	}

	mgr, dataDir := buildIntegrationManager(t)

	// Build a session with 2 agents.
	sess := types.Session{
		ID:   "test-session",
		Name: "Test Session",
		Agents: []types.AgentConfig{
			{
				ID:         "sess-agent-1",
				Name:       "Session Agent 1",
				Command:    mockAgentBin,
				Args:       []string{"--lines", "0", "--delay", "5s"},
				WorkingDir: t.TempDir(),
				RestartPolicy: types.RestartPolicy{
					Type: "never",
				},
			},
			{
				ID:         "sess-agent-2",
				Name:       "Session Agent 2",
				Command:    mockAgentBin,
				Args:       []string{"--lines", "0", "--delay", "5s"},
				WorkingDir: t.TempDir(),
				RestartPolicy: types.RestartPolicy{
					Type: "never",
				},
			},
		},
	}

	// Save the session.
	if err := session.SaveSession(dataDir, &sess); err != nil {
		t.Fatalf("SaveSession: %v", err)
	}

	// Load and verify it persisted.
	loaded, err := session.LoadSession(dataDir, sess.ID)
	if err != nil {
		t.Fatalf("LoadSession: %v", err)
	}
	if len(loaded.Agents) != 2 {
		t.Fatalf("expected 2 agents in session, got %d", len(loaded.Agents))
	}

	// Launch all agents from the session.
	for i := range loaded.Agents {
		agentCfg := loaded.Agents[i]
		if err := mgr.StartAgent(&agentCfg); err != nil {
			t.Fatalf("StartAgent %q: %v", agentCfg.ID, err)
		}
	}

	// Drain both start events.
	started := make(map[string]bool)
	deadline := time.After(4 * time.Second)
	events := mgr.Events()
	for len(started) < 2 {
		select {
		case evt := <-events:
			if evt.Type == agent.EventStarted {
				started[evt.AgentID] = true
			}
		case <-deadline:
			t.Fatalf("timed out waiting for both agents to start; got %v", started)
		}
	}

	// Verify both agents are running.
	for _, id := range []string{"sess-agent-1", "sess-agent-2"} {
		ma, ok := mgr.GetAgent(id)
		if !ok {
			t.Errorf("agent %q not found", id)
			continue
		}
		if ma.State.Status != types.StatusRunning {
			t.Errorf("agent %q: expected StatusRunning, got %q", id, ma.State.Status)
		}
	}

	// Clean up.
	mgr.KillAgent("sess-agent-1") //nolint:errcheck
	mgr.KillAgent("sess-agent-2") //nolint:errcheck
}
