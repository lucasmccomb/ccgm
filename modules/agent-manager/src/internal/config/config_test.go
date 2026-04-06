package config_test

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/config"
)

func TestDefaultConfig_NonEmpty(t *testing.T) {
	cfg := config.DefaultConfig()
	if cfg == nil {
		t.Fatal("DefaultConfig returned nil")
	}
	if cfg.DataDir == "" {
		t.Error("DataDir must not be empty")
	}
	if cfg.HealthCheckInterval <= 0 {
		t.Error("HealthCheckInterval must be positive")
	}
	if cfg.HangingTimeout <= 0 {
		t.Error("HangingTimeout must be positive")
	}
	if cfg.LogMaxSize <= 0 {
		t.Error("LogMaxSize must be positive")
	}
	if cfg.LogRetentionDays <= 0 {
		t.Error("LogRetentionDays must be positive")
	}
}

func TestSaveAndLoadConfig_RoundTrip(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "config.json")

	want := &config.GlobalConfig{
		DataDir:             "/tmp/ccgm-test",
		HealthCheckInterval: 5 * time.Second,
		HangingTimeout:      30 * time.Second,
		LogMaxSize:          1024 * 1024,
		LogRetentionDays:    3,
	}

	if err := config.SaveConfig(want, path); err != nil {
		t.Fatalf("SaveConfig: %v", err)
	}

	got, err := config.LoadConfig(path)
	if err != nil {
		t.Fatalf("LoadConfig: %v", err)
	}

	if got.DataDir != want.DataDir {
		t.Errorf("DataDir: got %q, want %q", got.DataDir, want.DataDir)
	}
	if got.HealthCheckInterval != want.HealthCheckInterval {
		t.Errorf("HealthCheckInterval: got %v, want %v", got.HealthCheckInterval, want.HealthCheckInterval)
	}
	if got.HangingTimeout != want.HangingTimeout {
		t.Errorf("HangingTimeout: got %v, want %v", got.HangingTimeout, want.HangingTimeout)
	}
	if got.LogMaxSize != want.LogMaxSize {
		t.Errorf("LogMaxSize: got %d, want %d", got.LogMaxSize, want.LogMaxSize)
	}
	if got.LogRetentionDays != want.LogRetentionDays {
		t.Errorf("LogRetentionDays: got %d, want %d", got.LogRetentionDays, want.LogRetentionDays)
	}
}

func TestLoadConfig_MissingFileReturnsDefault(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "nonexistent.json")

	cfg, err := config.LoadConfig(path)
	if err != nil {
		t.Fatalf("expected no error for missing file, got: %v", err)
	}
	if cfg == nil {
		t.Fatal("expected default config, got nil")
	}
}

func TestSaveConfig_FilePermissions(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "config.json")

	if err := config.SaveConfig(config.DefaultConfig(), path); err != nil {
		t.Fatalf("SaveConfig: %v", err)
	}

	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("stat: %v", err)
	}
	if info.Mode().Perm() != 0600 {
		t.Errorf("expected 0600 permissions, got %04o", info.Mode().Perm())
	}
}

func TestInitDataDir_CreatesSubdirectories(t *testing.T) {
	base := t.TempDir()

	if err := config.InitDataDir(base); err != nil {
		t.Fatalf("InitDataDir: %v", err)
	}

	expectedDirs := []string{"agents", "sessions", "logs", "history", "state"}
	for _, sub := range expectedDirs {
		dir := filepath.Join(base, sub)
		info, err := os.Stat(dir)
		if err != nil {
			t.Errorf("expected directory %s to exist: %v", sub, err)
			continue
		}
		if !info.IsDir() {
			t.Errorf("expected %s to be a directory", sub)
		}
	}
}

func TestInitDataDir_Permissions(t *testing.T) {
	base := t.TempDir()

	if err := config.InitDataDir(base); err != nil {
		t.Fatalf("InitDataDir: %v", err)
	}

	for _, sub := range []string{"agents", "sessions", "logs", "history", "state"} {
		info, err := os.Stat(filepath.Join(base, sub))
		if err != nil {
			t.Errorf("stat %s: %v", sub, err)
			continue
		}
		if info.Mode().Perm() != 0700 {
			t.Errorf("expected 0700 for %s, got %04o", sub, info.Mode().Perm())
		}
	}
}

func TestInitDataDir_Idempotent(t *testing.T) {
	base := t.TempDir()

	if err := config.InitDataDir(base); err != nil {
		t.Fatalf("first InitDataDir: %v", err)
	}
	if err := config.InitDataDir(base); err != nil {
		t.Fatalf("second InitDataDir: %v", err)
	}
}
