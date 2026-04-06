// Package log handles log collection, buffering, and export for agent processes.
// collector.go reads stdout/stderr streams from running agents into ring buffers.
// Epic 2 will implement the Collector type and per-agent log buffering.
package log
