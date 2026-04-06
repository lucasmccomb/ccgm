package agent_test

import (
	"bufio"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/agent"
	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/types"
)

// mockAgentBin is the path to the compiled mock_agent binary. It is set in
// TestMain and reused by all process tests.
var mockAgentBin string

func TestMain(m *testing.M) {
	// Compile mock_agent once for the whole test run.
	bin, err := buildMockAgent()
	if err != nil {
		// Cannot compile helper - skip tests that need it gracefully.
		// This happens on platforms where exec is unavailable (e.g. WASM).
		os.Exit(m.Run())
	}
	mockAgentBin = bin
	code := m.Run()
	os.Remove(mockAgentBin)
	os.Exit(code)
}

// buildMockAgent compiles testdata/mock_agent.go into a temp binary and
// returns its path.
func buildMockAgent() (string, error) {
	// Locate the testdata directory relative to this file.
	_, thisFile, _, _ := runtime.Caller(0)
	srcDir := filepath.Join(filepath.Dir(thisFile), "testdata")
	src := filepath.Join(srcDir, "mock_agent.go")

	bin := filepath.Join(os.TempDir(), "mock_agent_test")
	if runtime.GOOS == "windows" {
		bin += ".exe"
	}

	cmd := exec.Command("go", "build", "-o", bin, src)
	cmd.Stdout = os.Stderr // pipe build output to test stderr
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		return "", err
	}
	return bin, nil
}

// testConfig builds a minimal valid AgentConfig that runs the mock agent.
func testConfig(t *testing.T, id string, args ...string) *types.AgentConfig {
	t.Helper()
	if mockAgentBin == "" {
		t.Skip("mock_agent binary not available")
	}
	return &types.AgentConfig{
		ID:         id,
		Name:       "Test " + id,
		Command:    mockAgentBin,
		Args:       args,
		WorkingDir: t.TempDir(),
		RestartPolicy: types.RestartPolicy{
			Type: "never",
		},
	}
}

func TestSpawnProcess_CapturesStdout(t *testing.T) {
	cfg := testConfig(t, "spawn-stdout", "--lines", "3")

	proc, err := agent.SpawnProcess(cfg)
	if err != nil {
		t.Fatalf("SpawnProcess: %v", err)
	}

	var lines []string
	scanner := bufio.NewScanner(proc.Stdout())
	for scanner.Scan() {
		lines = append(lines, scanner.Text())
	}

	<-proc.Wait()

	if len(lines) != 3 {
		t.Errorf("expected 3 stdout lines, got %d: %v", len(lines), lines)
	}
	for i, l := range lines {
		if !strings.HasPrefix(l, "line") {
			t.Errorf("line %d unexpected: %q", i, l)
		}
	}
	if proc.ExitCode() != 0 {
		t.Errorf("expected exit code 0, got %d", proc.ExitCode())
	}
}

func TestSpawnProcess_CapturesStderr(t *testing.T) {
	cfg := testConfig(t, "spawn-stderr", "--lines", "1")

	proc, err := agent.SpawnProcess(cfg)
	if err != nil {
		t.Fatalf("SpawnProcess: %v", err)
	}

	// Drain stdout so the process is not blocked on a full pipe buffer.
	go func() {
		b := make([]byte, 4096)
		for {
			if _, err := proc.Stdout().Read(b); err != nil {
				return
			}
		}
	}()

	var stderrLines []string
	scanner := bufio.NewScanner(proc.Stderr())
	for scanner.Scan() {
		stderrLines = append(stderrLines, scanner.Text())
	}

	<-proc.Wait()

	if len(stderrLines) == 0 {
		t.Error("expected at least one stderr line, got none")
	}
}

func TestSpawnProcess_NonZeroExitCode(t *testing.T) {
	cfg := testConfig(t, "spawn-exitcode", "--exit-code", "42", "--lines", "0")

	proc, err := agent.SpawnProcess(cfg)
	if err != nil {
		t.Fatalf("SpawnProcess: %v", err)
	}

	// Drain stdout/stderr so the process can exit cleanly.
	go func() { bufio.NewScanner(proc.Stdout()).Scan() }()
	go func() { bufio.NewScanner(proc.Stderr()).Scan() }()

	<-proc.Wait()

	if got := proc.ExitCode(); got != 42 {
		t.Errorf("expected exit code 42, got %d", got)
	}
}

func TestStop_GracefulSIGTERM(t *testing.T) {
	// Run mock_agent with a long delay so it is still alive when we stop it.
	cfg := testConfig(t, "stop-graceful", "--delay", "30s", "--lines", "1")

	proc, err := agent.SpawnProcess(cfg)
	if err != nil {
		t.Fatalf("SpawnProcess: %v", err)
	}

	// Drain pipes.
	go func() {
		b := make([]byte, 4096)
		for {
			if _, err := proc.Stdout().Read(b); err != nil {
				return
			}
		}
	}()
	go func() {
		b := make([]byte, 4096)
		for {
			if _, err := proc.Stderr().Read(b); err != nil {
				return
			}
		}
	}()

	if !proc.IsAlive() {
		t.Fatal("expected process to be alive before Stop")
	}

	start := time.Now()
	if err := proc.Stop(2 * time.Second); err != nil {
		t.Fatalf("Stop: %v", err)
	}
	elapsed := time.Since(start)

	// Should have stopped well within the grace period (SIGTERM is instant
	// for mock_agent which has no signal handler, so it exits immediately).
	if elapsed > 3*time.Second {
		t.Errorf("Stop took too long: %s", elapsed)
	}
	if proc.IsAlive() {
		t.Error("process still alive after Stop")
	}
}

func TestStop_TimeoutForcesKill(t *testing.T) {
	// Use a very short grace period so the test exercises the SIGKILL path.
	// mock_agent with a 5s delay will not exit on SIGTERM within 1ms.
	cfg := testConfig(t, "stop-kill", "--delay", "5s", "--lines", "0")

	proc, err := agent.SpawnProcess(cfg)
	if err != nil {
		t.Fatalf("SpawnProcess: %v", err)
	}

	go func() {
		b := make([]byte, 4096)
		for {
			if _, err := proc.Stdout().Read(b); err != nil {
				return
			}
		}
	}()
	go func() {
		b := make([]byte, 4096)
		for {
			if _, err := proc.Stderr().Read(b); err != nil {
				return
			}
		}
	}()

	// Note: on macOS, SIGTERM to a process in a new process group causes
	// immediate exit for processes that don't install a SIGTERM handler (Go
	// runtime forwards the signal). So even with a 1ms grace period the process
	// will be gone. The important thing is that Stop returns without hanging.
	start := time.Now()
	if err := proc.Stop(1 * time.Millisecond); err != nil {
		t.Fatalf("Stop: %v", err)
	}
	if time.Since(start) > 5*time.Second {
		t.Error("Stop hung for more than 5 seconds")
	}
	if proc.IsAlive() {
		t.Error("process still alive after Stop")
	}
}

func TestIsAlive_FalseAfterExit(t *testing.T) {
	cfg := testConfig(t, "alive-after-exit", "--lines", "0", "--delay", "0s")

	proc, err := agent.SpawnProcess(cfg)
	if err != nil {
		t.Fatalf("SpawnProcess: %v", err)
	}

	go func() {
		b := make([]byte, 4096)
		for {
			if _, err := proc.Stdout().Read(b); err != nil {
				return
			}
		}
	}()
	go func() {
		b := make([]byte, 4096)
		for {
			if _, err := proc.Stderr().Read(b); err != nil {
				return
			}
		}
	}()

	<-proc.Wait()

	// Give the goroutine a moment to update state.
	time.Sleep(10 * time.Millisecond)
	if proc.IsAlive() {
		t.Error("expected IsAlive to be false after process exit")
	}
}

func TestSpawnProcess_InvalidConfig(t *testing.T) {
	cfg := &types.AgentConfig{
		ID:      "", // invalid
		Command: "/bin/true",
		WorkingDir: t.TempDir(),
		RestartPolicy: types.RestartPolicy{Type: "never"},
	}
	if _, err := agent.SpawnProcess(cfg); err == nil {
		t.Error("expected error for invalid config, got nil")
	}
}

func TestProcess_ConcurrentAccess(t *testing.T) {
	cfg := testConfig(t, "concurrent", "--delay", "200ms", "--lines", "5")

	proc, err := agent.SpawnProcess(cfg)
	if err != nil {
		t.Fatalf("SpawnProcess: %v", err)
	}

	// Drain pipes.
	go func() {
		b := make([]byte, 4096)
		for {
			if _, err := proc.Stdout().Read(b); err != nil {
				return
			}
		}
	}()
	go func() {
		b := make([]byte, 4096)
		for {
			if _, err := proc.Stderr().Read(b); err != nil {
				return
			}
		}
	}()

	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_ = proc.IsAlive()
			_ = proc.PID()
			_ = proc.ExitCode()
		}()
	}
	wg.Wait()
	proc.Stop(2 * time.Second) //nolint:errcheck
}
