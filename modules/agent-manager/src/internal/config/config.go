// Package config loads and validates ccgm-agents runtime configuration.
package config

import (
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/fileutil"
)

const (
	configFileName = "config.json"

	defaultHealthCheckInterval = 2 * time.Second
	defaultHangingTimeout      = 60 * time.Second
	defaultLogMaxSize          = 50 * 1024 * 1024 // 50 MB
	defaultLogRetentionDays    = 7
)

// GlobalConfig holds runtime settings for the agent-manager daemon.
type GlobalConfig struct {
	DataDir             string        `json:"data_dir"`
	HealthCheckInterval time.Duration `json:"health_check_interval"`
	HangingTimeout      time.Duration `json:"hanging_timeout"`
	LogMaxSize          int64         `json:"log_max_size"`
	LogRetentionDays    int           `json:"log_retention_days"`
}

// DefaultConfig returns a GlobalConfig populated with sensible defaults.
// DataDir defaults to ~/.ccgm/agent-manager.
func DefaultConfig() *GlobalConfig {
	home, err := os.UserHomeDir()
	if err != nil {
		home = "."
	}
	return &GlobalConfig{
		DataDir:             filepath.Join(home, ".ccgm", "agent-manager"),
		HealthCheckInterval: defaultHealthCheckInterval,
		HangingTimeout:      defaultHangingTimeout,
		LogMaxSize:          defaultLogMaxSize,
		LogRetentionDays:    defaultLogRetentionDays,
	}
}

// LoadConfig reads a GlobalConfig from the JSON file at path.
// If path does not exist, DefaultConfig is returned (not an error).
func LoadConfig(path string) (*GlobalConfig, error) {
	cfg := DefaultConfig()
	if _, err := os.Stat(path); os.IsNotExist(err) {
		return cfg, nil
	}
	if err := fileutil.ReadJSON(path, cfg); err != nil {
		return nil, fmt.Errorf("load config: %w", err)
	}
	return cfg, nil
}

// SaveConfig writes cfg to path as JSON using an atomic write and 0600 permissions.
func SaveConfig(cfg *GlobalConfig, path string) error {
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return fmt.Errorf("create config dir: %w", err)
	}
	if err := fileutil.AtomicWriteJSON(path, cfg, 0600); err != nil {
		return fmt.Errorf("save config: %w", err)
	}
	return nil
}

// InitDataDir creates the full directory structure needed by agent-manager
// under baseDir. Directories are created with 0700 permissions.
func InitDataDir(baseDir string) error {
	subdirs := []string{
		"agents",
		"sessions",
		"logs",
		"history",
		"state",
	}
	if err := fileutil.EnsureDir(baseDir, 0700); err != nil {
		return fmt.Errorf("init data dir %s: %w", baseDir, err)
	}
	for _, sub := range subdirs {
		dir := filepath.Join(baseDir, sub)
		if err := fileutil.EnsureDir(dir, 0700); err != nil {
			return fmt.Errorf("init data dir %s: %w", dir, err)
		}
	}
	return nil
}

// ConfigPath returns the default config file path within baseDir.
func ConfigPath(baseDir string) string {
	return filepath.Join(baseDir, configFileName)
}
