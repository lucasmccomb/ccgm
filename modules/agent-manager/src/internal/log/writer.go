// writer.go writes captured agent log lines to disk with simple rotation.
// When latest.log exceeds maxSize, it is renamed to previous.log and a new
// latest.log is opened. CleanupOldHistory removes files older than a
// configurable number of days from a history directory.
package log

import (
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"
)

const (
	latestLogName   = "latest.log"
	previousLogName = "previous.log"
)

// LogWriter writes LogLines to a rotating log file pair (latest.log /
// previous.log) under baseDir. All file access is serialised by mu.
type LogWriter struct {
	baseDir     string
	maxSize     int64
	mu          sync.Mutex
	currentFile *os.File
	currentSize int64
}

// NewLogWriter creates baseDir if needed, opens (or creates) latest.log, and
// returns a ready-to-use LogWriter. File permissions are 0600; directories
// are created with 0700.
func NewLogWriter(baseDir string, maxSize int64) (*LogWriter, error) {
	if err := os.MkdirAll(baseDir, 0700); err != nil {
		return nil, fmt.Errorf("log writer: create dir %s: %w", baseDir, err)
	}
	// Explicitly set permissions in case the directory already existed.
	if err := os.Chmod(baseDir, 0700); err != nil {
		return nil, fmt.Errorf("log writer: chmod dir %s: %w", baseDir, err)
	}

	w := &LogWriter{
		baseDir: baseDir,
		maxSize: maxSize,
	}
	if err := w.openLatest(); err != nil {
		return nil, err
	}
	return w, nil
}

// Write appends line to latest.log as a formatted text entry, rotating first
// if the current file has reached maxSize.
func (w *LogWriter) Write(line LogLine) error {
	w.mu.Lock()
	defer w.mu.Unlock()

	if w.currentSize >= w.maxSize {
		if err := w.rotateLocked(); err != nil {
			return fmt.Errorf("log writer: rotate: %w", err)
		}
	}

	stream := "stdout"
	if line.IsStderr {
		stream = "stderr"
	}
	entry := fmt.Sprintf("[%s] [%s] %s\n",
		line.Timestamp.UTC().Format(time.RFC3339),
		stream,
		line.Text,
	)

	n, err := fmt.Fprint(w.currentFile, entry)
	if err != nil {
		return fmt.Errorf("log writer: write: %w", err)
	}
	w.currentSize += int64(n)
	return nil
}

// Rotate explicitly renames latest.log to previous.log and opens a fresh
// latest.log. The old previous.log is overwritten if present.
func (w *LogWriter) Rotate() error {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.rotateLocked()
}

// rotateLocked performs the rename and open without acquiring mu. The caller
// must hold mu.
func (w *LogWriter) rotateLocked() error {
	if w.currentFile != nil {
		if err := w.currentFile.Close(); err != nil {
			return fmt.Errorf("close latest.log: %w", err)
		}
		w.currentFile = nil
	}

	latestPath := filepath.Join(w.baseDir, latestLogName)
	prevPath := filepath.Join(w.baseDir, previousLogName)

	// Rename latest -> previous (overwrites any existing previous.log).
	if _, err := os.Stat(latestPath); err == nil {
		if err := os.Rename(latestPath, prevPath); err != nil {
			return fmt.Errorf("rename latest.log to previous.log: %w", err)
		}
	}

	return w.openLatestLocked()
}

// Close flushes and closes the underlying log file.
func (w *LogWriter) Close() error {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.currentFile == nil {
		return nil
	}
	err := w.currentFile.Close()
	w.currentFile = nil
	return err
}

// openLatest opens latest.log for appending, creating it if necessary.
// Acquires mu internally; used only during construction.
func (w *LogWriter) openLatest() error {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.openLatestLocked()
}

// openLatestLocked opens latest.log without acquiring mu. The caller must hold mu.
func (w *LogWriter) openLatestLocked() error {
	path := filepath.Join(w.baseDir, latestLogName)
	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		return fmt.Errorf("log writer: open latest.log: %w", err)
	}
	// Ensure permissions on existing files.
	if err := os.Chmod(path, 0600); err != nil {
		_ = f.Close()
		return fmt.Errorf("log writer: chmod latest.log: %w", err)
	}

	info, err := f.Stat()
	if err != nil {
		_ = f.Close()
		return fmt.Errorf("log writer: stat latest.log: %w", err)
	}

	w.currentFile = f
	w.currentSize = info.Size()
	return nil
}

// CleanupOldHistory removes files inside historyDir whose modification time
// is older than retentionDays days. It does not recurse into subdirectories.
func CleanupOldHistory(historyDir string, retentionDays int) error {
	entries, err := os.ReadDir(historyDir)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return fmt.Errorf("cleanup history: read dir %s: %w", historyDir, err)
	}

	cutoff := time.Now().AddDate(0, 0, -retentionDays)

	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		info, err := entry.Info()
		if err != nil {
			// File may have been removed between ReadDir and Info; skip it.
			continue
		}
		if info.ModTime().Before(cutoff) {
			path := filepath.Join(historyDir, entry.Name())
			if err := os.Remove(path); err != nil && !os.IsNotExist(err) {
				return fmt.Errorf("cleanup history: remove %s: %w", path, err)
			}
		}
	}
	return nil
}
