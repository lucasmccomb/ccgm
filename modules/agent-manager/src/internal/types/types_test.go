package types_test

import (
	"testing"
	"time"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/types"
)

// --- RestartPolicy.Validate ---

func TestRestartPolicyValidate_ValidTypes(t *testing.T) {
	for _, typ := range []string{"never", "on-crash", "always"} {
		rp := types.RestartPolicy{Type: typ, MaxRetries: 3, BaseDelay: time.Second}
		if err := rp.Validate(); err != nil {
			t.Errorf("expected valid policy type %q, got error: %v", typ, err)
		}
	}
}

func TestRestartPolicyValidate_InvalidType(t *testing.T) {
	rp := types.RestartPolicy{Type: "sometimes"}
	if err := rp.Validate(); err == nil {
		t.Error("expected error for invalid restart policy type, got nil")
	}
}

func TestRestartPolicyValidate_EmptyType(t *testing.T) {
	rp := types.RestartPolicy{}
	if err := rp.Validate(); err == nil {
		t.Error("expected error for empty restart policy type, got nil")
	}
}

func TestRestartPolicyValidate_NegativeMaxRetries(t *testing.T) {
	rp := types.RestartPolicy{Type: "always", MaxRetries: -1}
	if err := rp.Validate(); err == nil {
		t.Error("expected error for negative max_retries, got nil")
	}
}

func TestRestartPolicyValidate_NegativeBaseDelay(t *testing.T) {
	rp := types.RestartPolicy{Type: "on-crash", MaxRetries: 0, BaseDelay: -time.Second}
	if err := rp.Validate(); err == nil {
		t.Error("expected error for negative base_delay, got nil")
	}
}

// --- AgentConfig.Validate ---

func validAgentConfig() types.AgentConfig {
	return types.AgentConfig{
		ID:         "agent-1",
		Name:       "Test Agent",
		Command:    "claude",
		WorkingDir: "/tmp/work",
		RestartPolicy: types.RestartPolicy{
			Type:       "on-crash",
			MaxRetries: 3,
			BaseDelay:  time.Second,
		},
	}
}

func TestAgentConfigValidate_Valid(t *testing.T) {
	cfg := validAgentConfig()
	if err := cfg.Validate(); err != nil {
		t.Errorf("expected valid config, got error: %v", err)
	}
}

func TestAgentConfigValidate_EmptyID(t *testing.T) {
	cfg := validAgentConfig()
	cfg.ID = ""
	if err := cfg.Validate(); err == nil {
		t.Error("expected error for empty ID, got nil")
	}
}

func TestAgentConfigValidate_EmptyCommand(t *testing.T) {
	cfg := validAgentConfig()
	cfg.Command = ""
	if err := cfg.Validate(); err == nil {
		t.Error("expected error for empty command, got nil")
	}
}

func TestAgentConfigValidate_EmptyWorkingDir(t *testing.T) {
	cfg := validAgentConfig()
	cfg.WorkingDir = ""
	if err := cfg.Validate(); err == nil {
		t.Error("expected error for empty working_dir, got nil")
	}
}

func TestAgentConfigValidate_PathTraversalID(t *testing.T) {
	// IDs that could cause path traversal must be rejected.
	malicious := []string{
		"../../../etc/passwd",
		"agent/../secret",
		"agent/subdir",
		"agent id",
		"agent.id",
		"agent@1",
	}
	for _, id := range malicious {
		cfg := validAgentConfig()
		cfg.ID = id
		if err := cfg.Validate(); err == nil {
			t.Errorf("expected error for malicious ID %q, got nil", id)
		}
	}
}

func TestAgentConfigValidate_ValidIDChars(t *testing.T) {
	validIDs := []string{
		"agent1",
		"agent-1",
		"agent_1",
		"Agent1",
		"AGENT",
		"a",
		"a-b-c_d",
	}
	for _, id := range validIDs {
		cfg := validAgentConfig()
		cfg.ID = id
		if err := cfg.Validate(); err != nil {
			t.Errorf("expected valid ID %q, got error: %v", id, err)
		}
	}
}

func TestAgentConfigValidate_InvalidRestartPolicy(t *testing.T) {
	cfg := validAgentConfig()
	cfg.RestartPolicy = types.RestartPolicy{Type: "bad"}
	if err := cfg.Validate(); err == nil {
		t.Error("expected error for invalid restart policy, got nil")
	}
}

// --- Session.Validate ---

func validSession() types.Session {
	return types.Session{
		ID:   "session-1",
		Name: "My Session",
		Agents: []types.AgentConfig{
			validAgentConfig(),
		},
	}
}

func TestSessionValidate_Valid(t *testing.T) {
	s := validSession()
	if err := s.Validate(); err != nil {
		t.Errorf("expected valid session, got error: %v", err)
	}
}

func TestSessionValidate_EmptyID(t *testing.T) {
	s := validSession()
	s.ID = ""
	if err := s.Validate(); err == nil {
		t.Error("expected error for empty session ID, got nil")
	}
}

func TestSessionValidate_EmptyName(t *testing.T) {
	s := validSession()
	s.Name = ""
	if err := s.Validate(); err == nil {
		t.Error("expected error for empty session name, got nil")
	}
}

func TestSessionValidate_PathTraversalID(t *testing.T) {
	s := validSession()
	s.ID = "../secret"
	if err := s.Validate(); err == nil {
		t.Error("expected error for path traversal session ID, got nil")
	}
}

func TestSessionValidate_InvalidAgent(t *testing.T) {
	s := validSession()
	s.Agents[0].Command = ""
	if err := s.Validate(); err == nil {
		t.Error("expected error for invalid agent in session, got nil")
	}
}

func TestSessionValidate_NoAgents(t *testing.T) {
	// A session with no agents is allowed (it's a config template).
	s := validSession()
	s.Agents = nil
	if err := s.Validate(); err != nil {
		t.Errorf("expected valid empty-agent session, got error: %v", err)
	}
}

// --- ValidateID ---

func TestValidateID_PathTraversal(t *testing.T) {
	bad := []string{
		"../etc",
		"foo/bar",
		"foo bar",
		"",
	}
	for _, id := range bad {
		if err := types.ValidateID(id); err == nil {
			t.Errorf("expected error for ID %q, got nil", id)
		}
	}
}

func TestValidateID_Valid(t *testing.T) {
	good := []string{"foo", "foo-bar", "foo_bar", "FOO123"}
	for _, id := range good {
		if err := types.ValidateID(id); err != nil {
			t.Errorf("expected valid ID %q, got error: %v", id, err)
		}
	}
}
