// Package types defines shared data structures used across the agent-manager.
package types

import (
	"fmt"
	"regexp"
	"time"
)

// validID matches agent and session IDs: alphanumeric, hyphens, underscores.
var validID = regexp.MustCompile(`^[a-zA-Z0-9_-]+$`)

// AgentStatus represents the lifecycle state of a managed agent process.
type AgentStatus string

const (
	StatusRunning    AgentStatus = "running"
	StatusStopped    AgentStatus = "stopped"
	StatusCrashed    AgentStatus = "crashed"
	StatusHanging    AgentStatus = "hanging"
	StatusRestarting AgentStatus = "restarting"
)

// RestartPolicy controls how the manager handles agent process exits.
type RestartPolicy struct {
	Type       string        `json:"type"`        // "never", "on-crash", "always"
	MaxRetries int           `json:"max_retries"` // 0 = unlimited
	BaseDelay  time.Duration `json:"base_delay"`  // exponential backoff base
}

// Validate returns an error if the restart policy is misconfigured.
func (r RestartPolicy) Validate() error {
	switch r.Type {
	case "never", "on-crash", "always":
		// valid
	default:
		return fmt.Errorf("invalid restart policy type %q: must be never, on-crash, or always", r.Type)
	}
	if r.MaxRetries < 0 {
		return fmt.Errorf("max_retries must be >= 0, got %d", r.MaxRetries)
	}
	if r.BaseDelay < 0 {
		return fmt.Errorf("base_delay must be >= 0, got %s", r.BaseDelay)
	}
	return nil
}

// AgentConfig is the persisted configuration for a single managed agent.
type AgentConfig struct {
	ID            string            `json:"id"`
	Name          string            `json:"name"`
	Command       string            `json:"command"`
	Args          []string          `json:"args,omitempty"`
	WorkingDir    string            `json:"working_dir"`
	Env           map[string]string `json:"env,omitempty"`
	Model         string            `json:"model,omitempty"`
	RestartPolicy RestartPolicy     `json:"restart_policy"`
}

// Validate returns an error if the agent config is missing required fields or
// contains an invalid ID (which would allow path traversal).
func (a AgentConfig) Validate() error {
	if a.ID == "" {
		return fmt.Errorf("agent ID must not be empty")
	}
	if !validID.MatchString(a.ID) {
		return fmt.Errorf("agent ID %q is invalid: only alphanumeric, hyphens, and underscores are allowed", a.ID)
	}
	if a.Command == "" {
		return fmt.Errorf("agent %q: command must not be empty", a.ID)
	}
	if a.WorkingDir == "" {
		return fmt.Errorf("agent %q: working_dir must not be empty", a.ID)
	}
	return a.RestartPolicy.Validate()
}

// Session is a named, saved grouping of agent configs that can be launched together.
type Session struct {
	ID          string        `json:"id"`
	Name        string        `json:"name"`
	Description string        `json:"description,omitempty"`
	Agents      []AgentConfig `json:"agents"`
}

// Validate returns an error if the session or any of its agent configs are invalid.
func (s Session) Validate() error {
	if s.ID == "" {
		return fmt.Errorf("session ID must not be empty")
	}
	if !validID.MatchString(s.ID) {
		return fmt.Errorf("session ID %q is invalid: only alphanumeric, hyphens, and underscores are allowed", s.ID)
	}
	if s.Name == "" {
		return fmt.Errorf("session %q: name must not be empty", s.ID)
	}
	for i, agent := range s.Agents {
		if err := agent.Validate(); err != nil {
			return fmt.Errorf("session %q agent[%d]: %w", s.ID, i, err)
		}
	}
	return nil
}

// AgentState holds the runtime state of an agent managed by the process supervisor.
type AgentState struct {
	Config       AgentConfig
	PID          int
	Status       AgentStatus
	StartedAt    time.Time
	ExitCode     int
	RestartCount int
}

// RunRecord is a historical record written after an agent process exits.
type RunRecord struct {
	AgentID      string    `json:"agent_id"`
	StartedAt    time.Time `json:"started_at"`
	StoppedAt    time.Time `json:"stopped_at"`
	ExitCode     int       `json:"exit_code"`
	LastLogLines []string  `json:"last_log_lines"`
	RestartCount int       `json:"restart_count"`
}

// ValidateID returns an error if id is empty or contains characters that could
// allow path traversal when used as a filename.
func ValidateID(id string) error {
	if id == "" {
		return fmt.Errorf("ID must not be empty")
	}
	if !validID.MatchString(id) {
		return fmt.Errorf("ID %q is invalid: only alphanumeric, hyphens, and underscores are allowed", id)
	}
	return nil
}
