// Package agent provides process lifecycle management for Claude Code agents.
// manager.go handles config persistence (CRUD). Process management lives in
// process.go and will be implemented in a later epic.
package agent

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/fileutil"
	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/types"
)

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
