#!/usr/bin/env bash
# Green dream-eval stub for the enabled-mode chain smoke (composite-eligibility
# plan.md §8.3 precondition 2 / E4 fixture triple part c).
#
# The optimistic-integrate step is eval-gated: it runs `dream-eval.sh --gate`
# and fails CLOSED unless that returns 0. The LIVE gate is structurally closed
# (#788) and would short-circuit optimistic-integrate BEFORE the composite ever
# runs, making the smoke vacuous. The smoke points CCGM_DREAMING_EVAL_SCRIPT at
# this stub so the gate is GREEN and the composite path actually executes. This
# stub is test scaffolding only -- it asserts nothing about eval quality.
echo "dream-eval green stub: gate open (test scaffolding only)"
exit 0
