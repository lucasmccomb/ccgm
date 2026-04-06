package agent_test

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/agent"
	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/types"
)

func validConfig(id string) *types.AgentConfig {
	return &types.AgentConfig{
		ID:         id,
		Name:       "Test Agent " + id,
		Command:    "claude",
		WorkingDir: "/tmp/work",
		RestartPolicy: types.RestartPolicy{
			Type:       "on-crash",
			MaxRetries: 3,
			BaseDelay:  time.Second,
		},
	}
}

func TestSaveAndLoadAgentConfig_RoundTrip(t *testing.T) {
	dir := t.TempDir()
	cfg := validConfig("agent-1")

	if err := agent.SaveAgentConfig(dir, cfg); err != nil {
		t.Fatalf("SaveAgentConfig: %v", err)
	}

	got, err := agent.LoadAgentConfig(dir, "agent-1")
	if err != nil {
		t.Fatalf("LoadAgentConfig: %v", err)
	}
	if got.ID != cfg.ID {
		t.Errorf("ID: got %q, want %q", got.ID, cfg.ID)
	}
	if got.Command != cfg.Command {
		t.Errorf("Command: got %q, want %q", got.Command, cfg.Command)
	}
	if got.WorkingDir != cfg.WorkingDir {
		t.Errorf("WorkingDir: got %q, want %q", got.WorkingDir, cfg.WorkingDir)
	}
}

func TestSaveAgentConfig_FilePermissions(t *testing.T) {
	dir := t.TempDir()
	cfg := validConfig("agent-perm")

	if err := agent.SaveAgentConfig(dir, cfg); err != nil {
		t.Fatalf("SaveAgentConfig: %v", err)
	}

	path := filepath.Join(dir, "agents", "agent-perm.json")
	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("stat: %v", err)
	}
	if info.Mode().Perm() != 0600 {
		t.Errorf("expected 0600 permissions, got %04o", info.Mode().Perm())
	}
}

func TestSaveAgentConfig_InvalidConfigRejected(t *testing.T) {
	dir := t.TempDir()
	cfg := validConfig("good-id")
	cfg.Command = "" // make invalid

	if err := agent.SaveAgentConfig(dir, cfg); err == nil {
		t.Error("expected error for invalid config, got nil")
	}
}

func TestLoadAgentConfig_NotFound(t *testing.T) {
	dir := t.TempDir()
	// Create agents dir to avoid a missing-dir error.
	if err := os.MkdirAll(filepath.Join(dir, "agents"), 0700); err != nil {
		t.Fatal(err)
	}

	_, err := agent.LoadAgentConfig(dir, "nonexistent")
	if err == nil {
		t.Error("expected error for missing agent, got nil")
	}
}

func TestLoadAgentConfig_PathTraversalRejected(t *testing.T) {
	dir := t.TempDir()
	malicious := []string{
		"../secret",
		"agent/../etc",
		"agent/sub",
		"agent id",
	}
	for _, id := range malicious {
		_, err := agent.LoadAgentConfig(dir, id)
		if err == nil {
			t.Errorf("expected error for malicious ID %q, got nil", id)
		}
	}
}

func TestDeleteAgentConfig_RemovesFile(t *testing.T) {
	dir := t.TempDir()
	cfg := validConfig("agent-del")

	if err := agent.SaveAgentConfig(dir, cfg); err != nil {
		t.Fatalf("SaveAgentConfig: %v", err)
	}
	if err := agent.DeleteAgentConfig(dir, "agent-del"); err != nil {
		t.Fatalf("DeleteAgentConfig: %v", err)
	}
	if _, err := agent.LoadAgentConfig(dir, "agent-del"); err == nil {
		t.Error("expected error after deletion, got nil")
	}
}

func TestDeleteAgentConfig_Idempotent(t *testing.T) {
	dir := t.TempDir()
	// Delete non-existent agent should not error.
	if err := os.MkdirAll(filepath.Join(dir, "agents"), 0700); err != nil {
		t.Fatal(err)
	}
	if err := agent.DeleteAgentConfig(dir, "no-such-agent"); err != nil {
		t.Errorf("expected no error for idempotent delete, got: %v", err)
	}
}

func TestDeleteAgentConfig_PathTraversalRejected(t *testing.T) {
	dir := t.TempDir()
	if err := agent.DeleteAgentConfig(dir, "../secret"); err == nil {
		t.Error("expected error for path traversal ID, got nil")
	}
}

func TestListAgentConfigs_Empty(t *testing.T) {
	dir := t.TempDir()
	if err := os.MkdirAll(filepath.Join(dir, "agents"), 0700); err != nil {
		t.Fatal(err)
	}

	configs, err := agent.ListAgentConfigs(dir)
	if err != nil {
		t.Fatalf("ListAgentConfigs: %v", err)
	}
	if len(configs) != 0 {
		t.Errorf("expected 0 configs, got %d", len(configs))
	}
}

func TestListAgentConfigs_Multiple(t *testing.T) {
	dir := t.TempDir()
	ids := []string{"agent-a", "agent-b", "agent-c"}

	for _, id := range ids {
		if err := agent.SaveAgentConfig(dir, validConfig(id)); err != nil {
			t.Fatalf("SaveAgentConfig %s: %v", id, err)
		}
	}

	configs, err := agent.ListAgentConfigs(dir)
	if err != nil {
		t.Fatalf("ListAgentConfigs: %v", err)
	}
	if len(configs) != len(ids) {
		t.Errorf("expected %d configs, got %d", len(ids), len(configs))
	}

	found := make(map[string]bool)
	for _, c := range configs {
		found[c.ID] = true
	}
	for _, id := range ids {
		if !found[id] {
			t.Errorf("expected agent %q in list, not found", id)
		}
	}
}

func TestListAgentConfigs_MissingDirReturnsEmpty(t *testing.T) {
	dir := t.TempDir()
	// Do NOT create agents dir - should return empty, not error.
	configs, err := agent.ListAgentConfigs(dir)
	if err != nil {
		t.Fatalf("expected no error for missing dir, got: %v", err)
	}
	if len(configs) != 0 {
		t.Errorf("expected 0 configs, got %d", len(configs))
	}
}
