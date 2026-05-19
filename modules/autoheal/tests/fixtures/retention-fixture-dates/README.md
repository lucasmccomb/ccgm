# retention-fixture-dates

Reference fixture documenting how `test-retention-sweep.sh` constructs date-bounded files.

The actual test creates fixture files in `mktemp -d` and uses `touch -t` to set
mtimes at three age boundaries:

- **15-day-old** file → `retention_gzip_days` is 30 → should remain untouched
- **45-day-old** file → between gzip (30) and delete (60) → should be gzipped
- **75-day-old** file → past delete (60) → should be deleted

This README exists because plan.md §3.3 lists `fixtures/retention-fixture-dates/`
as a fixture directory. The inline `touch -t` approach in the test is
preferred over checked-in dated files because: (a) committed mtimes don't
preserve across clones/checkouts, (b) age boundaries shift relative to "today"
and would need re-creation periodically. The test owns its data deterministically.

Example commands used by the test:

```bash
touch -t "$(date -v -15d +%Y%m%d0000)" "${EVENTS_DIR}/2026-05-03.jsonl"
touch -t "$(date -v -45d +%Y%m%d0000)" "${EVENTS_DIR}/2026-04-03.jsonl"
touch -t "$(date -v -75d +%Y%m%d0000)" "${EVENTS_DIR}/2026-03-04.jsonl"
```
