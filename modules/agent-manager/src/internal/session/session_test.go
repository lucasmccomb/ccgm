package session_test

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/session"
	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/types"
)

func validAgentConfig(id string) types.AgentConfig {
	return types.AgentConfig{
		ID:         id,
		Name:       "Agent " + id,
		Command:    "claude",
		WorkingDir: "/tmp/work",
		RestartPolicy: types.RestartPolicy{
			Type:       "never",
			MaxRetries: 0,
			BaseDelay:  time.Second,
		},
	}
}

func validSession(id string) *types.Session {
	return &types.Session{
		ID:          id,
		Name:        "Session " + id,
		Description: "test session",
		Agents:      []types.AgentConfig{validAgentConfig("agent-1")},
	}
}

func TestSaveAndLoadSession_RoundTrip(t *testing.T) {
	dir := t.TempDir()
	s := validSession("session-1")

	if err := session.SaveSession(dir, s); err != nil {
		t.Fatalf("SaveSession: %v", err)
	}

	got, err := session.LoadSession(dir, "session-1")
	if err != nil {
		t.Fatalf("LoadSession: %v", err)
	}
	if got.ID != s.ID {
		t.Errorf("ID: got %q, want %q", got.ID, s.ID)
	}
	if got.Name != s.Name {
		t.Errorf("Name: got %q, want %q", got.Name, s.Name)
	}
	if got.Description != s.Description {
		t.Errorf("Description: got %q, want %q", got.Description, s.Description)
	}
	if len(got.Agents) != len(s.Agents) {
		t.Errorf("Agents length: got %d, want %d", len(got.Agents), len(s.Agents))
	}
}

func TestSaveSession_FilePermissions(t *testing.T) {
	dir := t.TempDir()
	s := validSession("session-perm")

	if err := session.SaveSession(dir, s); err != nil {
		t.Fatalf("SaveSession: %v", err)
	}

	path := filepath.Join(dir, "sessions", "session-perm.json")
	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("stat: %v", err)
	}
	if info.Mode().Perm() != 0600 {
		t.Errorf("expected 0600 permissions, got %04o", info.Mode().Perm())
	}
}

func TestSaveSession_InvalidSessionRejected(t *testing.T) {
	dir := t.TempDir()
	s := validSession("ok-id")
	s.Name = "" // make invalid

	if err := session.SaveSession(dir, s); err == nil {
		t.Error("expected error for invalid session, got nil")
	}
}

func TestSaveSession_PathTraversalIDRejected(t *testing.T) {
	dir := t.TempDir()
	s := validSession("ok-id")
	s.ID = "../secret"

	if err := session.SaveSession(dir, s); err == nil {
		t.Error("expected error for path traversal session ID, got nil")
	}
}

func TestLoadSession_NotFound(t *testing.T) {
	dir := t.TempDir()
	if err := os.MkdirAll(filepath.Join(dir, "sessions"), 0700); err != nil {
		t.Fatal(err)
	}

	_, err := session.LoadSession(dir, "no-such-session")
	if err == nil {
		t.Error("expected error for missing session, got nil")
	}
}

func TestLoadSession_PathTraversalRejected(t *testing.T) {
	dir := t.TempDir()
	malicious := []string{
		"../secret",
		"session/../etc",
		"session/sub",
	}
	for _, id := range malicious {
		_, err := session.LoadSession(dir, id)
		if err == nil {
			t.Errorf("expected error for malicious ID %q, got nil", id)
		}
	}
}

func TestDeleteSession_RemovesFile(t *testing.T) {
	dir := t.TempDir()
	s := validSession("session-del")

	if err := session.SaveSession(dir, s); err != nil {
		t.Fatalf("SaveSession: %v", err)
	}
	if err := session.DeleteSession(dir, "session-del"); err != nil {
		t.Fatalf("DeleteSession: %v", err)
	}
	if _, err := session.LoadSession(dir, "session-del"); err == nil {
		t.Error("expected error after deletion, got nil")
	}
}

func TestDeleteSession_Idempotent(t *testing.T) {
	dir := t.TempDir()
	if err := os.MkdirAll(filepath.Join(dir, "sessions"), 0700); err != nil {
		t.Fatal(err)
	}
	if err := session.DeleteSession(dir, "no-such-session"); err != nil {
		t.Errorf("expected no error for idempotent delete, got: %v", err)
	}
}

func TestDeleteSession_PathTraversalRejected(t *testing.T) {
	dir := t.TempDir()
	if err := session.DeleteSession(dir, "../secret"); err == nil {
		t.Error("expected error for path traversal ID, got nil")
	}
}

func TestListSessions_Empty(t *testing.T) {
	dir := t.TempDir()
	if err := os.MkdirAll(filepath.Join(dir, "sessions"), 0700); err != nil {
		t.Fatal(err)
	}

	sessions, err := session.ListSessions(dir)
	if err != nil {
		t.Fatalf("ListSessions: %v", err)
	}
	if len(sessions) != 0 {
		t.Errorf("expected 0 sessions, got %d", len(sessions))
	}
}

func TestListSessions_Multiple(t *testing.T) {
	dir := t.TempDir()
	ids := []string{"session-a", "session-b", "session-c"}

	for _, id := range ids {
		if err := session.SaveSession(dir, validSession(id)); err != nil {
			t.Fatalf("SaveSession %s: %v", id, err)
		}
	}

	sessions, err := session.ListSessions(dir)
	if err != nil {
		t.Fatalf("ListSessions: %v", err)
	}
	if len(sessions) != len(ids) {
		t.Errorf("expected %d sessions, got %d", len(ids), len(sessions))
	}

	found := make(map[string]bool)
	for _, s := range sessions {
		found[s.ID] = true
	}
	for _, id := range ids {
		if !found[id] {
			t.Errorf("expected session %q in list, not found", id)
		}
	}
}

func TestListSessions_MissingDirReturnsEmpty(t *testing.T) {
	dir := t.TempDir()
	// Do NOT create sessions dir.
	sessions, err := session.ListSessions(dir)
	if err != nil {
		t.Fatalf("expected no error for missing dir, got: %v", err)
	}
	if len(sessions) != 0 {
		t.Errorf("expected 0 sessions, got %d", len(sessions))
	}
}
