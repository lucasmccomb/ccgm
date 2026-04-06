// process.go handles low-level OS process interaction: spawning, signaling,
// and waiting on Claude Code agent processes.
// Epic 2 will implement Process wrapping os/exec.Cmd with PID tracking.
package agent
