#!/usr/bin/env bash
# Plan §3.3 names this file `test-cross-clone-file-lock.sh`. The concrete
# 4-writer concurrent test ships at `test-cross-clone-lock-concurrent.sh`
# (a clearer name). This stub redirects so either name works.
exec bash "$(dirname "$0")/test-cross-clone-lock-concurrent.sh" "$@"
