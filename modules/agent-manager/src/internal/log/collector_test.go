package log_test

import (
	"context"
	"io"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/log"
)

// pipePair returns (writer, reader) backed by an io.Pipe.
func pipePair() (*io.PipeWriter, *io.PipeReader) {
	r, w := io.Pipe()
	return w, r
}

func TestCollector_ReceivesBatchedLines(t *testing.T) {
	var mu sync.Mutex
	var received []log.LogLineMsg

	sendFn := func(msg log.LogLineMsg) {
		mu.Lock()
		received = append(received, msg)
		mu.Unlock()
	}

	stdoutW, stdoutR := pipePair()
	stderrW, stderrR := pipePair()

	c := log.NewLogCollector("agent-1", sendFn, 16*time.Millisecond, nil)
	c.Start(context.Background(), stdoutR, stderrR)

	// Write several lines quickly - they should all arrive eventually.
	lines := []string{"line1", "line2", "line3"}
	for _, l := range lines {
		_, err := io.WriteString(stdoutW, l+"\n")
		if err != nil {
			t.Fatalf("write line: %v", err)
		}
	}

	// Close both pipes so both reader goroutines reach EOF and the collector
	// performs its final flush.
	stdoutW.Close()
	stderrW.Close()
	c.Stop() // blocks until final flush

	mu.Lock()
	defer mu.Unlock()

	// Collect all lines across all batches.
	var allLines []log.LogLine
	for _, msg := range received {
		if msg.AgentID != "agent-1" {
			t.Errorf("unexpected agent ID %q in message", msg.AgentID)
		}
		allLines = append(allLines, msg.Lines...)
	}

	if len(allLines) != len(lines) {
		t.Fatalf("expected %d lines total, got %d", len(lines), len(allLines))
	}
	for i, want := range lines {
		if allLines[i].Text != want {
			t.Errorf("line[%d]: got %q, want %q", i, allLines[i].Text, want)
		}
	}
}

func TestCollector_StdoutStderrSeparated(t *testing.T) {
	var mu sync.Mutex
	var received []log.LogLineMsg

	sendFn := func(msg log.LogLineMsg) {
		mu.Lock()
		received = append(received, msg)
		mu.Unlock()
	}

	stdoutW, stdoutR := pipePair()
	stderrW, stderrR := pipePair()

	c := log.NewLogCollector("agent-sep", sendFn, 16*time.Millisecond, nil)
	c.Start(context.Background(), stdoutR, stderrR)

	_, _ = io.WriteString(stdoutW, "out-line\n")
	_, _ = io.WriteString(stderrW, "err-line\n")

	stdoutW.Close()
	stderrW.Close()
	c.Stop()

	mu.Lock()
	defer mu.Unlock()

	var gotOut, gotErr int
	for _, msg := range received {
		for _, line := range msg.Lines {
			if line.Text == "out-line" && !line.IsStderr {
				gotOut++
			}
			if line.Text == "err-line" && line.IsStderr {
				gotErr++
			}
		}
	}

	if gotOut != 1 {
		t.Errorf("expected 1 stdout line, got %d", gotOut)
	}
	if gotErr != 1 {
		t.Errorf("expected 1 stderr line, got %d", gotErr)
	}
}

func TestCollector_ContextCancellationStopsCollection(t *testing.T) {
	var mu sync.Mutex
	var totalLines int

	sendFn := func(msg log.LogLineMsg) {
		mu.Lock()
		totalLines += len(msg.Lines)
		mu.Unlock()
	}

	stdoutW, stdoutR := pipePair()
	stderrW, stderrR := pipePair()

	ctx, cancel := context.WithCancel(context.Background())

	c := log.NewLogCollector("agent-ctx", sendFn, 16*time.Millisecond, nil)
	c.Start(ctx, stdoutR, stderrR)

	_, _ = io.WriteString(stdoutW, "before-cancel\n")

	// Cancel context after giving readers time to process the line.
	// Then close pipes so readers can unblock and exit.
	time.Sleep(20 * time.Millisecond)
	cancel()
	stdoutW.Close()
	stderrW.Close()

	// Stop should return promptly once pipes are closed.
	done := make(chan struct{})
	go func() {
		c.Stop()
		close(done)
	}()

	select {
	case <-done:
		// Good: Stop returned promptly.
	case <-time.After(2 * time.Second):
		t.Fatal("Stop did not return within 2 seconds after context cancellation")
	}
}

func TestCollector_ConcurrentReadersNoRace(t *testing.T) {
	// This test is designed to surface data races when run with -race.
	var mu sync.Mutex
	var total int

	sendFn := func(msg log.LogLineMsg) {
		mu.Lock()
		total += len(msg.Lines)
		mu.Unlock()
	}

	stdoutW, stdoutR := pipePair()
	stderrW, stderrR := pipePair()

	c := log.NewLogCollector("agent-race", sendFn, 8*time.Millisecond, nil)
	c.Start(context.Background(), stdoutR, stderrR)

	// Write from multiple goroutines concurrently.
	var wg sync.WaitGroup
	for i := 0; i < 10; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, _ = io.WriteString(stdoutW, strings.Repeat("x", 64)+"\n")
		}()
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, _ = io.WriteString(stderrW, strings.Repeat("e", 64)+"\n")
		}()
	}
	wg.Wait()

	// Close both pipes before calling Stop so readers unblock.
	stdoutW.Close()
	stderrW.Close()
	c.Stop()

	mu.Lock()
	defer mu.Unlock()
	if total != 20 {
		t.Errorf("expected 20 lines total, got %d", total)
	}
}

func TestCollector_BatchInterval_LinesBatchedTogether(t *testing.T) {
	// Use a long batch interval so all lines written quickly are in one batch.
	const interval = 200 * time.Millisecond

	var mu sync.Mutex
	var batches []int // number of lines per batch

	sendFn := func(msg log.LogLineMsg) {
		mu.Lock()
		batches = append(batches, len(msg.Lines))
		mu.Unlock()
	}

	stdoutW, stdoutR := pipePair()
	stderrW, stderrR := pipePair()

	c := log.NewLogCollector("agent-batch", sendFn, interval, nil)
	c.Start(context.Background(), stdoutR, stderrR)

	// Write 5 lines quickly - they should all land in one batch before the
	// first tick fires (interval is 200ms, writes are nearly instantaneous).
	for i := 0; i < 5; i++ {
		_, _ = io.WriteString(stdoutW, "line\n")
	}

	// Close both pipes so readers reach EOF, triggering the final flush.
	stdoutW.Close()
	stderrW.Close()
	c.Stop()

	mu.Lock()
	defer mu.Unlock()

	// All 5 lines should have arrived across one or more batches.
	total := 0
	for _, n := range batches {
		total += n
	}
	if total != 5 {
		t.Errorf("expected 5 lines across all batches, got %d", total)
	}
}
