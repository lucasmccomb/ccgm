// restart.go implements automatic restart logic and run record persistence.
package agent

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/fileutil"
	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/types"
)

// historyDir returns the per-agent history directory within dataDir.
func historyDir(dataDir, agentID string) string {
	return filepath.Join(dataDir, "history", agentID)
}

// WriteRunRecord persists record to history/{agentID}/{timestamp}.json.
// The file is written atomically with 0600 permissions.
func WriteRunRecord(dataDir string, record *types.RunRecord) error {
	dir := historyDir(dataDir, record.AgentID)
	if err := os.MkdirAll(dir, 0700); err != nil {
		return fmt.Errorf("write run record: create history dir: %w", err)
	}

	// Use the stopped-at timestamp for the filename to give records a
	// human-readable, sortable name.
	filename := record.StoppedAt.UTC().Format("20060102T150405Z") + ".json"
	path := filepath.Join(dir, filename)

	if err := fileutil.AtomicWriteJSON(path, record, 0600); err != nil {
		return fmt.Errorf("write run record for %s: %w", record.AgentID, err)
	}
	return nil
}
