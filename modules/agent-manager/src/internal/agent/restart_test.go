package agent_test

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/agent"
	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/config"
	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/types"
)

// safeBuffer is a thread-safe bytes.Buffer for capturing output in tests.
type safeBuffer struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (s *safeBuffer) Write(p []byte) (int, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.buf.Write(p)
}

func (s *safeBuffer) Bytes() []byte {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.buf.Bytes()
}

// ---- helpers -----------------------------------------------------------------

func newRestartManager(t *testing.T) (*agent.AgentManager, string) {
	t.Helper()
	dir := t.TempDir()
	cfg := &config.GlobalConfig{
		DataDir:             dir,
		HealthCheckInterval: 50 * time.Millisecond,
		HangingTimeout:      0, // disable hang detection in restart tests
	}
	m := agent.NewAgentManager(dir, cfg)
	return m, dir
}

// crashConfig returns an AgentConfig that uses the mock_agent and exits after
// delayMs with the given exitCode.
func crashConfig(t *testing.T, id, exitCode string, policy types.RestartPolicy) *types.AgentConfig {
	t.Helper()
	if mockAgentBin == "" {
		t.Skip("mock_agent binary not available")
	}
	return &types.AgentConfig{
		ID:            id,
		Name:          id,
		Command:       mockAgentBin,
		Args:          []string{"--lines", "3", "--delay", "80ms", "--exit-code", exitCode},
		WorkingDir:    t.TempDir(),
		RestartPolicy: policy,
	}
}

// drainUntil reads from events until predicate returns true or timeout expires.
func drainUntil(t *testing.T, events <-chan agent.AgentEvent, predicate func(agent.AgentEvent) bool, timeout time.Duration) agent.AgentEvent {
	t.Helper()
	deadline := time.After(timeout)
	for {
		select {
		case evt := <-events:
			if predicate(evt) {
				return evt
			}
		case <-deadline:
			t.Fatalf("timed out after %s waiting for event", timeout)
			return agent.AgentEvent{} // satisfy compiler; Fatalf stops execution
		}
	}
}

// ---- policy: never -----------------------------------------------------------

func TestRestartPolicy_Never_AgentStaysDead(t *testing.T) {
	if mockAgentBin == "" {
		t.Skip("mock_agent binary not available")
	}

	m, _ := newRestartManager(t)
	agentCfg := crashConfig(t, "never-agent", "1", types.RestartPolicy{Type: "never"})

	if err := m.StartAgent(agentCfg); err != nil {
		t.Fatalf("StartAgent: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	m.StartHealthCheck(ctx)

	// Wait for crash event.
	drainUntil(t, m.Events(), func(e agent.AgentEvent) bool {
		return e.AgentID == "never-agent" && e.Type == agent.EventCrashed
	}, 3*time.Second)

	// Give the restart engine time to (not) act.
	time.Sleep(200 * time.Millisecond)

	// Agent should remain in crashed state; retry count stays at zero.
	if got := m.RestartEngine.RetryCount("never-agent"); got != 0 {
		t.Errorf("expected 0 retries for 'never' policy, got %d", got)
	}

	ma, ok := m.GetAgent("never-agent")
	if !ok {
		t.Fatal("agent not found")
	}
	if ma.State.Status != types.StatusCrashed {
		t.Errorf("expected StatusCrashed, got %q", ma.State.Status)
	}
}

// ---- policy: on-crash --------------------------------------------------------

func TestRestartPolicy_OnCrash_RestartsAfterCrash(t *testing.T) {
	if mockAgentBin == "" {
		t.Skip("mock_agent binary not available")
	}

	m, _ := newRestartManager(t)
	agentCfg := crashConfig(t, "on-crash-agent", "1", types.RestartPolicy{
		Type:       "on-crash",
		MaxRetries: 2,
		BaseDelay:  50 * time.Millisecond,
	})

	if err := m.StartAgent(agentCfg); err != nil {
		t.Fatalf("StartAgent: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	m.StartHealthCheck(ctx)

	// Wait for a restart event.
	drainUntil(t, m.Events(), func(e agent.AgentEvent) bool {
		return e.AgentID == "on-crash-agent" && e.Type == agent.EventRestarted
	}, 5*time.Second)

	// Retry count should now be 1.
	if got := m.RestartEngine.RetryCount("on-crash-agent"); got != 1 {
		t.Errorf("expected retry count 1, got %d", got)
	}

	// Clean up.
	m.KillAgent("on-crash-agent") //nolint:errcheck
}

func TestRestartPolicy_OnCrash_DoesNotRestartCleanExit(t *testing.T) {
	if mockAgentBin == "" {
		t.Skip("mock_agent binary not available")
	}

	m, _ := newRestartManager(t)
	// exit code 0 = clean exit; on-crash should NOT restart.
	agentCfg := crashConfig(t, "clean-exit-agent", "0", types.RestartPolicy{
		Type:       "on-crash",
		MaxRetries: 3,
		BaseDelay:  50 * time.Millisecond,
	})

	if err := m.StartAgent(agentCfg); err != nil {
		t.Fatalf("StartAgent: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	m.StartHealthCheck(ctx)

	// Wait for crash detection (exit code 0 still triggers the health-check crash path).
	drainUntil(t, m.Events(), func(e agent.AgentEvent) bool {
		return e.AgentID == "clean-exit-agent" && e.Type == agent.EventCrashed
	}, 3*time.Second)

	time.Sleep(200 * time.Millisecond)

	// No restart should have been scheduled.
	if got := m.RestartEngine.RetryCount("clean-exit-agent"); got != 0 {
		t.Errorf("expected 0 retries for clean exit with on-crash policy, got %d", got)
	}
}

func TestRestartPolicy_OnCrash_ExhaustsMaxRetries(t *testing.T) {
	if mockAgentBin == "" {
		t.Skip("mock_agent binary not available")
	}

	m, _ := newRestartManager(t)
	// Set MaxRetries=1 so one crash triggers a restart and the second crash stops it.
	agentCfg := crashConfig(t, "max-retry-agent", "1", types.RestartPolicy{
		Type:       "on-crash",
		MaxRetries: 1,
		BaseDelay:  50 * time.Millisecond,
	})

	if err := m.StartAgent(agentCfg); err != nil {
		t.Fatalf("StartAgent: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	m.StartHealthCheck(ctx)

	// First crash -> restart.
	drainUntil(t, m.Events(), func(e agent.AgentEvent) bool {
		return e.AgentID == "max-retry-agent" && e.Type == agent.EventRestarted
	}, 5*time.Second)

	// Second crash -> no more restarts (maxRetries=1 exhausted).
	drainUntil(t, m.Events(), func(e agent.AgentEvent) bool {
		return e.AgentID == "max-retry-agent" && e.Type == agent.EventCrashed
	}, 5*time.Second)

	// Allow engine time to decide.
	time.Sleep(300 * time.Millisecond)

	// Retry count should be 1 (not 2).
	if got := m.RestartEngine.RetryCount("max-retry-agent"); got != 1 {
		t.Errorf("expected retry count 1 after max retries exhausted, got %d", got)
	}
}

// ---- policy: always ----------------------------------------------------------

func TestRestartPolicy_Always_RestartsOnCleanExit(t *testing.T) {
	if mockAgentBin == "" {
		t.Skip("mock_agent binary not available")
	}

	m, _ := newRestartManager(t)
	// exit code 0 = clean exit; always policy should still restart.
	agentCfg := crashConfig(t, "always-agent", "0", types.RestartPolicy{
		Type:       "always",
		MaxRetries: 0, // unlimited
		BaseDelay:  50 * time.Millisecond,
	})

	if err := m.StartAgent(agentCfg); err != nil {
		t.Fatalf("StartAgent: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	m.StartHealthCheck(ctx)

	// Wait for at least one restart event.
	drainUntil(t, m.Events(), func(e agent.AgentEvent) bool {
		return e.AgentID == "always-agent" && e.Type == agent.EventRestarted
	}, 5*time.Second)

	m.KillAgent("always-agent") //nolint:errcheck
}

// ---- backoff calculation -----------------------------------------------------

func TestCalculateBackoff_DoublesEachRetry(t *testing.T) {
	m, _ := newRestartManager(t)
	re := m.RestartEngine
	base := 100 * time.Millisecond

	cases := []struct {
		retry    int
		expected time.Duration
	}{
		{0, 100 * time.Millisecond},
		{1, 200 * time.Millisecond},
		{2, 400 * time.Millisecond},
		{3, 800 * time.Millisecond},
		{4, 1600 * time.Millisecond},
	}

	for _, tc := range cases {
		got := re.CalculateBackoff(tc.retry, base)
		if got != tc.expected {
			t.Errorf("retry %d: expected %s, got %s", tc.retry, tc.expected, got)
		}
	}
}

func TestCalculateBackoff_CapsAtFiveMinutes(t *testing.T) {
	m, _ := newRestartManager(t)
	re := m.RestartEngine
	base := time.Second

	// retry=20 would be 2^20 seconds = over 12 days without cap.
	got := re.CalculateBackoff(20, base)
	if got > 5*time.Minute {
		t.Errorf("expected cap at 5 minutes, got %s", got)
	}
	if got != 5*time.Minute {
		t.Errorf("expected exactly 5 minutes, got %s", got)
	}
}

func TestCalculateBackoff_ZeroRetry_ReturnsBase(t *testing.T) {
	m, _ := newRestartManager(t)
	re := m.RestartEngine
	base := 250 * time.Millisecond

	got := re.CalculateBackoff(0, base)
	if got != base {
		t.Errorf("expected base delay %s for retry 0, got %s", base, got)
	}
}

// ---- retry count reset -------------------------------------------------------

func TestResetRetryCount_ClearsCounter(t *testing.T) {
	if mockAgentBin == "" {
		t.Skip("mock_agent binary not available")
	}

	m, _ := newRestartManager(t)
	agentCfg := crashConfig(t, "reset-agent", "1", types.RestartPolicy{
		Type:       "on-crash",
		MaxRetries: 5,
		BaseDelay:  50 * time.Millisecond,
	})

	if err := m.StartAgent(agentCfg); err != nil {
		t.Fatalf("StartAgent: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	m.StartHealthCheck(ctx)

	// Wait for first restart.
	drainUntil(t, m.Events(), func(e agent.AgentEvent) bool {
		return e.AgentID == "reset-agent" && e.Type == agent.EventRestarted
	}, 5*time.Second)

	if got := m.RestartEngine.RetryCount("reset-agent"); got == 0 {
		t.Error("expected retry count > 0 before reset")
	}

	// Manual stop then reset.
	m.KillAgent("reset-agent") //nolint:errcheck
	m.RestartEngine.ResetRetryCount("reset-agent")

	if got := m.RestartEngine.RetryCount("reset-agent"); got != 0 {
		t.Errorf("expected 0 after reset, got %d", got)
	}
}

// ---- crash tombstone ---------------------------------------------------------

func TestCrashTombstone_CreatedOnCrash(t *testing.T) {
	if mockAgentBin == "" {
		t.Skip("mock_agent binary not available")
	}

	m, dataDir := newRestartManager(t)
	agentCfg := crashConfig(t, "tombstone-agent", "2", types.RestartPolicy{Type: "never"})

	if err := m.StartAgent(agentCfg); err != nil {
		t.Fatalf("StartAgent: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	m.StartHealthCheck(ctx)

	// Wait for crash.
	drainUntil(t, m.Events(), func(e agent.AgentEvent) bool {
		return e.AgentID == "tombstone-agent" && e.Type == agent.EventCrashed
	}, 3*time.Second)

	// Give the restart engine time to write the tombstone.
	time.Sleep(200 * time.Millisecond)

	// Look for a crash-*.json file in the history directory.
	histDir := filepath.Join(dataDir, "history", "tombstone-agent")
	entries, err := os.ReadDir(histDir)
	if err != nil {
		t.Fatalf("read history dir: %v", err)
	}

	var tombstoneFile string
	for _, e := range entries {
		if len(e.Name()) > 6 && e.Name()[:6] == "crash-" {
			tombstoneFile = filepath.Join(histDir, e.Name())
			break
		}
	}
	if tombstoneFile == "" {
		t.Fatal("no crash tombstone file found")
	}

	raw, err := os.ReadFile(tombstoneFile)
	if err != nil {
		t.Fatalf("read tombstone: %v", err)
	}

	var tombstone agent.CrashTombstone
	if err := json.Unmarshal(raw, &tombstone); err != nil {
		t.Fatalf("parse tombstone: %v", err)
	}

	if tombstone.AgentID != "tombstone-agent" {
		t.Errorf("tombstone agent_id: got %q, want %q", tombstone.AgentID, "tombstone-agent")
	}
	if tombstone.ExitCode != 2 {
		t.Errorf("tombstone exit_code: got %d, want 2", tombstone.ExitCode)
	}
	if tombstone.WillRestart {
		t.Error("tombstone will_restart: expected false for 'never' policy")
	}
}

func TestCrashTombstone_WillRestart_True_WhenPolicyAllows(t *testing.T) {
	if mockAgentBin == "" {
		t.Skip("mock_agent binary not available")
	}

	m, dataDir := newRestartManager(t)
	agentCfg := crashConfig(t, "tombstone-restart-agent", "1", types.RestartPolicy{
		Type:       "on-crash",
		MaxRetries: 3,
		BaseDelay:  50 * time.Millisecond,
	})

	if err := m.StartAgent(agentCfg); err != nil {
		t.Fatalf("StartAgent: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	m.StartHealthCheck(ctx)

	// Wait for restart.
	drainUntil(t, m.Events(), func(e agent.AgentEvent) bool {
		return e.AgentID == "tombstone-restart-agent" && e.Type == agent.EventRestarted
	}, 5*time.Second)

	m.KillAgent("tombstone-restart-agent") //nolint:errcheck

	histDir := filepath.Join(dataDir, "history", "tombstone-restart-agent")
	entries, err := os.ReadDir(histDir)
	if err != nil {
		t.Fatalf("read history dir: %v", err)
	}

	var tombstoneFile string
	for _, e := range entries {
		if len(e.Name()) > 6 && e.Name()[:6] == "crash-" {
			tombstoneFile = filepath.Join(histDir, e.Name())
			break
		}
	}
	if tombstoneFile == "" {
		t.Fatal("no crash tombstone file found")
	}

	raw, err := os.ReadFile(tombstoneFile)
	if err != nil {
		t.Fatalf("read tombstone: %v", err)
	}

	var tombstone agent.CrashTombstone
	if err := json.Unmarshal(raw, &tombstone); err != nil {
		t.Fatalf("parse tombstone: %v", err)
	}

	if !tombstone.WillRestart {
		t.Error("tombstone will_restart: expected true when policy permits restart")
	}
}

// ---- terminal bell -----------------------------------------------------------

func TestTerminalBell_EmittedOnCrash(t *testing.T) {
	if mockAgentBin == "" {
		t.Skip("mock_agent binary not available")
	}

	m, _ := newRestartManager(t)

	// Redirect the bell output to a thread-safe buffer for inspection.
	var buf safeBuffer
	m.RestartEngine.SetBellWriter(&buf)

	agentCfg := crashConfig(t, "bell-agent", "1", types.RestartPolicy{Type: "never"})

	if err := m.StartAgent(agentCfg); err != nil {
		t.Fatalf("StartAgent: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	m.StartHealthCheck(ctx)

	drainUntil(t, m.Events(), func(e agent.AgentEvent) bool {
		return e.AgentID == "bell-agent" && e.Type == agent.EventCrashed
	}, 3*time.Second)

	// Give HandleCrash time to run.
	time.Sleep(200 * time.Millisecond)

	if !bytes.Contains(buf.Bytes(), []byte("\a")) {
		t.Errorf("expected terminal bell (\\a) in output, got: %q", buf.Bytes())
	}
}

// ---- WriteCrashTombstone (unit) ----------------------------------------------

func TestWriteCrashTombstone_AtomicWrite(t *testing.T) {
	dir := t.TempDir()
	tombstone := &agent.CrashTombstone{
		AgentID:      "unit-agent",
		CrashedAt:    time.Date(2024, 1, 15, 12, 0, 0, 0, time.UTC),
		ExitCode:     3,
		LastLogLines: []string{"line 1", "line 2"},
		RestartCount: 2,
		WillRestart:  false,
	}

	if err := agent.WriteCrashTombstone(dir, tombstone); err != nil {
		t.Fatalf("WriteCrashTombstone: %v", err)
	}

	histDir := filepath.Join(dir, "history", "unit-agent")
	entries, err := os.ReadDir(histDir)
	if err != nil {
		t.Fatalf("read history dir: %v", err)
	}
	if len(entries) != 1 {
		t.Fatalf("expected 1 file, got %d", len(entries))
	}

	raw, err := os.ReadFile(filepath.Join(histDir, entries[0].Name()))
	if err != nil {
		t.Fatalf("read tombstone: %v", err)
	}

	var got agent.CrashTombstone
	if err := json.Unmarshal(raw, &got); err != nil {
		t.Fatalf("parse tombstone: %v", err)
	}

	if got.AgentID != tombstone.AgentID {
		t.Errorf("AgentID: got %q, want %q", got.AgentID, tombstone.AgentID)
	}
	if got.ExitCode != tombstone.ExitCode {
		t.Errorf("ExitCode: got %d, want %d", got.ExitCode, tombstone.ExitCode)
	}
	if len(got.LastLogLines) != len(tombstone.LastLogLines) {
		t.Errorf("LastLogLines length: got %d, want %d", len(got.LastLogLines), len(tombstone.LastLogLines))
	}
	if got.RestartCount != tombstone.RestartCount {
		t.Errorf("RestartCount: got %d, want %d", got.RestartCount, tombstone.RestartCount)
	}
}

func TestWriteCrashTombstone_FilePermissions(t *testing.T) {
	dir := t.TempDir()
	tombstone := &agent.CrashTombstone{
		AgentID:   "perm-agent",
		CrashedAt: time.Now(),
		ExitCode:  1,
	}

	if err := agent.WriteCrashTombstone(dir, tombstone); err != nil {
		t.Fatalf("WriteCrashTombstone: %v", err)
	}

	histDir := filepath.Join(dir, "history", "perm-agent")
	entries, err := os.ReadDir(histDir)
	if err != nil {
		t.Fatalf("read history dir: %v", err)
	}

	info, err := os.Stat(filepath.Join(histDir, entries[0].Name()))
	if err != nil {
		t.Fatalf("stat: %v", err)
	}
	if info.Mode().Perm() != 0600 {
		t.Errorf("expected 0600, got %04o", info.Mode().Perm())
	}
}
