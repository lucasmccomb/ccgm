// Package session handles persistence of agent session configs.
// A Session is a named group of agent configs that can be launched together.
package session

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/fileutil"
	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/types"
)

// sessionsDir returns the path to the sessions directory within dataDir.
func sessionsDir(dataDir string) string {
	return filepath.Join(dataDir, "sessions")
}

// sessionPath returns the JSON file path for a given sessionID within dataDir.
// The caller must validate sessionID before calling this function.
func sessionPath(dataDir, sessionID string) string {
	return filepath.Join(sessionsDir(dataDir), sessionID+".json")
}

// LoadSession reads and returns the Session for sessionID from dataDir.
// Returns an error wrapping os.ErrNotExist if the session does not exist.
func LoadSession(dataDir, sessionID string) (*types.Session, error) {
	if err := types.ValidateID(sessionID); err != nil {
		return nil, fmt.Errorf("load session: %w", err)
	}
	path := sessionPath(dataDir, sessionID)
	var s types.Session
	if err := fileutil.ReadJSON(path, &s); err != nil {
		return nil, fmt.Errorf("load session %s: %w", sessionID, err)
	}
	return &s, nil
}

// SaveSession persists s to dataDir/sessions/<s.ID>.json using an atomic
// write with 0600 permissions. s.Validate() must pass before saving.
func SaveSession(dataDir string, s *types.Session) error {
	if err := s.Validate(); err != nil {
		return fmt.Errorf("save session: %w", err)
	}
	dir := sessionsDir(dataDir)
	if err := os.MkdirAll(dir, 0700); err != nil {
		return fmt.Errorf("save session: create sessions dir: %w", err)
	}
	path := sessionPath(dataDir, s.ID)
	if err := fileutil.AtomicWriteJSON(path, s, 0600); err != nil {
		return fmt.Errorf("save session %s: %w", s.ID, err)
	}
	return nil
}

// DeleteSession removes the persisted session for sessionID from dataDir.
// Returns nil if the file does not exist (idempotent delete).
func DeleteSession(dataDir, sessionID string) error {
	if err := types.ValidateID(sessionID); err != nil {
		return fmt.Errorf("delete session: %w", err)
	}
	path := sessionPath(dataDir, sessionID)
	if err := os.Remove(path); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("delete session %s: %w", sessionID, err)
	}
	return nil
}

// ListSessions returns all Sessions persisted in dataDir/sessions/.
// The order of results is not guaranteed.
func ListSessions(dataDir string) ([]*types.Session, error) {
	dir := sessionsDir(dataDir)
	entries, err := os.ReadDir(dir)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("list sessions: %w", err)
	}

	var sessions []*types.Session
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		if filepath.Ext(entry.Name()) != ".json" {
			continue
		}
		id := fileutil.Basename(entry.Name())
		if err := types.ValidateID(id); err != nil {
			continue
		}
		s, err := LoadSession(dataDir, id)
		if err != nil {
			return nil, fmt.Errorf("list sessions: %w", err)
		}
		sessions = append(sessions, s)
	}
	return sessions, nil
}
