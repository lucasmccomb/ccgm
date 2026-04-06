// Package log handles log collection, buffering, rotation, and export for
// agent processes. collector.go reads stdout/stderr streams from running
// agents, batches lines, and delivers them to the TUI via a send function.
package log

import (
	"bufio"
	"context"
	"io"
	"sync"
	"time"
)

// DefaultBatchInterval is the interval at which batched log lines are flushed
// to the send function. 16ms gives ~60fps update cadence for the TUI.
const DefaultBatchInterval = 16 * time.Millisecond

// LogLine is a single line of output captured from a running agent process.
type LogLine struct {
	Text      string
	IsStderr  bool
	Timestamp time.Time
}

// LogLineMsg is the message type delivered to the TUI (via sendFn) containing
// a batch of log lines from one agent. Using a generic func type keeps this
// package free of any bubbletea dependency.
type LogLineMsg struct {
	AgentID string
	Lines   []LogLine
}

// LogCollector reads stdout and stderr from an agent process, batches the
// lines at a configurable interval, and calls sendFn for each batch. It also
// writes every line to an optional LogWriter for file persistence.
//
// The collectors lifetime is tied to the readers: once both stdout and stderr
// reach EOF, the collector automatically performs a final flush and exits. The
// Stop method can be used to cancel the context early when the process is
// killed; the readers will then be unblocked by the process exiting and
// closing the pipes from the OS side.
type LogCollector struct {
	agentID       string
	sendFn        func(msg LogLineMsg)
	batchInterval time.Duration
	writer        *LogWriter // may be nil

	cancel  context.CancelFunc
	stopped chan struct{} // closed when the flush goroutine exits

	mu      sync.Mutex
	pending []LogLine
}

// NewLogCollector creates a LogCollector for agentID. sendFn is called with
// each batch of lines (never called with an empty slice). batchInterval
// controls how often pending lines are flushed; pass 0 to use
// DefaultBatchInterval. writer may be nil if file persistence is not needed.
func NewLogCollector(agentID string, sendFn func(LogLineMsg), batchInterval time.Duration, writer *LogWriter) *LogCollector {
	if batchInterval <= 0 {
		batchInterval = DefaultBatchInterval
	}
	return &LogCollector{
		agentID:       agentID,
		sendFn:        sendFn,
		batchInterval: batchInterval,
		writer:        writer,
		stopped:       make(chan struct{}),
	}
}

// Start begins reading from stdout and stderr in separate goroutines. Lines
// are collected into an internal buffer and flushed to sendFn at the
// configured batchInterval.
//
// The flush goroutine exits once both reader goroutines finish (EOF on both
// pipes) and performs a final flush. Stop cancels the context to signal
// readers that they should exit on the next line boundary, then waits for the
// flush goroutine to close.
//
// Start may only be called once per LogCollector.
func (c *LogCollector) Start(ctx context.Context, stdout, stderr io.Reader) {
	ctx, cancel := context.WithCancel(ctx)
	c.cancel = cancel

	// readersDone is closed once both reader goroutines have exited.
	readersDone := make(chan struct{})

	var wg sync.WaitGroup
	wg.Add(2)

	go func() {
		defer wg.Done()
		c.readLines(ctx, stdout, false)
	}()
	go func() {
		defer wg.Done()
		c.readLines(ctx, stderr, true)
	}()

	// Close readersDone when both goroutines are done.
	go func() {
		wg.Wait()
		close(readersDone)
	}()

	// Flush goroutine: drains the pending buffer on a timer, and does one
	// final flush once both readers have exited.
	go func() {
		defer close(c.stopped)

		ticker := time.NewTicker(c.batchInterval)
		defer ticker.Stop()

		for {
			select {
			case <-ticker.C:
				c.flush()
			case <-readersDone:
				// Both readers finished: final flush and exit.
				c.flush()
				return
			}
		}
	}()
}

// Stop cancels the collection context and blocks until the flush goroutine
// has performed its final flush and exited. It is safe to call Stop multiple
// times.
//
// Note: reader goroutines blocked inside bufio.Scanner.Scan() cannot be
// interrupted by context cancellation alone; they will unblock when the
// underlying pipe is closed (i.e. when the agent process exits). Stop signals
// that no new lines should be processed after the current one and waits for
// the natural shutdown path.
func (c *LogCollector) Stop() {
	if c.cancel != nil {
		c.cancel()
	}
	<-c.stopped
}

// readLines scans lines from r and appends them to the pending buffer.
// It exits when the reader returns EOF or an error, or after each scanned
// line if the context has been cancelled.
func (c *LogCollector) readLines(ctx context.Context, r io.Reader, isStderr bool) {
	scanner := bufio.NewScanner(r)
	for scanner.Scan() {
		line := LogLine{
			Text:      scanner.Text(),
			IsStderr:  isStderr,
			Timestamp: time.Now(),
		}

		// Write to file immediately (before batching for TUI).
		if c.writer != nil {
			// Best-effort: ignore write errors so a disk issue does not kill the TUI.
			_ = c.writer.Write(line)
		}

		c.mu.Lock()
		c.pending = append(c.pending, line)
		c.mu.Unlock()

		// Check context after each line so we stop promptly when cancelled.
		select {
		case <-ctx.Done():
			return
		default:
		}
	}
}

// flush takes ownership of pending lines and calls sendFn if there are any.
func (c *LogCollector) flush() {
	c.mu.Lock()
	if len(c.pending) == 0 {
		c.mu.Unlock()
		return
	}
	lines := c.pending
	c.pending = nil
	c.mu.Unlock()

	c.sendFn(LogLineMsg{
		AgentID: c.agentID,
		Lines:   lines,
	})
}
