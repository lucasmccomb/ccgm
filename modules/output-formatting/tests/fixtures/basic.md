# Release Report

The answer: the migration is safe to ship.

## Summary

Three services changed. Two need a restart.

## Results

| Service | Status | Notes |
|---------|--------|-------|
| api | ok | restart |
| worker | ok | restart |
| web | ok | none |

## Risks

Low.

## Rollback

Revert the merge commit.

## Follow-ups

None.
