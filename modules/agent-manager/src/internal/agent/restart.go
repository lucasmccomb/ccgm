// restart.go implements automatic restart logic, run record persistence, and
// crash tombstone writing.
package agent

import (
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/fileutil"
	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/types"
)

// maxBackoffDelay caps the exponential backoff at 5 minutes.
const maxBackoffDelay = 5 * time.Minute

// historyDir returns the per-agent history directory within dataDir.
func historyDir(dataDir, agentID string) string {
	return filepath.Join(dataDir, "history", agentID)
}

// WriteRunRecord persists record to history/{agentID}/{timestamp}.json.
// The file is written atomically with 0600 permissions.
func WriteRunRecord(dataDir string, record *types.RunRecord) error {
	dir := historyDir(dataDir, record.AgentID)
	if err := os.MkdirAll(dir, 0700); err != nil {
		return fmt.Errorf("write run record: create history dir: %w", err)
	}

	// Use the stopped-at timestamp for the filename to give records a
	// human-readable, sortable name.
	filename := record.StoppedAt.UTC().Format("20060102T150405Z") + ".json"
	path := filepath.Join(dir, filename)

	if err := fileutil.AtomicWriteJSON(path, record, 0600); err != nil {
		return fmt.Errorf("write run record for %s: %w", record.AgentID, err)
	}
	return nil
}

// CrashTombstone records the state of a crashed agent for post-mortem inspection.
type CrashTombstone struct {
	AgentID      string    `json:"agent_id"`
	CrashedAt    time.Time `json:"crashed_at"`
	ExitCode     int       `json:"exit_code"`
	LastLogLines []string  `json:"last_log_lines"` // last 50 lines of output
	RestartCount int       `json:"restart_count"`
	WillRestart  bool      `json:"will_restart"`
}

// WriteCrashTombstone persists a CrashTombstone to
// history/{agentID}/crash-{timestamp}.json atomically.
func WriteCrashTombstone(dataDir string, tombstone *CrashTombstone) error {
	dir := historyDir(dataDir, tombstone.AgentID)
	if err := os.MkdirAll(dir, 0700); err != nil {
		return fmt.Errorf("write crash tombstone: create history dir: %w", err)
	}

	filename := "crash-" + tombstone.CrashedAt.UTC().Format("20060102T150405Z") + ".json"
	path := filepath.Join(dir, filename)

	if err := fileutil.AtomicWriteJSON(path, tombstone, 0600); err != nil {
		return fmt.Errorf("write crash tombstone for %s: %w", tombstone.AgentID, err)
	}
	return nil
}

// RestartEngine decides whether and when to restart a crashed agent based on
// its RestartPolicy. It is owned by the AgentManager and called by the health
// check when a crash is detected.
type RestartEngine struct {
	manager    *AgentManager
	retryCount map[string]int       // agentID -> current retry count
	nextRetry  map[string]time.Time // agentID -> next allowed retry time
	mu         sync.Mutex

	// bellWriter is the destination for terminal bell characters. Defaults to
	// os.Stdout; overridden in tests to capture output.
	bellWriter interface{ Write([]byte) (int, error) }
}

// NewRestartEngine constructs a RestartEngine owned by manager.
func NewRestartEngine(manager *AgentManager) *RestartEngine {
	return &RestartEngine{
		manager:    manager,
		retryCount: make(map[string]int),
		nextRetry:  make(map[string]time.Time),
		bellWriter: os.Stdout,
	}
}

// HandleCrash is called by the health check when a crash is detected for
// agentID. It emits a terminal bell, writes a crash tombstone, and schedules
// a restart if the agent's RestartPolicy permits it.
func (r *RestartEngine) HandleCrash(agentID string) error {
	// Emit terminal bell to alert the operator. Lock while accessing bellWriter
	// so tests that substitute a bytes.Buffer see consistent reads.
	r.mu.Lock()
	_, _ = r.bellWriter.Write([]byte("\a"))
	r.mu.Unlock()

	r.manager.mu.RLock()
	ma, ok := r.manager.agents[agentID]
	r.manager.mu.RUnlock()
	if !ok {
		return fmt.Errorf("restart engine: agent %q not found", agentID)
	}

	r.manager.mu.RLock()
	exitCode := ma.State.ExitCode
	restartCount := ma.State.RestartCount
	policy := ma.Config.RestartPolicy
	r.manager.mu.RUnlock()

	r.mu.Lock()
	currentRetries := r.retryCount[agentID]
	r.mu.Unlock()

	// Determine whether to restart.
	willRestart := r.shouldRestart(policy, exitCode, currentRetries)

	// Write crash tombstone (best-effort; do not block on I/O failure).
	tombstone := &CrashTombstone{
		AgentID:      agentID,
		CrashedAt:    nowFunc(),
		ExitCode:     exitCode,
		LastLogLines: r.collectLastLogLines(agentID),
		RestartCount: restartCount,
		WillRestart:  willRestart,
	}
	_ = WriteCrashTombstone(r.manager.dataDir, tombstone)

	if !willRestart {
		// Mark permanently dead if we exhausted retries.
		if policy.Type != "never" && policy.MaxRetries > 0 && currentRetries >= policy.MaxRetries {
			r.manager.emit(AgentEvent{
				AgentID: agentID,
				Type:    EventCrashed,
				Details: fmt.Sprintf("max retries (%d) exhausted", policy.MaxRetries),
			})
		}
		return nil
	}

	// Calculate backoff delay.
	baseDelay := policy.BaseDelay
	if baseDelay <= 0 {
		baseDelay = time.Second
	}
	delay := r.CalculateBackoff(currentRetries, baseDelay)

	r.mu.Lock()
	r.retryCount[agentID] = currentRetries + 1
	r.nextRetry[agentID] = nowFunc().Add(delay)
	r.mu.Unlock()

	// Schedule the restart asynchronously so the health check loop is not blocked.
	go func() {
		time.Sleep(delay)
		r.doRestart(agentID)
	}()

	return nil
}

// shouldRestart returns true if the agent's policy permits a restart given the
// current exit code and retry count.
func (r *RestartEngine) shouldRestart(policy types.RestartPolicy, exitCode, currentRetries int) bool {
	switch policy.Type {
	case "never":
		return false
	case "on-crash":
		if exitCode == 0 {
			// Clean exit is not a crash.
			return false
		}
		if policy.MaxRetries > 0 && currentRetries >= policy.MaxRetries {
			return false
		}
		return true
	case "always":
		if policy.MaxRetries > 0 && currentRetries >= policy.MaxRetries {
			return false
		}
		return true
	default:
		return false
	}
}

// doRestart re-spawns the agent. Called from the goroutine launched in HandleCrash.
func (r *RestartEngine) doRestart(agentID string) {
	r.manager.mu.RLock()
	ma, ok := r.manager.agents[agentID]
	r.manager.mu.RUnlock()
	if !ok {
		return
	}

	cfg := ma.Config

	// Update status to restarting while we spawn.
	r.manager.mu.Lock()
	ma.State.Status = types.StatusRestarting
	r.manager.mu.Unlock()

	proc, err := SpawnProcess(&cfg)
	if err != nil {
		r.manager.emit(AgentEvent{
			AgentID: agentID,
			Type:    EventCrashed,
			Details: fmt.Sprintf("restart failed: %v", err),
		})
		r.manager.mu.Lock()
		ma.State.Status = types.StatusCrashed
		r.manager.mu.Unlock()
		return
	}

	r.manager.mu.Lock()
	ma.Process = proc
	ma.State.PID = proc.PID()
	ma.State.Status = types.StatusRunning
	ma.State.StartedAt = nowFunc()
	ma.State.RestartCount++
	r.manager.mu.Unlock()

	r.manager.emit(AgentEvent{
		AgentID: agentID,
		Type:    EventRestarted,
		Details: fmt.Sprintf("PID %d", proc.PID()),
	})
}

// CalculateBackoff computes the exponential backoff delay for the given retry
// count: baseDelay * 2^retryCount, capped at maxBackoffDelay (5 minutes).
func (r *RestartEngine) CalculateBackoff(retryCount int, baseDelay time.Duration) time.Duration {
	if retryCount <= 0 {
		return baseDelay
	}
	// Use bit-shift for power-of-two multiplication; cap at 62 to avoid overflow.
	shift := retryCount
	if shift > 62 {
		shift = 62
	}
	delay := baseDelay * (1 << shift)
	if delay > maxBackoffDelay || delay < 0 { // negative = overflow
		return maxBackoffDelay
	}
	return delay
}

// ResetRetryCount clears the retry counter for agentID. Call this on a
// successful manual stop so subsequent crashes start from zero retries.
func (r *RestartEngine) ResetRetryCount(agentID string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	delete(r.retryCount, agentID)
	delete(r.nextRetry, agentID)
}

// SetBellWriter overrides the writer used for terminal bell output. The default
// is os.Stdout. Use this in tests to capture bell output.
func (r *RestartEngine) SetBellWriter(w interface{ Write([]byte) (int, error) }) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.bellWriter = w
}

// RetryCount returns the current retry count for agentID (used in tests).
func (r *RestartEngine) RetryCount(agentID string) int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.retryCount[agentID]
}

// collectLastLogLines returns up to 50 lines from the agent's recent output.
// When no log collector is wired up this returns an empty slice.
func (r *RestartEngine) collectLastLogLines(agentID string) []string {
	r.manager.mu.RLock()
	ma, ok := r.manager.agents[agentID]
	r.manager.mu.RUnlock()
	if !ok {
		return nil
	}
	// The log collector (wired up in the TUI epic) will provide lines via
	// ma.recentLines. For now, return whatever lines are available.
	_ = ma
	return nil
}
