package log_test

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/log"
)

func TestWriter_BasicWrite(t *testing.T) {
	dir := t.TempDir()
	w, err := log.NewLogWriter(dir, 1024*1024) // 1 MB
	if err != nil {
		t.Fatalf("NewLogWriter: %v", err)
	}
	defer w.Close()

	line := log.LogLine{Text: "hello world", IsStderr: false, Timestamp: time.Now()}
	if err := w.Write(line); err != nil {
		t.Fatalf("Write: %v", err)
	}

	data, err := os.ReadFile(filepath.Join(dir, "latest.log"))
	if err != nil {
		t.Fatalf("read latest.log: %v", err)
	}
	if len(data) == 0 {
		t.Error("expected non-empty latest.log after write")
	}
}

func TestWriter_RotationTriggersAtMaxSize(t *testing.T) {
	dir := t.TempDir()
	// Set a very small maxSize so rotation triggers after the first write.
	const maxSize = 10 // bytes
	w, err := log.NewLogWriter(dir, maxSize)
	if err != nil {
		t.Fatalf("NewLogWriter: %v", err)
	}
	defer w.Close()

	// First write: fits within maxSize.
	line1 := log.LogLine{Text: "aaa", IsStderr: false, Timestamp: time.Now()}
	if err := w.Write(line1); err != nil {
		t.Fatalf("Write line1: %v", err)
	}

	// Second write: triggers rotation (previous size >= maxSize).
	line2 := log.LogLine{Text: "bbb", IsStderr: false, Timestamp: time.Now()}
	if err := w.Write(line2); err != nil {
		t.Fatalf("Write line2: %v", err)
	}

	// previous.log must exist after rotation.
	if _, err := os.Stat(filepath.Join(dir, "previous.log")); err != nil {
		t.Errorf("expected previous.log to exist after rotation: %v", err)
	}

	// latest.log must also exist (newly created after rotation).
	if _, err := os.Stat(filepath.Join(dir, "latest.log")); err != nil {
		t.Errorf("expected latest.log to exist after rotation: %v", err)
	}
}

func TestWriter_RotationCreatesPreviousLog(t *testing.T) {
	dir := t.TempDir()
	w, err := log.NewLogWriter(dir, 50)
	if err != nil {
		t.Fatalf("NewLogWriter: %v", err)
	}
	defer w.Close()

	// Write enough to fill the budget.
	for i := 0; i < 5; i++ {
		line := log.LogLine{Text: "rotation-test", IsStderr: false, Timestamp: time.Now()}
		_ = w.Write(line)
	}

	// Explicitly rotate to ensure previous.log is created.
	if err := w.Rotate(); err != nil {
		t.Fatalf("Rotate: %v", err)
	}

	prevPath := filepath.Join(dir, "previous.log")
	if _, err := os.Stat(prevPath); os.IsNotExist(err) {
		t.Error("previous.log does not exist after explicit Rotate")
	}
}

func TestWriter_FilePermissions(t *testing.T) {
	dir := t.TempDir()
	w, err := log.NewLogWriter(dir, 1024*1024)
	if err != nil {
		t.Fatalf("NewLogWriter: %v", err)
	}
	defer w.Close()

	line := log.LogLine{Text: "perm-test", IsStderr: false, Timestamp: time.Now()}
	if err := w.Write(line); err != nil {
		t.Fatalf("Write: %v", err)
	}

	// Check log file permissions.
	latestPath := filepath.Join(dir, "latest.log")
	info, err := os.Stat(latestPath)
	if err != nil {
		t.Fatalf("stat latest.log: %v", err)
	}
	if perm := info.Mode().Perm(); perm != 0600 {
		t.Errorf("latest.log: expected 0600, got %04o", perm)
	}

	// Check directory permissions.
	dirInfo, err := os.Stat(dir)
	if err != nil {
		t.Fatalf("stat dir: %v", err)
	}
	if perm := dirInfo.Mode().Perm(); perm != 0700 {
		t.Errorf("log dir: expected 0700, got %04o", perm)
	}
}

func TestWriter_RotationPreviousLogOverwritten(t *testing.T) {
	dir := t.TempDir()
	w, err := log.NewLogWriter(dir, 1024*1024)
	if err != nil {
		t.Fatalf("NewLogWriter: %v", err)
	}

	// Write first batch, rotate, write second batch, rotate again.
	// The second rotation should overwrite previous.log.
	_ = w.Write(log.LogLine{Text: "first-batch", IsStderr: false, Timestamp: time.Now()})
	if err := w.Rotate(); err != nil {
		t.Fatalf("first Rotate: %v", err)
	}

	_ = w.Write(log.LogLine{Text: "second-batch", IsStderr: false, Timestamp: time.Now()})
	if err := w.Rotate(); err != nil {
		t.Fatalf("second Rotate: %v", err)
	}
	w.Close()

	data, err := os.ReadFile(filepath.Join(dir, "previous.log"))
	if err != nil {
		t.Fatalf("read previous.log: %v", err)
	}
	// After second rotation, previous.log should contain the second batch only.
	if string(data) == "" {
		t.Error("previous.log should not be empty after second rotation")
	}
}

func TestCleanupOldHistory_RemovesOldFiles(t *testing.T) {
	dir := t.TempDir()

	// Create an "old" file by backdating its mtime.
	oldFile := filepath.Join(dir, "old.log")
	if err := os.WriteFile(oldFile, []byte("old"), 0600); err != nil {
		t.Fatalf("create old file: %v", err)
	}
	past := time.Now().AddDate(0, 0, -10) // 10 days ago
	if err := os.Chtimes(oldFile, past, past); err != nil {
		t.Fatalf("chtimes: %v", err)
	}

	// Create a recent file.
	newFile := filepath.Join(dir, "new.log")
	if err := os.WriteFile(newFile, []byte("new"), 0600); err != nil {
		t.Fatalf("create new file: %v", err)
	}

	if err := log.CleanupOldHistory(dir, 7); err != nil {
		t.Fatalf("CleanupOldHistory: %v", err)
	}

	if _, err := os.Stat(oldFile); !os.IsNotExist(err) {
		t.Error("expected old file to be removed")
	}
	if _, err := os.Stat(newFile); err != nil {
		t.Error("expected new file to still exist")
	}
}

func TestCleanupOldHistory_MissingDirIsNoop(t *testing.T) {
	if err := log.CleanupOldHistory("/tmp/does-not-exist-ccgm-test", 7); err != nil {
		t.Errorf("expected no error for missing dir, got: %v", err)
	}
}

func TestCleanupOldHistory_PreservesRecentFiles(t *testing.T) {
	dir := t.TempDir()

	// Write two recent files.
	for _, name := range []string{"a.log", "b.log"} {
		if err := os.WriteFile(filepath.Join(dir, name), []byte("data"), 0600); err != nil {
			t.Fatalf("create %s: %v", name, err)
		}
	}

	if err := log.CleanupOldHistory(dir, 7); err != nil {
		t.Fatalf("CleanupOldHistory: %v", err)
	}

	for _, name := range []string{"a.log", "b.log"} {
		if _, err := os.Stat(filepath.Join(dir, name)); err != nil {
			t.Errorf("expected %s to still exist: %v", name, err)
		}
	}
}
