package log_test

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/log"
)

// writeLogFile is a test helper that creates logDir/filename containing body.
func writeLogFile(t *testing.T, logDir, filename, body string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(logDir, filename), []byte(body), 0600); err != nil {
		t.Fatalf("writeLogFile %s: %v", filename, err)
	}
}

func TestExportLogs_CombinesLatestAndPrevious(t *testing.T) {
	logDir := t.TempDir()
	outDir := t.TempDir()

	writeLogFile(t, logDir, "previous.log", "previous-line\n")
	writeLogFile(t, logDir, "latest.log", "latest-line\n")

	outPath := filepath.Join(outDir, "export.txt")
	if err := log.ExportLogs(logDir, outPath); err != nil {
		t.Fatalf("ExportLogs: %v", err)
	}

	data, err := os.ReadFile(outPath)
	if err != nil {
		t.Fatalf("read export: %v", err)
	}

	combined := string(data)
	if !strings.Contains(combined, "previous-line") {
		t.Error("export missing content from previous.log")
	}
	if !strings.Contains(combined, "latest-line") {
		t.Error("export missing content from latest.log")
	}

	// previous.log should appear before latest.log (chronological order).
	prevIdx := strings.Index(combined, "previous-line")
	latestIdx := strings.Index(combined, "latest-line")
	if prevIdx >= latestIdx {
		t.Errorf("expected previous-line before latest-line in export; prevIdx=%d latestIdx=%d", prevIdx, latestIdx)
	}
}

func TestExportLogs_OnlyLatestLog(t *testing.T) {
	logDir := t.TempDir()
	outDir := t.TempDir()

	writeLogFile(t, logDir, "latest.log", "only-latest\n")

	outPath := filepath.Join(outDir, "export.txt")
	if err := log.ExportLogs(logDir, outPath); err != nil {
		t.Fatalf("ExportLogs: %v", err)
	}

	data, err := os.ReadFile(outPath)
	if err != nil {
		t.Fatalf("read export: %v", err)
	}
	if !strings.Contains(string(data), "only-latest") {
		t.Error("export missing content from latest.log")
	}
}

func TestExportLogs_EmptyLogDir_ProducesEmptyFile(t *testing.T) {
	logDir := t.TempDir()
	outDir := t.TempDir()

	outPath := filepath.Join(outDir, "export.txt")
	if err := log.ExportLogs(logDir, outPath); err != nil {
		t.Fatalf("ExportLogs on empty dir: %v", err)
	}

	info, err := os.Stat(outPath)
	if err != nil {
		t.Fatalf("stat export: %v", err)
	}
	if info.Size() != 0 {
		t.Errorf("expected empty export file, got %d bytes", info.Size())
	}
}

func TestExportLogs_OutputFilePermissions(t *testing.T) {
	logDir := t.TempDir()
	outDir := t.TempDir()

	writeLogFile(t, logDir, "latest.log", "some log content\n")

	outPath := filepath.Join(outDir, "export.txt")
	if err := log.ExportLogs(logDir, outPath); err != nil {
		t.Fatalf("ExportLogs: %v", err)
	}

	info, err := os.Stat(outPath)
	if err != nil {
		t.Fatalf("stat output: %v", err)
	}
	if perm := info.Mode().Perm(); perm != 0600 {
		t.Errorf("expected 0600 permissions on export file, got %04o", perm)
	}
}

func TestExportLogs_WriterIntegration(t *testing.T) {
	// Write lines through LogWriter, then export and verify output.
	logDir := t.TempDir()
	outDir := t.TempDir()

	w, err := log.NewLogWriter(logDir, 1024*1024)
	if err != nil {
		t.Fatalf("NewLogWriter: %v", err)
	}

	lines := []log.LogLine{
		{Text: "first", IsStderr: false, Timestamp: time.Now()},
		{Text: "second", IsStderr: true, Timestamp: time.Now()},
	}
	for _, l := range lines {
		if err := w.Write(l); err != nil {
			t.Fatalf("Write: %v", err)
		}
	}
	if err := w.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	outPath := filepath.Join(outDir, "integration-export.txt")
	if err := log.ExportLogs(logDir, outPath); err != nil {
		t.Fatalf("ExportLogs: %v", err)
	}

	data, err := os.ReadFile(outPath)
	if err != nil {
		t.Fatalf("read export: %v", err)
	}

	combined := string(data)
	for _, l := range lines {
		if !strings.Contains(combined, l.Text) {
			t.Errorf("export missing line %q", l.Text)
		}
	}
	if !strings.Contains(combined, "[stdout]") {
		t.Error("export missing [stdout] stream indicator")
	}
	if !strings.Contains(combined, "[stderr]") {
		t.Error("export missing [stderr] stream indicator")
	}
}
