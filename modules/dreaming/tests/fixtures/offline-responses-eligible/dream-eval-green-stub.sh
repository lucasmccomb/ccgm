#!/usr/bin/env bash
# Green dream-eval stub for the enabled-mode chain smoke (composite-eligibility
# plan.md §8.3 precondition 2 / E4 fixture triple part c).
#
# The optimistic-integrate step is eval-gated: it runs `dream-eval.sh --gate`
# and integrates only when the gate is open. The smoke has no eval results, so
# the real gate would pause and optimistic-integrate would never reach the
# composite, making the smoke vacuous. The smoke points
# CCGM_DREAMING_EVAL_SCRIPT at this stub so the gate is open and the composite
# path actually executes. This stub is test scaffolding only -- it asserts
# nothing about eval quality.
echo '{"gate": "open", "code": "ok", "reason": "dream-eval green stub (test scaffolding only)", "since": null}'
exit 0
