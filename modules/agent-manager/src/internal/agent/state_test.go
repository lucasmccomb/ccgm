package agent_test

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/agent"
	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/config"
	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/types"
)

func TestSaveAndLoadRunningState_RoundTrip(t *testing.T) {
	dir := t.TempDir()
	if err := os.MkdirAll(filepath.Join(dir, "state"), 0700); err != nil {
		t.Fatal(err)
	}

	// Build a mock map with one entry (Process is nil; SaveRunningState skips it).
	// We need a real process PID so use os.Getpid() as a stand-in.
	agentCfg := types.AgentConfig{
		ID:         "save-agent",
		Name:       "Save Agent",
		Command:    "/bin/true",
		WorkingDir: "/tmp",
		RestartPolicy: types.RestartPolicy{Type: "never"},
	}
	now := time.Now().UTC().Truncate(time.Second)

	// We test SaveRunningState directly with a nil-Process ManagedAgent.
	// SaveRunningState skips agents with nil Process, so we use the lower-level
	// approach: call the exported functions directly using a struct that
	// embeds a real process.
	//
	// Instead, test via LoadRunningState on a hand-crafted file.
	rs := &agent.RunningState{
		SavedAt: now,
		Agents: []agent.RunningAgentState{
			{
				Config:    agentCfg,
				PID:       os.Getpid(), // guaranteed alive
				StartedAt: now,
			},
		},
	}
	_ = rs // silence linter

	// Use save/load round-trip via a real AgentManager with a live process.
	if mockAgentBin == "" {
		t.Skip("mock_agent binary not available - skipping state round-trip test")
	}

	cfg := &config.GlobalConfig{
		DataDir:             dir,
		HealthCheckInterval: 50 * time.Millisecond,
		HangingTimeout:      5 * time.Second,
	}
	m := agent.NewAgentManager(dir, cfg)

	if err := os.MkdirAll(filepath.Join(dir, "state"), 0700); err != nil {
		t.Fatal(err)
	}

	liveCfg := &types.AgentConfig{
		ID:         "state-agent",
		Name:       "State Agent",
		Command:    mockAgentBin,
		Args:       []string{"--lines", "0", "--delay", "5s"},
		WorkingDir: t.TempDir(),
		RestartPolicy: types.RestartPolicy{Type: "never"},
	}
	if err := m.StartAgent(liveCfg); err != nil {
		t.Fatalf("StartAgent: %v", err)
	}
	defer m.KillAgent("state-agent") //nolint:errcheck

	if err := m.SaveState(); err != nil {
		t.Fatalf("SaveState: %v", err)
	}

	loaded, err := agent.LoadRunningState(dir)
	if err != nil {
		t.Fatalf("LoadRunningState: %v", err)
	}

	if len(loaded.Agents) != 1 {
		t.Fatalf("expected 1 agent in state, got %d", len(loaded.Agents))
	}
	if loaded.Agents[0].Config.ID != "state-agent" {
		t.Errorf("expected agent ID 'state-agent', got %q", loaded.Agents[0].Config.ID)
	}
	if loaded.Agents[0].PID <= 0 {
		t.Errorf("expected positive PID, got %d", loaded.Agents[0].PID)
	}
}

func TestLoadRunningState_MissingFileReturnsEmpty(t *testing.T) {
	dir := t.TempDir()
	rs, err := agent.LoadRunningState(dir)
	if err != nil {
		t.Fatalf("expected no error for missing state, got: %v", err)
	}
	if len(rs.Agents) != 0 {
		t.Errorf("expected 0 agents, got %d", len(rs.Agents))
	}
}

func TestReattachFromState_AlivePID(t *testing.T) {
	dir := t.TempDir()

	agentCfg := types.AgentConfig{
		ID:         "reattach-alive",
		Name:       "Reattach Alive",
		Command:    "/bin/true",
		WorkingDir: "/tmp",
		RestartPolicy: types.RestartPolicy{Type: "never"},
	}

	// Write a state file with the current process PID (always alive).
	rs := &agent.RunningState{
		SavedAt: time.Now(),
		Agents: []agent.RunningAgentState{
			{
				Config:    agentCfg,
				PID:       os.Getpid(),
				StartedAt: time.Now(),
			},
		},
	}
	if err := agent.SaveRunningStateRaw(dir, rs); err != nil {
		t.Fatalf("SaveRunningStateRaw: %v", err)
	}

	cfg := &config.GlobalConfig{
		DataDir:             dir,
		HealthCheckInterval: 50 * time.Millisecond,
		HangingTimeout:      5 * time.Second,
	}
	m := agent.NewAgentManager(dir, cfg)
	if err := m.ReattachFromState(); err != nil {
		t.Fatalf("ReattachFromState: %v", err)
	}

	ma, ok := m.GetAgent("reattach-alive")
	if !ok {
		t.Fatal("expected agent 'reattach-alive' to be registered after reattach")
	}
	if ma.State.Status != types.StatusRunning {
		t.Errorf("expected status running for alive PID, got %q", ma.State.Status)
	}
}

func TestReattachFromState_DeadPID(t *testing.T) {
	dir := t.TempDir()

	agentCfg := types.AgentConfig{
		ID:         "reattach-dead",
		Name:       "Reattach Dead",
		Command:    "/bin/true",
		WorkingDir: "/tmp",
		RestartPolicy: types.RestartPolicy{Type: "never"},
	}

	// PID 1 is init/launchd - definitely not our agent. Use a PID that is
	// guaranteed not to belong to any process: max pid + 1 would overflow, so
	// use a heuristic: write an implausible PID.
	rs := &agent.RunningState{
		SavedAt: time.Now(),
		Agents: []agent.RunningAgentState{
			{
				Config:    agentCfg,
				PID:       99999999, // extremely unlikely to exist
				StartedAt: time.Now(),
			},
		},
	}
	if err := agent.SaveRunningStateRaw(dir, rs); err != nil {
		t.Fatalf("SaveRunningStateRaw: %v", err)
	}

	cfg := &config.GlobalConfig{
		DataDir:             dir,
		HealthCheckInterval: 50 * time.Millisecond,
		HangingTimeout:      5 * time.Second,
	}
	m := agent.NewAgentManager(dir, cfg)
	if err := m.ReattachFromState(); err != nil {
		t.Fatalf("ReattachFromState: %v", err)
	}

	ma, ok := m.GetAgent("reattach-dead")
	if !ok {
		t.Fatal("expected agent 'reattach-dead' to be registered (as stopped)")
	}
	if ma.State.Status != types.StatusStopped {
		t.Errorf("expected status stopped for dead PID, got %q", ma.State.Status)
	}
}
