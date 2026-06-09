// Config-isolation fixture: this file is intentionally malformed/erroring.
// If eslint loads this config (i.e., --no-config-lookup was NOT used),
// it will throw an error, causing the wrapper to emit a skip note.
// The test asserts that the wrapper either:
//   (a) emits a skip note (correct: config isolation prevented execution), or
//   (b) produces findings without loading this config (also correct).
// It must NOT crash with exit code 2 due to this config being loaded.
throw new Error("CCGM config-isolation test: this config should never be loaded");
