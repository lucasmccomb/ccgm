#!/usr/bin/env python3
"""Native-envelope fixture. Never contacts a model or executes supplied code."""
import json
import os
from pathlib import Path
import sys
import time

config = json.loads(Path(__file__).with_name('scenario.json').read_text())
if config.get('sleep'):
    time.sleep(config['sleep'])
if config.get('exit'):
    print(config.get('stderr', 'login required'), file=sys.stderr)
    sys.exit(config['exit'])
if config.get('raw'):
    print(config['raw'])
    sys.exit(0)
prompt = json.loads(sys.stdin.read().split('\n', 1)[1])
identity = prompt['identity']
provider = identity['provider']
payload = {'schema_version': 1, **identity, 'status': 'CLEAN', 'summary': 'No defect found.',
           'findings': [], 'verdicts': [], 'evidence_requests': [], 'verification': []}
if config.get('leak_check'):
    forbidden = ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL',
                 'CLAUDE_CODE_OAUTH_TOKEN', 'OPENAI_API_KEY', 'OPENAI_BASE_URL',
                 'CODEX_SESSION_ID', 'CODEX_THREAD_ID', 'CODEX_PERMISSION_PROFILE')
    if any(name in os.environ for name in forbidden):
        payload['summary'] = 'CREDENTIAL_ENV_LEAK'
if config.get('findings'):
    payload['status'] = 'FINDINGS'
    payload['findings'] = config['findings']
if config.get('mutate'):
    Path(config['mutate']).write_text('mutated during invocation')
context = json.loads(prompt.get('context') or '{}')
if context.get('purpose', '').endswith('ack') or config.get('critic_verdict'):
    for fid, row in context.get('findings', {}).items():
        evidence = (row.get('proposal') or row['finding'])['evidence']
        payload['verdicts'].append({'finding_id': fid, 'verdict': config.get('critic_verdict', 'AGREE'), 'evidence': evidence})
payload.update(config.get('payload', {}))
if provider == 'claude':
    events = [{'type': 'system', 'subtype': 'init', 'model': 'claude-fixture', 'tools': ['StructuredOutput']},
              {'type': 'result', 'subtype': 'success', 'is_error': False,
               'session_id': 'claude-fixture-session-' + str(os.getpid()), 'structured_output': payload,
               'usage': {'input_tokens': 10, 'output_tokens': 5}}]
    print(json.dumps(events[-1] if config.get('object') else events))
else:
    events = [{'type': 'thread.started', 'thread_id': 'codex-fixture-session-' + str(os.getpid())},
              {'type': 'turn.started'},
              {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(payload)}},
              {'type': 'turn.completed', 'usage': {'input_tokens': 10, 'output_tokens': 5}}]
    for event in events:
        print(json.dumps(event))
