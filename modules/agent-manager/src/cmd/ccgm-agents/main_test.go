// main_test.go contains basic smoke tests for the ccgm-agents entry point.
package main

import "testing"

func TestVersionDefault(t *testing.T) {
	if version == "" {
		t.Fatal("version variable must not be empty")
	}
	// In development builds the version defaults to "dev".
	// In release builds it is set via -ldflags at compile time.
}
