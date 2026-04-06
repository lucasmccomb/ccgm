package agent_test

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/agent"
	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/config"
	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/types"
)

func newTestManager(t *testing.T) (*agent.AgentManager, string) {
	t.Helper()
	dir := t.TempDir()
	cfg := &config.GlobalConfig{
		DataDir:             dir,
		HealthCheckInterval: 50 * time.Millisecond,
		HangingTimeout:      500 * time.Millisecond,
	}
	m := agent.NewAgentManager(dir, cfg)
	return m, dir
}

func TestHealthCheck_DetectsCrash(t *testing.T) {
	if mockAgentBin == "" {
		t.Skip("mock_agent binary not available")
	}

	m, dataDir := newTestManager(t)
	// The restart engine writes crash tombstones asynchronously into
	// dataDir/history/<agentID>/. Register a cleanup that removes those files
	// before t.TempDir's own cleanup runs, preventing "directory not empty" errors.
	t.Cleanup(func() {
		os.RemoveAll(filepath.Join(dataDir, "history"))
	})

	// Agent exits after 100ms.
	agentCfg := &types.AgentConfig{
		ID:         "crash-agent",
		Name:       "Crash Agent",
		Command:    mockAgentBin,
		Args:       []string{"--lines", "1", "--delay", "100ms", "--exit-code", "1"},
		WorkingDir: t.TempDir(),
		RestartPolicy: types.RestartPolicy{
			Type: "never",
		},
	}

	if err := m.StartAgent(agentCfg); err != nil {
		t.Fatalf("StartAgent: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	m.StartHealthCheck(ctx)

	// Drain events until we see a crash event or timeout.
	events := m.Events()
	var gotCrash bool
	deadline := time.After(3 * time.Second)
	for !gotCrash {
		select {
		case evt := <-events:
			if evt.AgentID == "crash-agent" && evt.Type == agent.EventCrashed {
				gotCrash = true
			}
		case <-deadline:
			t.Fatal("timed out waiting for crash event")
		}
	}
}

func TestHealthCheck_DetectsHang(t *testing.T) {
	if mockAgentBin == "" {
		t.Skip("mock_agent binary not available")
	}

	dir := t.TempDir()
	cfg := &config.GlobalConfig{
		DataDir:             dir,
		HealthCheckInterval: 50 * time.Millisecond,
		HangingTimeout:      200 * time.Millisecond,
	}
	m := agent.NewAgentManager(dir, cfg)

	// Agent runs for 10 seconds (well beyond the hanging timeout).
	agentCfg := &types.AgentConfig{
		ID:         "hang-agent",
		Name:       "Hang Agent",
		Command:    mockAgentBin,
		Args:       []string{"--lines", "0", "--delay", "10s"},
		WorkingDir: t.TempDir(),
		RestartPolicy: types.RestartPolicy{
			Type: "never",
		},
	}

	if err := m.StartAgent(agentCfg); err != nil {
		t.Fatalf("StartAgent: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	m.StartHealthCheck(ctx)

	events := m.Events()
	var gotHang bool
	deadline := time.After(3 * time.Second)
	for !gotHang {
		select {
		case evt := <-events:
			if evt.AgentID == "hang-agent" && evt.Type == agent.EventHanging {
				gotHang = true
			}
		case <-deadline:
			t.Fatal("timed out waiting for hang event")
		}
	}

	// Clean up the long-running agent.
	m.KillAgent("hang-agent") //nolint:errcheck
}

func TestHealthCheck_ContextCancellation(t *testing.T) {
	if mockAgentBin == "" {
		t.Skip("mock_agent binary not available")
	}

	m, _ := newTestManager(t)

	ctx, cancel := context.WithCancel(context.Background())
	m.StartHealthCheck(ctx)

	// Let the health check loop run a couple ticks.
	time.Sleep(120 * time.Millisecond)

	// Cancel the context - the goroutine should stop cleanly.
	cancel()

	// There is no public way to observe the goroutine's termination directly,
	// but we can confirm the test does not deadlock or hang.
	time.Sleep(100 * time.Millisecond)
}

func TestStartAgent_EmitsStartedEvent(t *testing.T) {
	if mockAgentBin == "" {
		t.Skip("mock_agent binary not available")
	}

	m, _ := newTestManager(t)

	agentCfg := &types.AgentConfig{
		ID:         "event-agent",
		Name:       "Event Agent",
		Command:    mockAgentBin,
		Args:       []string{"--lines", "0", "--delay", "2s"},
		WorkingDir: t.TempDir(),
		RestartPolicy: types.RestartPolicy{
			Type: "never",
		},
	}

	if err := m.StartAgent(agentCfg); err != nil {
		t.Fatalf("StartAgent: %v", err)
	}

	select {
	case evt := <-m.Events():
		if evt.Type != agent.EventStarted {
			t.Errorf("expected EventStarted, got %q", evt.Type)
		}
		if evt.AgentID != "event-agent" {
			t.Errorf("expected agentID 'event-agent', got %q", evt.AgentID)
		}
	case <-time.After(time.Second):
		t.Fatal("timed out waiting for start event")
	}

	m.KillAgent("event-agent") //nolint:errcheck
}

func TestStopAgent_EmitsStoppedEvent(t *testing.T) {
	if mockAgentBin == "" {
		t.Skip("mock_agent binary not available")
	}

	m, _ := newTestManager(t)

	agentCfg := &types.AgentConfig{
		ID:         "stop-event-agent",
		Name:       "Stop Event Agent",
		Command:    mockAgentBin,
		Args:       []string{"--lines", "0", "--delay", "10s"},
		WorkingDir: t.TempDir(),
		RestartPolicy: types.RestartPolicy{
			Type: "never",
		},
	}

	if err := m.StartAgent(agentCfg); err != nil {
		t.Fatalf("StartAgent: %v", err)
	}

	// Drain the start event.
	<-m.Events()

	if err := m.StopAgent("stop-event-agent"); err != nil {
		t.Fatalf("StopAgent: %v", err)
	}

	select {
	case evt := <-m.Events():
		if evt.Type != agent.EventStopped {
			t.Errorf("expected EventStopped, got %q", evt.Type)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("timed out waiting for stop event")
	}
}

func TestStartAgent_ConcurrentStartStop(t *testing.T) {
	if mockAgentBin == "" {
		t.Skip("mock_agent binary not available")
	}

	m, _ := newTestManager(t)

	// Start multiple agents concurrently.
	const n = 4
	errs := make(chan error, n)
	for i := 0; i < n; i++ {
		id := "concurrent-agent-" + string(rune('a'+i))
		cfg := &types.AgentConfig{
			ID:         id,
			Name:       id,
			Command:    mockAgentBin,
			Args:       []string{"--lines", "0", "--delay", "5s"},
			WorkingDir: t.TempDir(),
			RestartPolicy: types.RestartPolicy{
				Type: "never",
			},
		}
		go func(c *types.AgentConfig) {
			errs <- m.StartAgent(c)
		}(cfg)
	}

	for i := 0; i < n; i++ {
		if err := <-errs; err != nil {
			t.Errorf("StartAgent error: %v", err)
		}
	}

	// Kill all agents concurrently.
	killErrs := make(chan error, n)
	for i := 0; i < n; i++ {
		id := "concurrent-agent-" + string(rune('a'+i))
		go func(agentID string) {
			killErrs <- m.KillAgent(agentID)
		}(id)
	}
	for i := 0; i < n; i++ {
		if err := <-killErrs; err != nil {
			t.Errorf("KillAgent error: %v", err)
		}
	}
}
