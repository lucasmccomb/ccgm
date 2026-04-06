// ringbuffer.go implements a fixed-capacity ring buffer for LogDisplayLine entries.
// When the buffer is full, new lines overwrite the oldest entries.
package tui

import "time"

// LogDisplayLine is a single rendered log line with metadata.
type LogDisplayLine struct {
	Text      string
	IsStderr  bool
	Timestamp time.Time
}

// RingBuffer is a fixed-capacity circular buffer for LogDisplayLines.
// When capacity is exceeded, the oldest entries are dropped automatically.
type RingBuffer struct {
	items []LogDisplayLine
	max   int
}

// NewRingBuffer creates a RingBuffer with the given maximum capacity.
// Panics if max <= 0.
func NewRingBuffer(max int) *RingBuffer {
	if max <= 0 {
		panic("ringbuffer: max must be > 0")
	}
	return &RingBuffer{
		items: make([]LogDisplayLine, 0, min(max, 256)),
		max:   max,
	}
}

// Add appends one or more lines to the buffer. If adding the new lines causes
// the total to exceed the maximum, the oldest entries are dropped first.
func (r *RingBuffer) Add(lines ...LogDisplayLine) {
	if len(lines) == 0 {
		return
	}
	// If the incoming batch alone exceeds capacity, only keep the tail.
	if len(lines) >= r.max {
		lines = lines[len(lines)-r.max:]
		r.items = make([]LogDisplayLine, r.max)
		copy(r.items, lines)
		return
	}
	combined := len(r.items) + len(lines)
	if combined > r.max {
		// Drop oldest entries to make room.
		drop := combined - r.max
		r.items = r.items[drop:]
	}
	r.items = append(r.items, lines...)
}

// Lines returns a slice of all buffered lines in insertion order (oldest first).
// The returned slice is a copy; mutations do not affect the buffer.
func (r *RingBuffer) Lines() []LogDisplayLine {
	out := make([]LogDisplayLine, len(r.items))
	copy(out, r.items)
	return out
}

// Len returns the number of lines currently in the buffer.
func (r *RingBuffer) Len() int {
	return len(r.items)
}

// Clear removes all entries from the buffer.
func (r *RingBuffer) Clear() {
	r.items = r.items[:0]
}

