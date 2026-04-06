package fileutil_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/fileutil"
)

func TestAtomicWriteJSON_RoundTrip(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "data.json")

	type payload struct {
		Name  string `json:"name"`
		Value int    `json:"value"`
	}

	want := payload{Name: "test", Value: 42}
	if err := fileutil.AtomicWriteJSON(path, want, 0600); err != nil {
		t.Fatalf("AtomicWriteJSON: %v", err)
	}

	var got payload
	if err := fileutil.ReadJSON(path, &got); err != nil {
		t.Fatalf("ReadJSON: %v", err)
	}
	if got != want {
		t.Errorf("round-trip mismatch: got %+v, want %+v", got, want)
	}
}

func TestAtomicWriteJSON_Permissions(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "secret.json")

	if err := fileutil.AtomicWriteJSON(path, map[string]string{"k": "v"}, 0600); err != nil {
		t.Fatalf("AtomicWriteJSON: %v", err)
	}

	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("stat: %v", err)
	}
	if info.Mode().Perm() != 0600 {
		t.Errorf("expected 0600 permissions, got %04o", info.Mode().Perm())
	}
}

func TestAtomicWriteJSON_NoTmpFileLeftOnSuccess(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "data.json")

	if err := fileutil.AtomicWriteJSON(path, "hello", 0600); err != nil {
		t.Fatalf("AtomicWriteJSON: %v", err)
	}

	tmpPath := path + ".tmp"
	if _, err := os.Stat(tmpPath); !os.IsNotExist(err) {
		t.Errorf("expected .tmp file to be cleaned up, but it exists")
	}
}

func TestEnsureDir_CreatesDirectory(t *testing.T) {
	base := t.TempDir()
	dir := filepath.Join(base, "a", "b", "c")

	if err := fileutil.EnsureDir(dir, 0700); err != nil {
		t.Fatalf("EnsureDir: %v", err)
	}
	info, err := os.Stat(dir)
	if err != nil {
		t.Fatalf("stat: %v", err)
	}
	if !info.IsDir() {
		t.Error("expected directory, got file")
	}
}

func TestEnsureDir_Idempotent(t *testing.T) {
	dir := t.TempDir()
	// Calling twice should not error.
	if err := fileutil.EnsureDir(dir, 0700); err != nil {
		t.Fatalf("first EnsureDir: %v", err)
	}
	if err := fileutil.EnsureDir(dir, 0700); err != nil {
		t.Fatalf("second EnsureDir: %v", err)
	}
}

func TestBasename(t *testing.T) {
	cases := []struct {
		path string
		want string
	}{
		{"/foo/bar/baz.json", "baz"},
		{"agent-1.json", "agent-1"},
		{"session.json", "session"},
		{"/path/to/file", "file"},
	}
	for _, c := range cases {
		got := fileutil.Basename(c.path)
		if got != c.want {
			t.Errorf("Basename(%q) = %q, want %q", c.path, got, c.want)
		}
	}
}
