#!/usr/bin/env bash
# docupdate-discover.sh - Parallel repo discovery for /docupdate Phase 0
# Detects project type, finds all docs, and maps structure concurrently.

TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

# --- Parallel jobs ---

# 1. Project type detection
(
  echo "---MANIFESTS---"
  ls package.json Cargo.toml pyproject.toml go.mod Gemfile 2>/dev/null || echo "none"
  echo "---PACKAGE_JSON---"
  if [ -f package.json ]; then
    cat package.json | python3 -c "
import sys,json
d=json.load(sys.stdin)
out={'name':d.get('name',''),'description':d.get('description',''),'scripts':d.get('scripts',{}),'dependencies':list(d.get('dependencies',{}).keys()),'devDependencies':list(d.get('devDependencies',{}).keys())}
json.dump(out,sys.stdout,indent=2)" 2>/dev/null || echo "{}"
  else
    echo "{}"
  fi
) > "$TMPDIR/project" 2>/dev/null &

# 2. Documentation files
(
  find . -maxdepth 3 \( -name "README*" -o -name "CONTRIBUTING*" -o -name "CHANGELOG*" -o -name "INSTALL*" -o -name "SETUP*" -o -name "QUICKSTART*" \) -not -path "*/node_modules/*" -not -path "*/.git/*" 2>/dev/null
) > "$TMPDIR/doc_files" 2>/dev/null &

# 3. Docs directories
(
  find . -maxdepth 3 -type d \( -name "docs" -o -name "doc" -o -name "documentation" -o -name ".github" \) -not -path "*/node_modules/*" 2>/dev/null
) > "$TMPDIR/doc_dirs" 2>/dev/null &

# 4. Onboarding/setup docs
(
  find . -maxdepth 4 -name "*.md" -not -path "*/node_modules/*" -not -path "*/.git/*" -print0 2>/dev/null | \
    xargs -0 grep -l -i "getting started\|installation\|setup\|onboarding\|quick start" 2>/dev/null | head -10
) > "$TMPDIR/onboarding" 2>/dev/null &

# 5. Workspace/monorepo detection
(
  if [ -f package.json ]; then
    python3 -c "import json; d=json.load(open('package.json')); ws=d.get('workspaces',[]); print('\n'.join(ws) if isinstance(ws,list) else '\n'.join(ws.get('packages',[])))" 2>/dev/null
  fi
  echo "---DIRS---"
  ls -d packages/ apps/ libs/ modules/ src/ lib/ app/ 2>/dev/null || echo "none"
) > "$TMPDIR/structure" 2>/dev/null &

# 6. Available scripts
(
  if [ -f package.json ]; then
    python3 -c "import json; [print(f'{k}: {v}') for k,v in json.load(open('package.json')).get('scripts',{}).items()]" 2>/dev/null
  elif [ -f Makefile ]; then
    grep -E '^[a-zA-Z_-]+:' Makefile 2>/dev/null | sed 's/:.*//'
  fi
) > "$TMPDIR/scripts" 2>/dev/null &

wait

# --- Output ---
cat <<GATHER_EOF
=== PROJECT ===
$(cat "$TMPDIR/project")

=== DOC_FILES ===
$(cat "$TMPDIR/doc_files")

=== DOC_DIRS ===
$(cat "$TMPDIR/doc_dirs")

=== ONBOARDING ===
$(cat "$TMPDIR/onboarding")

=== STRUCTURE ===
$(cat "$TMPDIR/structure")

=== SCRIPTS ===
$(cat "$TMPDIR/scripts")
GATHER_EOF
