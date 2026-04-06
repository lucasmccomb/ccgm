// export.go exports agent log files to a single plain-text output file.
// It combines previous.log (if present) followed by latest.log so the
// resulting file is in chronological order.
package log

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
)

// ExportLogs reads latest.log and (if present) previous.log from logDir and
// writes their combined contents to outputPath. previous.log is written first
// so the output file is in chronological order.
//
// The output file is created with 0600 permissions. If outputPath already
// exists it is overwritten.
func ExportLogs(logDir string, outputPath string) error {
	out, err := os.OpenFile(outputPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0600)
	if err != nil {
		return fmt.Errorf("export logs: create output file %s: %w", outputPath, err)
	}
	defer out.Close()

	// Write previous.log first (older data), if it exists.
	prevPath := filepath.Join(logDir, previousLogName)
	if err := appendFile(out, prevPath); err != nil {
		return fmt.Errorf("export logs: append previous.log: %w", err)
	}

	// Write latest.log (newer data).
	latestPath := filepath.Join(logDir, latestLogName)
	if err := appendFile(out, latestPath); err != nil {
		return fmt.Errorf("export logs: append latest.log: %w", err)
	}

	return nil
}

// appendFile copies the contents of srcPath to dst. If srcPath does not
// exist, the function returns nil (the file is simply skipped).
func appendFile(dst io.Writer, srcPath string) error {
	f, err := os.Open(srcPath)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return fmt.Errorf("open %s: %w", srcPath, err)
	}
	defer f.Close()

	if _, err := io.Copy(dst, f); err != nil {
		return fmt.Errorf("copy %s: %w", srcPath, err)
	}
	return nil
}
