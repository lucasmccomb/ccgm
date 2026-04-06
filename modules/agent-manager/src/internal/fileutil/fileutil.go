// Package fileutil provides safe file I/O helpers for the agent-manager.
package fileutil

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

// AtomicWriteJSON serializes data as indented JSON and writes it to path using
// an atomic write: it writes to a .tmp sibling file first, then renames into
// place. The destination file will have the permissions specified by perm.
func AtomicWriteJSON(path string, data interface{}, perm os.FileMode) error {
	b, err := json.MarshalIndent(data, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal JSON for %s: %w", path, err)
	}

	tmpPath := path + ".tmp"
	if err := os.WriteFile(tmpPath, b, perm); err != nil {
		return fmt.Errorf("write temp file %s: %w", tmpPath, err)
	}
	// Ensure permissions are exact even if the file already existed with
	// different permissions (WriteFile only sets perms for new files on some
	// platforms).
	if err := os.Chmod(tmpPath, perm); err != nil {
		_ = os.Remove(tmpPath)
		return fmt.Errorf("chmod temp file %s: %w", tmpPath, err)
	}
	if err := os.Rename(tmpPath, path); err != nil {
		_ = os.Remove(tmpPath)
		return fmt.Errorf("rename %s -> %s: %w", tmpPath, path, err)
	}
	return nil
}

// EnsureDir creates dir with the given permissions if it does not already exist.
func EnsureDir(dir string, perm os.FileMode) error {
	if err := os.MkdirAll(dir, perm); err != nil {
		return fmt.Errorf("create directory %s: %w", dir, err)
	}
	// Explicitly chmod in case the directory already existed with other perms.
	if err := os.Chmod(dir, perm); err != nil {
		return fmt.Errorf("chmod directory %s: %w", dir, err)
	}
	return nil
}

// ReadJSON reads the file at path and unmarshals it into dst.
func ReadJSON(path string, dst interface{}) error {
	b, err := os.ReadFile(path)
	if err != nil {
		return fmt.Errorf("read %s: %w", path, err)
	}
	if err := json.Unmarshal(b, dst); err != nil {
		return fmt.Errorf("parse JSON %s: %w", path, err)
	}
	return nil
}

// Basename returns the filename of path without directory or extension.
func Basename(path string) string {
	base := filepath.Base(path)
	ext := filepath.Ext(base)
	return base[:len(base)-len(ext)]
}
