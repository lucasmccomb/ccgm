// parser.go defines an interface for log line parsing. The initial
// implementation is a no-op stub; a v2 token-aware parser can satisfy the
// same interface without changing call sites.
package log

// LogParser parses a raw log line into a ParsedLine. Implementations may
// extract token counts, context usage, or other structured fields from the
// line text.
type LogParser interface {
	ParseLine(line string) *ParsedLine
}

// ParsedLine holds the result of parsing a single log line.
// Fields set to -1 indicate that the value could not be determined.
type ParsedLine struct {
	Raw          string
	TokenCount   int     // -1 if unknown
	ContextUsage float64 // -1 if unknown
}

// NoOpParser implements LogParser by returning a ParsedLine with the raw text
// and sentinel values for unknown fields. It is safe for concurrent use.
type NoOpParser struct{}

// ParseLine returns a ParsedLine with TokenCount and ContextUsage set to -1,
// indicating that no structured parsing was performed.
func (p *NoOpParser) ParseLine(line string) *ParsedLine {
	return &ParsedLine{
		Raw:          line,
		TokenCount:   -1,
		ContextUsage: -1,
	}
}
