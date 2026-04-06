package tui

import (
	"testing"
	"time"
)

func TestRingBuffer_BasicAddAndRetrieve(t *testing.T) {
	rb := NewRingBuffer(10)
	now := time.Now()
	lines := []LogDisplayLine{
		{Text: "line 1", Timestamp: now},
		{Text: "line 2", Timestamp: now},
		{Text: "line 3", Timestamp: now},
	}
	rb.Add(lines...)

	got := rb.Lines()
	if len(got) != 3 {
		t.Fatalf("expected 3 lines, got %d", len(got))
	}
	if got[0].Text != "line 1" {
		t.Errorf("expected first line to be %q, got %q", "line 1", got[0].Text)
	}
	if got[2].Text != "line 3" {
		t.Errorf("expected third line to be %q, got %q", "line 3", got[2].Text)
	}
}

func TestRingBuffer_Len(t *testing.T) {
	rb := NewRingBuffer(10)
	if rb.Len() != 0 {
		t.Fatalf("expected Len 0 on empty buffer, got %d", rb.Len())
	}
	now := time.Now()
	rb.Add(LogDisplayLine{Text: "a", Timestamp: now})
	rb.Add(LogDisplayLine{Text: "b", Timestamp: now})
	if rb.Len() != 2 {
		t.Fatalf("expected Len 2, got %d", rb.Len())
	}
}

func TestRingBuffer_OverflowDropsOldest(t *testing.T) {
	rb := NewRingBuffer(5)
	now := time.Now()
	for i := 0; i < 8; i++ {
		rb.Add(LogDisplayLine{Text: string(rune('a' + i)), Timestamp: now})
	}
	if rb.Len() != 5 {
		t.Fatalf("expected Len 5 after overflow, got %d", rb.Len())
	}
	got := rb.Lines()
	// Oldest 3 (a, b, c) should be gone; remaining should be d, e, f, g, h.
	expected := []string{"d", "e", "f", "g", "h"}
	for i, want := range expected {
		if got[i].Text != want {
			t.Errorf("index %d: expected %q, got %q", i, want, got[i].Text)
		}
	}
}

func TestRingBuffer_OverflowWithLargeBatch(t *testing.T) {
	rb := NewRingBuffer(5)
	now := time.Now()
	// Add 10 lines in a single batch; only the last 5 should remain.
	batch := make([]LogDisplayLine, 10)
	for i := range batch {
		batch[i] = LogDisplayLine{Text: string(rune('a' + i)), Timestamp: now}
	}
	rb.Add(batch...)
	if rb.Len() != 5 {
		t.Fatalf("expected Len 5, got %d", rb.Len())
	}
	got := rb.Lines()
	expected := []string{"f", "g", "h", "i", "j"}
	for i, want := range expected {
		if got[i].Text != want {
			t.Errorf("index %d: expected %q, got %q", i, want, got[i].Text)
		}
	}
}

func TestRingBuffer_Clear(t *testing.T) {
	rb := NewRingBuffer(10)
	now := time.Now()
	rb.Add(LogDisplayLine{Text: "x", Timestamp: now})
	rb.Add(LogDisplayLine{Text: "y", Timestamp: now})
	rb.Clear()
	if rb.Len() != 0 {
		t.Fatalf("expected Len 0 after Clear, got %d", rb.Len())
	}
	got := rb.Lines()
	if len(got) != 0 {
		t.Fatalf("expected empty slice after Clear, got %v", got)
	}
}

func TestRingBuffer_LinesReturnsCopy(t *testing.T) {
	rb := NewRingBuffer(10)
	now := time.Now()
	rb.Add(LogDisplayLine{Text: "original", Timestamp: now})

	got := rb.Lines()
	got[0].Text = "mutated"

	// Internal state should be unaffected.
	internal := rb.Lines()
	if internal[0].Text != "original" {
		t.Errorf("Lines() should return a copy; internal state was mutated: got %q", internal[0].Text)
	}
}

func TestRingBuffer_10001Lines(t *testing.T) {
	const max = 10_000
	rb := NewRingBuffer(max)
	now := time.Now()
	// Add max+1 lines one at a time to exercise the slow-path trimming.
	for i := 0; i <= max; i++ {
		rb.Add(LogDisplayLine{Text: "x", Timestamp: now})
	}
	if rb.Len() != max {
		t.Fatalf("expected %d lines after %d adds, got %d", max, max+1, rb.Len())
	}
}
