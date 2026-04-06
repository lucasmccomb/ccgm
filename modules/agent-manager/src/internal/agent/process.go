// process.go handles low-level OS process interaction: spawning, signaling,
// and waiting on Claude Code agent processes.
package agent

import (
	"fmt"
	"io"
	"os"
	"os/exec"
	"sync"
	"syscall"
	"time"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/types"
)

// Process wraps an os/exec.Cmd and provides safe concurrent access to its
// lifecycle state. Once started, the process runs in its own process group
// (Setpgid: true) so the manager can stop it without affecting peers.
type Process struct {
	cmd      *exec.Cmd
	pid      int
	stdout   io.ReadCloser
	stderr   io.ReadCloser
	done     chan struct{} // closed when process exits
	exitCode int
	mu       sync.Mutex
}

// SpawnProcess creates and starts an agent process from cfg.
//
// The command is executed directly (never via sh -c). stdout and stderr pipes
// are opened so callers can consume output. The process runs in its own
// process group to prevent signal propagation from the manager.
func SpawnProcess(cfg *types.AgentConfig) (*Process, error) {
	if err := cfg.Validate(); err != nil {
		return nil, fmt.Errorf("spawn process: invalid config: %w", err)
	}

	// Build the command. Never use sh -c.
	cmd := exec.Command(cfg.Command, cfg.Args...) //nolint:gosec
	cmd.Dir = cfg.WorkingDir

	// Merge parent env with agent-specific overrides.
	env := os.Environ()
	for k, v := range cfg.Env {
		env = append(env, k+"="+v)
	}
	cmd.Env = env

	// Isolate the child in its own process group so signals sent to the manager
	// do not propagate to agents.
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, fmt.Errorf("spawn process %q: open stdout pipe: %w", cfg.ID, err)
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		stdout.Close()
		return nil, fmt.Errorf("spawn process %q: open stderr pipe: %w", cfg.ID, err)
	}

	if err := cmd.Start(); err != nil {
		stdout.Close()
		stderr.Close()
		return nil, fmt.Errorf("spawn process %q: start: %w", cfg.ID, err)
	}

	p := &Process{
		cmd:    cmd,
		pid:    cmd.Process.Pid,
		stdout: stdout,
		stderr: stderr,
		done:   make(chan struct{}),
	}

	// Wait for the process in a goroutine so we can report the exit code and
	// close the done channel without blocking the caller.
	go func() {
		defer close(p.done)
		err := cmd.Wait()
		p.mu.Lock()
		defer p.mu.Unlock()
		if err != nil {
			if exitErr, ok := err.(*exec.ExitError); ok {
				p.exitCode = exitErr.ExitCode()
			} else {
				// Non-exit error (e.g. I/O problem). Use -1 as sentinel.
				p.exitCode = -1
			}
		} else {
			p.exitCode = 0
		}
	}()

	return p, nil
}

// Stop attempts a graceful shutdown by sending SIGTERM to the process group.
// If the process does not exit within gracePeriod, SIGKILL is sent.
func (p *Process) Stop(gracePeriod time.Duration) error {
	p.mu.Lock()
	proc := p.cmd.Process
	p.mu.Unlock()

	if proc == nil {
		return nil
	}

	// Send SIGTERM to the entire process group (negative PID).
	if err := syscall.Kill(-proc.Pid, syscall.SIGTERM); err != nil {
		// If the process is already gone, that is fine.
		if err == syscall.ESRCH {
			return nil
		}
		return fmt.Errorf("stop: SIGTERM to process group -%d: %w", proc.Pid, err)
	}

	// Wait for graceful exit.
	select {
	case <-p.done:
		return nil
	case <-time.After(gracePeriod):
	}

	// Grace period expired - force kill.
	if err := syscall.Kill(-proc.Pid, syscall.SIGKILL); err != nil {
		if err == syscall.ESRCH {
			return nil
		}
		return fmt.Errorf("stop: SIGKILL to process group -%d: %w", proc.Pid, err)
	}

	<-p.done
	return nil
}

// Kill immediately sends SIGKILL to the process group.
func (p *Process) Kill() error {
	p.mu.Lock()
	proc := p.cmd.Process
	p.mu.Unlock()

	if proc == nil {
		return nil
	}

	if err := syscall.Kill(-proc.Pid, syscall.SIGKILL); err != nil {
		if err == syscall.ESRCH {
			return nil
		}
		return fmt.Errorf("kill: SIGKILL to process group -%d: %w", proc.Pid, err)
	}

	<-p.done
	return nil
}

// IsAlive reports whether the process is still running by sending signal 0
// (which checks for process existence without delivering a signal).
func (p *Process) IsAlive() bool {
	p.mu.Lock()
	pid := p.pid
	p.mu.Unlock()

	if pid == 0 {
		return false
	}

	// Check the done channel first - if closed the goroutine already observed
	// the process exit.
	select {
	case <-p.done:
		return false
	default:
	}

	err := syscall.Kill(pid, 0)
	return err == nil
}

// Wait returns a channel that is closed when the process exits.
func (p *Process) Wait() <-chan struct{} {
	return p.done
}

// ExitCode returns the process exit code. The value is only meaningful after
// the done channel has been closed.
func (p *Process) ExitCode() int {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.exitCode
}

// Stdout returns the stdout pipe of the spawned process.
// The pipe is valid only while the process is running.
func (p *Process) Stdout() io.ReadCloser {
	return p.stdout
}

// Stderr returns the stderr pipe of the spawned process.
// The pipe is valid only while the process is running.
func (p *Process) Stderr() io.ReadCloser {
	return p.stderr
}

// PID returns the OS process ID.
func (p *Process) PID() int {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.pid
}
