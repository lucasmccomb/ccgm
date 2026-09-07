#!/usr/bin/env python3
"""Deterministic pilot workflow gates above the restricted native review runtime."""
import argparse
import copy
import json
from pathlib import Path
import secrets
import sys
import time

# Selection must not create import caches before the user submits a choice.
sys.dont_write_bytecode = True

# The skill remains independently copyable into Codex.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cross_agent_review as rt

POLICY_VERSION = 1
MAX_EXCHANGES = 3
MAX_FIX_ROUNDS = 2
LENSES = {
    'plan': 'Review premises, falsifiability, the strongest opposing case, second-order effects, execution and failure modes, reversal costs, whole-plan coherence, minimal/edge-bucketed human work, follow-up completion, autonomous decision context, and comprehensive autonomous end-to-end tests. Every pass covers all lenses; additional passes reconsider the revised artifact.',
    'spec': 'Review specification compliance: actual goal, all acceptance criteria, required behavior, omissions, unintended scope, and concrete source/test evidence.',
    'quality': 'Review code quality after specification compliance: correctness, regressions, maintainability, resource handling, security boundaries, and meaningful tests.',
    'adrev': 'Adversarially review the entire stated target against the actual goal, premises, failure modes, reversibility, and evidence. Respect report-only authority.',
}


def selection(count=None, source='explicit', unattended=False, resume_dir=None):
    if resume_dir:
        rt.require(count is None and not unattended, 'Resume restores its saved review choice.')
        request, _, _ = rt.load(resume_dir)
        count, source = request.get('adversarial_review_count'), request.get('review_count_source')
        if count is None or source not in ('explicit', 'interactive', 'unattended-default'):
            return {'status': 'NEEDS_SELECTION', 'options': [1, 2, 3], 'recommended': 1}
    if count is None:
        if not unattended:
            return {'status': 'NEEDS_SELECTION', 'options': [1, 2, 3], 'recommended': 1,
                    'question': 'How many adversarial reviews should this plan receive?'}
        count, source = 1, 'unattended-default'
    rt.require(type(count) is int or (isinstance(count, str) and count in ('1', '2', '3')),
               'Review count must be an integer from 1 through 3.')
    count = int(count)
    rt.require(count in (1, 2, 3), 'Review count must be from 1 through 3.')
    rt.require(source in ('explicit', 'interactive', 'unattended-default'), 'Unknown selection source.')
    return {'status': 'SELECTED', 'adversarial_review_count': count, 'review_count_source': source}


def stamp(bundle):
    return {key: bundle[key] for key in ('artifact_sha256', 'evidence_sha256')}


def payload(run_dir, relative):
    path = Path(relative)
    rt.require(not path.is_absolute() and '..' not in path.parts and path.suffix == '.json',
               'Payload must be a relative JSON file inside the private run directory.')
    current = Path(run_dir)
    for part in path.parts:
        current = current / part
        rt.require(not current.is_symlink(), 'Payload symlinks are not accepted.')
    with current.open('rb') as stream:
        content = stream.read(rt.MAX_CONTEXT_BYTES + 1)
    rt.require(len(content) <= rt.MAX_CONTEXT_BYTES, 'Payload exceeds 64 KB.')
    result = json.loads(content)
    rt.require(isinstance(result, dict), 'Expected an object payload.')
    return result


def keys(value, required):
    rt.require(set(value) == set(required), 'Incorrect payload fields: expected ' + ', '.join(required))


def fresh(request, state, bundle, *, allow_completed=False):
    rt.require(not state['policy'].get('stopped'), 'Optional review was stopped.', 'STOPPED')
    rt.require(allow_completed or state['policy']['status'] not in ('CONSENSUS', 'REPORT_DELIVERED'),
               'Completed workflows are read-only history.')
    rt.require(rt.snapshot(request) == bundle, 'Artifact/evidence changed: refresh is required.', 'STALE_ARTIFACT')
    rt.require(state['quota'] != 'exhausted', 'Known provider quota exhaustion.', 'UNRESOLVED_BUDGET')
    rt.require(time.time() < state['deadline'], 'Original deadline expired.', 'UNRESOLVED_BUDGET')


def persist(run_dir, state):
    with rt.run_lock(run_dir):
        rt.save(Path(run_dir) / 'state.json', state)


def make_stages(request, mode, light_review):
    if mode == 'plan':
        return [{'key': 'plan-' + str(number), 'lens': 'plan', 'pass_number': number,
                 'perspective': None, 'is_final': number == request['adversarial_review_count']}
                for number in range(1, request['adversarial_review_count'] + 1)]
    lenses = ['spec'] if mode == 'etp' and light_review else ['spec', 'quality'] if mode == 'etp' else ['adrev']
    perspectives = list(rt.PROVIDERS) if request['producer_provider'] in ('mixed', 'unknown') else [None]
    return [{'key': lens + ('-' + provider if provider else ''), 'lens': lens, 'pass_number': 1,
             'perspective': provider, 'is_final': lens == lenses[-1] and provider == perspectives[-1]}
            for lens in lenses for provider in perspectives]


def lead_review():
    return {'status': 'LEAD_REVIEW', 'review_mode': 'lead', 'execution_ready': False,
            'next_action': 'Personally review the work and run repository tests and release checks.'}


def preflight():
    """Read-only native login checks; never expose auth output or launch a model."""
    providers = {}
    for provider in rt.PROVIDERS:
        binary = rt.shutil.which(provider)
        entry = {'binary_found': binary is not None, 'authenticated': False}
        if binary:
            argv = [binary, 'auth', 'status', '--json'] if provider == 'claude' else [binary, 'login', 'status']
            try:
                result = rt.subprocess.run(argv, capture_output=True, text=True, timeout=10, env=rt.native_environment())
                auth = json.loads(result.stdout) if provider == 'claude' and result.returncode == 0 else {}
                entry['authenticated'] = result.returncode == 0 and (
                    provider == 'codex' or isinstance(auth, dict) and auth.get('loggedIn') is True)
            except (OSError, ValueError, rt.subprocess.TimeoutExpired):
                pass
        providers[provider] = entry
    return {'status': 'AVAILABLE' if all(p['authenticated'] for p in providers.values()) else 'NEEDS_PROVIDER',
            'providers': providers, 'generation_tested': False}


def initialize(request, run_dir, mode, checks, writer_session_id, light_review=False, report_only=False,
               *, cross_provider=False):
    if not cross_provider:
        return lead_review()
    request = rt.validate_request(request)
    selection(request['adversarial_review_count'], request['review_count_source'])
    rt.require(mode in ('plan', 'etp', 'adrev'), 'Unknown pilot mode.')
    rt.require(request['workflow'] == ('plan' if mode == 'plan' else 'work'), 'Request workflow contradicts pilot mode.')
    rt.require(not light_review or mode == 'etp', '--light-review applies only to ETP.')
    rt.require(not report_only or mode == 'adrev', '--report-only applies only to standalone adrev.')
    keys(checks, ['required'])
    required = checks['required']
    rt.require(isinstance(required, list) and all(isinstance(name, str) and name.strip() for name in required)
               and len(required) == len(set(required)), 'Required checks must be unique names.')
    rt.require(required or report_only, 'Execution-ready workflows need explicit required checks.')
    rt.require(isinstance(writer_session_id, str) and writer_session_id.strip(), 'Designated writer session is required.')
    stages = make_stages(request, mode, light_review)
    state = rt.create_run(request, run_dir)
    state['policy'] = {'version': POLICY_VERSION, 'mode': mode, 'status': 'ACTIVE',
                       'report_only': report_only, 'light_review': light_review,
                       'writer_provider': request['producer_provider'] if request['producer_provider'] in rt.PROVIDERS else request['origin_provider'],
                       'writer_session_id': writer_session_id, 'stages': stages, 'index': 0,
                       'findings': {}, 'checks': {}, 'required_checks': required,
                       'fix_rounds': 0, 'fix_allowance': MAX_FIX_ROUNDS, 'extensions': [], 'pending_fix': None,
                       'acks': {}, 'receipt': None, 'history': [], 'sessions': []}
    persist(run_dir, state)
    return status(run_dir)


def status(run_dir):
    request, state, bundle = rt.load(run_dir)
    policy = state.get('policy')
    rt.require(policy and policy['version'] == POLICY_VERSION, 'This run has no supported pilot policy.')
    current = policy['stages'][policy['index']] if policy['index'] < len(policy['stages']) else None
    try:
        stale = rt.snapshot(request) != bundle
    except (rt.ReviewError, OSError, ValueError):
        stale = True
    effective_status = 'STALE_ARTIFACT' if stale else policy['status']
    if policy.get('stopped'):
        effective_status = 'STOPPED'
    elif not stale and policy['status'] not in ('CONSENSUS', 'REPORT_DELIVERED'):
        if state['quota'] == 'exhausted' or time.time() >= state['deadline']:
            effective_status = 'UNRESOLVED_BUDGET'
    return {'status': effective_status, 'transport_status': state['status'], **stamp(bundle),
            'origin_provider': request['origin_provider'], 'origin_session_id': request['origin_session_id'],
            'adversarial_review_count': request['adversarial_review_count'],
            'review_count_source': request['review_count_source'],
            'current_stage': current, 'completed_stages': policy['index'],
            'total_stages': len(policy['stages']), 'invocations': state['invocations'],
            'deadline': state['deadline'], 'fix_rounds': policy['fix_rounds'],
            'findings': policy['findings'], 'handoff': policy.get('handoff'),
            'execution_ready': effective_status == 'CONSENSUS' and not policy['report_only']}


def current_stage(policy):
    rt.require(policy['index'] < len(policy['stages']), 'All selected stages have been advanced.')
    return policy['stages'][policy['index']]


def report_for(run_dir, state, ref):
    calls = [call for call in state['calls'] if call.get('report') == ref]
    rt.require(len(calls) == 1 and calls[0]['status'] == 'REVIEWED', 'No successful native invocation for report.')
    report = rt.read_json(Path(run_dir) / ref)
    rt.require(rt.digest(report) == calls[0]['report_sha256'], 'Native report was changed.')
    return report


def evidence_valid(evidence, bundle):
    rt.require(isinstance(evidence, list) and evidence, 'Concrete evidence is required.')
    for item in evidence:
        keys(item, ['path', 'quote'])
        entry = bundle['files'].get(item['path'])
        rt.require(entry and isinstance(item['quote'], str) and item['quote'].strip()
                   and item['quote'] in entry['content'], 'Evidence must quote the current frozen bundle.')


def native_context(request, policy, purpose, stage, extra=None):
    context = {'purpose': purpose, 'stage': stage['key'], 'criteria': LENSES[stage['lens']],
               'final_selected_pass': stage['is_final'], 'selected_pass_count': request['adversarial_review_count']}
    if purpose != 'review':
        context.update({'findings': policy['findings'], 'checks': policy['checks'],
                        'required_checks': policy['required_checks']})
    if purpose.endswith('ack'):
        # Derived closure/ack fields must not change the question halfway through
        # a pair, or between final-stage acceptance and final handback.
        context['findings'] = {
            fid: {**{key: row[key] for key in ('finding', 'proposal', 'observations', 'verdicts')},
                  'state': 'PROPOSED' if row['proposal'] else 'OPEN'}
            for fid, row in policy['findings'].items()}
    if extra:
        context.update(extra)
    return context


def native(run_dir, purpose, role, stage, extra=None):
    request, state, bundle = rt.load(run_dir)
    policy = state['policy']
    fresh(request, state, bundle)
    rt.require(not policy['pending_fix'], 'The designated writer must return the admitted fix first.')
    context = native_context(request, policy, purpose, stage, extra)
    text = json.dumps(context, ensure_ascii=False)
    rt.require(len(text.encode()) <= rt.MAX_CONTEXT_BYTES, 'Resolution context exceeds bounded transport capacity.')
    rt.save(Path(run_dir) / ('policy-context-' + str(state['invocations'] + 1) + '.json'), context)
    try:
        report = rt.invoke(run_dir, role, stage['pass_number'], perspective=stage['perspective'], context_data=text,
                           workflow_purpose=purpose)
    except rt.ReviewError as error:
        _, state, _ = rt.load(run_dir)
        state['policy']['status'] = error.status
        persist(run_dir, state)
        raise
    request, state, bundle = rt.load(run_dir)
    policy = state['policy']
    session = report['identity']['provider'] + ':' + report['identity']['session_id']
    rt.require(session not in policy['sessions'], 'Reviewer session was reused.', 'INVALID_RESULT')
    policy['sessions'].append(session)
    ref = state['calls'][-1]['report']
    policy['history'].append({'purpose': purpose, 'stage': stage['key'], 'report': ref, **stamp(bundle)})
    policy['receipt'] = None
    persist(run_dir, state)
    return report, ref


def ingest(policy, report, ref, bundle, stage_key, judgment_target='original_finding'):
    provider = report['identity']['provider']
    known_ids = set(policy['findings'])
    for finding in report['result']['findings']:
        fid = finding['id']
        if fid not in known_ids:
            # Only exact ledger IDs identify previous observations. Local IDs
            # are fresh discoveries, including after a fix or during an ack.
            fid = stage_key + ':' + provider + ':' + fid
            if fid in policy['findings']:
                base = fid + ':' + ref
                fid, suffix = base, 2
                while fid in policy['findings']:
                    fid, suffix = base + ':' + str(suffix), suffix + 1
        finding = {**finding, 'id': fid}
        row = policy['findings'].get(fid)
        if row:
            rt.require(row['finding']['requirement'] == finding['requirement'], 'Finding ID collision across requirements.', 'INVALID_RESULT')
            row['observations'].append({'provider': provider, 'report': ref, **stamp(bundle)})
            row['state'], row['proposal'] = 'OPEN', None
        else:
            policy['findings'][fid] = {'finding': finding, 'state': 'OPEN', 'proposal': None,
                                       'observations': [{'provider': provider, 'report': ref, **stamp(bundle)}],
                                       'verdicts': {}}
    for verdict in report['result']['verdicts']:
        rt.require(verdict['finding_id'] in policy['findings'], 'Critic referenced an unknown finding.', 'INVALID_RESULT')
        policy['findings'][verdict['finding_id']]['verdicts'][provider] = {'verdict': verdict, 'report': ref,
                                                                        'judgment_target': judgment_target, **stamp(bundle)}


def do_review(run_dir, action):
    request, state, bundle = rt.load(run_dir)
    fresh(request, state, bundle)
    policy = state['policy']
    stage = current_stage(policy)
    if action == 'review':
        rt.require(not stage.get('report'), 'This stage already has a report; use critic/rebuttal or advance.')
        role = 'validation' if stage.get('previous_report') else 'reviewer'
    else:
        rt.require(stage.get('report'), 'Review the frozen artifact before a dispute.')
        rt.require(stage.get('exchanges', 0) < MAX_EXCHANGES, 'Dispute exchange limit reached.', 'UNRESOLVED_DISPUTE')
        rt.require(stage.get('no_progress', 0) < 2, 'Two unchanged exchanges: supply a discriminating check.', 'UNRESOLVED_DISPUTE')
        role = 'critic' if action == 'critic' else 'reviewer'
    purpose = 'revalidation' if action == 'review' and stage.get('previous_report') else action
    if action != 'review':
        fresh(request, state, bundle)
        stage['exchanges'] = stage.get('exchanges', 0) + 1
        persist(run_dir, state)  # Failed provider attempts spend the exchange too.
    report, ref = native(run_dir, purpose, role, stage)
    request, state, bundle = rt.load(run_dir)
    policy, stage = state['policy'], current_stage(state['policy'])
    ingest(policy, report, ref, bundle, stage['key'])
    if action == 'review':
        stage.update({'report': ref, **stamp(bundle), 'exchanges': 0, 'no_progress': 0})
    else:
        signal = rt.digest({'findings': report['result']['findings'], 'verdicts': report['result']['verdicts'],
                            'requests': report['result']['evidence_requests']})
        stage['no_progress'] = stage.get('no_progress', 0) + 1 if signal == stage.get('last_signal') else 0
        stage['last_signal'] = signal
    stage['needs_evidence'] = report['result']['status'] == 'NEEDS_EVIDENCE'
    policy['status'] = 'ACTIVE'
    persist(run_dir, state)
    return {'report': ref, 'result': report['result'], 'workflow': status(run_dir)}


def propose(run_dir, value):
    request, state, bundle = rt.load(run_dir)
    fresh(request, state, bundle)
    keys(value, ['dispositions'])
    policy = state['policy']
    rt.require(not policy['report_only'], 'Report-only review preserves findings without applying dispositions.')
    rt.require(isinstance(value['dispositions'], list), 'Expected dispositions array.')
    for item in value['dispositions']:
        keys(item, ['finding_id', 'disposition', 'rationale', 'evidence'])
        row = policy['findings'].get(item['finding_id'])
        rt.require(row is not None and item['disposition'] in ('fixed', 'refuted', 'duplicate', 'outside_scope'), 'Unknown finding/disposition.')
        rt.require(isinstance(item['rationale'], str) and item['rationale'].strip(), 'Disposition rationale required.')
        evidence_valid(item['evidence'], bundle)
        if item['disposition'] == 'fixed':
            rt.require(any(observation['artifact_sha256'] != bundle['artifact_sha256'] for observation in row['observations']),
                       'A fixed disposition requires a changed artifact.')
        row['proposal'] = {**item, **stamp(bundle)}
        row['state'] = 'PROPOSED'
    policy['acks'], policy['receipt'] = {}, None
    persist(run_dir, state)
    return status(run_dir)


def record_check(run_dir, value):
    keys(value, ['name', 'argv', 'exit_code', 'output', 'started_at', 'finished_at', 'artifact_sha256', 'evidence_sha256'])
    request, state, bundle = rt.load(run_dir)
    fresh(request, state, bundle)
    policy = state['policy']
    rt.require(isinstance(value['name'], str) and value['name'].strip(), 'Check name required.')
    rt.require(isinstance(value['argv'], list) and value['argv'] and all(isinstance(arg, str) for arg in value['argv']), 'Actual check argv required.')
    rt.require(type(value['exit_code']) is int and isinstance(value['output'], str) and value['output'].strip(), 'Actual exit status/output required.')
    rt.require(all(type(value[key]) in (int, float) for key in ('started_at', 'finished_at')), 'Check timestamps required.')
    rt.require(state['created_at'] <= value['started_at'] <= value['finished_at'] <= time.time(), 'Check must have executed in this run.')
    rt.require(all(value[key] == expected for key, expected in stamp(bundle).items()), 'Check targets stale evidence.')
    previous = policy['checks'].get(value['name'])
    policy['checks'][value['name']] = value
    policy['acks'], policy['receipt'] = {}, None
    substantive = lambda check: {key: check[key] for key in ('argv', 'exit_code', 'output')}
    if (previous is None or substantive(previous) != substantive(value)) and policy['index'] < len(policy['stages']):
        current_stage(policy)['no_progress'] = 0
    persist(run_dir, state)
    return status(run_dir)


def checks_pass(policy, bundle):
    for name in policy['required_checks']:
        check = policy['checks'].get(name)
        rt.require(check and check['exit_code'] == 0 and all(check[key] == value for key, value in stamp(bundle).items()),
                   'Required current-artifact check missing or failed: ' + name, 'NEEDS_CHECKS')


def acknowledgment_basis(policy, bundle):
    return rt.digest({'snapshot': stamp(bundle), 'reports': [s.get('report') for s in policy['stages']],
                      'checks': policy['checks'], 'required_checks': policy['required_checks'],
                      'findings': {fid: {'finding': row['finding'], 'proposal': row['proposal']}
                                   for fid, row in policy['findings'].items()}})


def ack_inputs(run_dir, request, policy, bundle, stage):
    purpose = 'final-ack' if stage['is_final'] else 'stage-ack'
    extra = {'all_selected_reports': [entry.get('report') for entry in policy['stages']],
             'scope_constraints': request['goal']}
    context = native_context(request, policy, purpose, stage, extra)
    references = {entry['report'] for entry in policy['stages'] if entry.get('report')}
    for row in policy['findings'].values():
        references.update(item['report'] for item in row['observations'])
        references.update(item['report'] for item in row['verdicts'].values())
    _, state, _ = rt.load(run_dir)
    reports = {ref: rt.digest(report_for(run_dir, state, ref)) for ref in sorted(references)}
    basis = rt.digest({'request': request, 'snapshot': bundle, 'context': context,
                       'reports': reports, 'stage': {key: stage[key] for key in (
                           'key', 'lens', 'pass_number', 'perspective', 'is_final')},
                       'coordinator': rt.coordinator_revision()})
    return purpose, extra, rt.digest(json.dumps(context, ensure_ascii=False).encode()), basis


def cached_ack(run_dir, state, bundle, ack, provider, role, stage, context_hash):
    report = report_for(run_dir, state, ack['report'])
    call = next(call for call in state['calls'] if call.get('report') == ack['report'])
    context = rt.read_json(Path(run_dir) / ('policy-context-' + str(call['number']) + '.json'))
    text = json.dumps(context, ensure_ascii=False)
    rt.require(rt.digest(text.encode()) == context_hash == ack['context_sha256'],
               'Cached acknowledgment context changed.', 'INVALID_RESULT')
    expected = {'provider': provider, 'role': role, 'pass_number': stage['pass_number'],
                **stamp(bundle), 'context_sha256': context_hash}
    rt.validate_result(report['result'], expected, bundle, text)
    rt.require(report['identity']['provider'] == provider and report['result']['status'] == 'CLEAN',
               'Cached native acknowledgment is invalid.', 'INVALID_RESULT')
    verdicts = {item['finding_id']: item for item in report['result']['verdicts']}
    rt.require(all(verdicts.get(fid, {}).get('verdict') == 'AGREE' for fid in state['policy']['findings']),
               'Cached acknowledgment lacks supported dispositions.', 'INVALID_RESULT')
    return ack


def validate_ack_checkpoint(run_dir, request, state, bundle, stage, acknowledgments):
    policy = state['policy']
    _, _, context_hash, basis = ack_inputs(run_dir, request, policy, bundle, stage)
    checkpoint = policy.get('ack_checkpoint', {})
    rt.require(checkpoint.get('basis') == basis and checkpoint.get('acks') == acknowledgments
               and set(acknowledgments) == set(rt.PROVIDERS),
               'Both acknowledgments must cover the unchanged complete evidence basis.', 'INVALID_RESULT')
    for role in ('validation', 'critic'):
        provider = rt.route(request, role, stage['pass_number'], stage['perspective'])
        cached_ack(run_dir, state, bundle, acknowledgments[provider], provider, role, stage, context_hash)


def acknowledge(run_dir):
    request, state, bundle = rt.load(run_dir)
    policy = state['policy']
    fresh(request, state, bundle)
    rt.require(not policy['report_only'], 'Report-only delivery does not manufacture consensus acknowledgments.')
    checks_pass(policy, bundle)
    rt.require(all(row['state'] == 'CLOSED' or row['proposal'] for row in policy['findings'].values()),
               'Open findings need proposed evidence-backed dispositions.', 'UNRESOLVED_DISPUTE')
    final = policy['index'] == len(policy['stages'])
    stage = policy['stages'][-1] if final else current_stage(policy)
    rt.require(stage.get('report') and not stage.get('needs_evidence'), 'Current stage lacks a complete review.')
    purpose, extra, context_hash, basis = ack_inputs(run_dir, request, policy, bundle, stage)
    checkpoint = policy.get('ack_checkpoint', {})
    if checkpoint.get('basis') != basis:
        checkpoint = {'basis': basis, 'stage': stage['key'], 'acks': {}}
        policy['ack_checkpoint'] = checkpoint
        persist(run_dir, state)
    acknowledgments = {}
    admitted = False
    for role in ('validation', 'critic'):
        provider = rt.route(request, role, stage['pass_number'], stage['perspective'])
        if provider in checkpoint['acks']:
            acknowledgments[provider] = cached_ack(run_dir, state, bundle, checkpoint['acks'][provider],
                                                   provider, role, stage, context_hash)
            continue
        if not admitted:
            rt.require(stage.get('exchanges', 0) < MAX_EXCHANGES, 'Dispute exchange limit reached.', 'UNRESOLVED_DISPUTE')
            stage['exchanges'] = stage.get('exchanges', 0) + 1
            persist(run_dir, state)
            admitted = True
        report, ref = native(run_dir, purpose, role, stage, extra)
        request, state, bundle = rt.load(run_dir)
        policy = state['policy']
        stage = policy['stages'][-1] if final else current_stage(policy)
        checkpoint = policy['ack_checkpoint']
        rt.require(ack_inputs(run_dir, request, policy, bundle, stage)[3] == basis,
                   'Acknowledgment basis changed during the call.', 'STALE_ARTIFACT')
        result = report['result']
        if result['status'] != 'CLEAN' or result['findings']:
            ingest(policy, report, ref, bundle, stage['key'], 'proposed_disposition')
            policy['status'] = 'UNRESOLVED_DISPUTE'
            persist(run_dir, state)
            raise rt.ReviewError('UNRESOLVED_DISPUTE', 'Native provider did not accept final evidence/dispositions.')
        verdicts = {item['finding_id']: item for item in result['verdicts']}
        if not all(fid in verdicts and verdicts[fid]['verdict'] == 'AGREE' for fid in policy['findings']):
            # A supported objection is new review evidence, even under CLEAN.
            # Preserve its distinct target and invalidate earlier cache reuse.
            ingest(policy, report, ref, bundle, stage['key'], 'proposed_disposition')
            policy['status'] = 'UNRESOLVED_DISPUTE'
            persist(run_dir, state)
            raise rt.ReviewError('INVALID_RESULT', 'Native acknowledgment must support every substantive disposition.')
        ack = {'report': ref, **stamp(bundle), 'context_sha256': result['context_sha256']}
        acknowledgments[provider] = checkpoint['acks'][provider] = ack
        # Persist each accepted provider before attempting the other. This is not
        # a complete pair and cannot close a finding or advance a stage.
        persist(run_dir, state)
    rt.require(set(acknowledgments) == set(rt.PROVIDERS), 'Both actual providers must acknowledge.')
    for row in policy['findings'].values():
        row['state'] = 'CLOSED'
        row['acknowledgments'] = copy.deepcopy(acknowledgments)
    if final:
        policy['acks'] = acknowledgments
        policy['acks_basis'] = acknowledgment_basis(policy, bundle)
        make_handoff(request, policy, bundle)
        policy['status'] = 'HANDOFF_PENDING'
    else:
        stage['acks'] = acknowledgments
        stage['ack_basis'] = acknowledgment_basis(policy, bundle)
        policy['status'] = 'ACTIVE'
    persist(run_dir, state)
    return status(run_dir)


def make_handoff(request, policy, bundle):
    packet = {'origin_provider': request['origin_provider'], 'origin_session_id': request['origin_session_id'],
              **stamp(bundle), 'reports': [entry['report'] for entry in policy['stages']],
              'ledger_sha256': rt.digest(policy['findings']), 'nonce': secrets.token_hex(16)}
    policy['handoff'] = {**packet, 'handoff_sha256': rt.digest(packet)}
    policy['receipt'] = None


def advance(run_dir):
    request, state, bundle = rt.load(run_dir)
    fresh(request, state, bundle)
    policy, stage = state['policy'], current_stage(state['policy'])
    rt.require(stage.get('report') and not stage.get('needs_evidence'), 'Current pass has no complete report.')
    rt.require(all(stage[key] == value for key, value in stamp(bundle).items()), 'Stage review is stale.')
    report_for(run_dir, state, stage['report'])
    if not policy['report_only']:
        rt.require(all(row['state'] == 'CLOSED' for row in policy['findings'].values()), 'Resolve findings before the next pass.', 'UNRESOLVED_DISPUTE')
        rt.require(not stage.get('requires_ack') or set(stage.get('acks', {})) == set(rt.PROVIDERS),
                   'A material change requires both-provider validation before proceeding.')
        if stage.get('requires_ack') or stage.get('acks'):
            validate_ack_checkpoint(run_dir, request, state, bundle, stage, stage.get('acks', {}))
        checks_pass(policy, bundle)
    stage['complete'] = True
    policy['index'] += 1
    if policy['report_only'] and policy['index'] == len(policy['stages']):
        make_handoff(request, policy, bundle)
        policy['status'] = 'HANDOFF_PENDING'
    persist(run_dir, state)
    return status(run_dir)


def fix(run_dir, value):
    keys(value, ['writer_provider', 'writer_session_id', 'finding_ids', 'reason', 'next_check'])
    request, state, bundle = rt.load(run_dir)
    fresh(request, state, bundle)
    policy = state['policy']
    rt.require(not policy['report_only'] and not policy['pending_fix'], 'No apply authority or an admitted fix is outstanding.')
    rt.require(value['writer_provider'] == policy['writer_provider'] and value['writer_session_id'] == policy['writer_session_id'],
               'Only the designated writer may accept a fix ticket.')
    rt.require(value['reason'] and value['next_check'] and isinstance(value['finding_ids'], list) and value['finding_ids'], 'Fix needs findings, reason, and next check.')
    for fid in value['finding_ids']:
        row = policy['findings'].get(fid)
        rt.require(row is not None, 'Unknown finding.')
        rt.require(any(v['verdict']['verdict'] == 'AGREE' and all(v[key] == val for key, val in stamp(bundle).items())
                       for v in row['verdicts'].values()), 'A supported critic finding is required before a fix.')
    rt.require(policy['fix_rounds'] < min(policy['fix_allowance'], MAX_FIX_ROUNDS), 'Two correction rounds exhausted; stop optional review.', 'UNRESOLVED_BUDGET')
    rt.require(state['invocations'] < request['limits']['max_invocations'], 'Invocation allowance exhausted.', 'UNRESOLVED_BUDGET')
    state['invocations'] += 1
    ticket = {**value, 'number': state['invocations'], 'status': 'FIX_ADMITTED',
              'deadline': min(state['deadline'], time.time() + request['limits']['invocation_seconds']), **stamp(bundle)}
    state['calls'].append(copy.deepcopy(ticket))
    policy['pending_fix'] = ticket
    policy['fix_rounds'] += 1
    policy['acks'], policy['receipt'] = {}, None
    persist(run_dir, state)
    return ticket


def amend(run_dir, value):
    keys(value, ['writer_provider', 'writer_session_id', 'reason', 'next_check', 'authorization'])
    request, state, bundle = rt.load(run_dir)
    fresh(request, state, bundle, allow_completed=True)
    policy = state['policy']
    rt.require(not policy['report_only'] and not policy['pending_fix'], 'No amendment authority or an author action is outstanding.')
    rt.require(value['authorization'] == 'explicit-user-update', 'Amendments require an explicit user update.')
    rt.require(value['writer_provider'] == policy['writer_provider'] and value['writer_session_id'] == policy['writer_session_id'],
               'The designated writer must own the amendment.')
    rt.require(value['reason'] and value['next_check'], 'Record the requested change and next check.')
    rt.require(state['quota'] != 'exhausted' and time.time() < state['deadline']
               and state['invocations'] < request['limits']['max_invocations']
               and policy['fix_rounds'] < min(policy['fix_allowance'], MAX_FIX_ROUNDS), 'Original author-action limits exhausted.', 'UNRESOLVED_BUDGET')
    state['invocations'] += 1
    ticket = {**value, 'number': state['invocations'], 'status': 'FIX_ADMITTED',
              'deadline': min(state['deadline'], time.time() + request['limits']['invocation_seconds']),
              'accounting': 'before-author-dispatch', **stamp(bundle)}
    state['calls'].append(copy.deepcopy(ticket))
    policy['status'] = 'ACTIVE'  # Explicit user amendment invalidates prior readiness immediately.
    policy['pending_fix'] = ticket
    policy['fix_rounds'] += 1
    policy['acks'], policy['receipt'] = {}, None
    persist(run_dir, state)
    return ticket


def extend(run_dir, value):
    raise rt.ReviewError('UNRESOLVED_BUDGET',
                         'Automatic review extensions are disabled. Stop this optional run; retain its history.')


def refresh(run_dir, add_evidence=()):
    request, state, old = rt.load(run_dir)
    policy = state['policy']
    rt.require(not policy.get('stopped'), 'Optional review was stopped.', 'STOPPED')
    rt.require(policy['status'] not in ('CONSENSUS', 'REPORT_DELIVERED'), 'Completed workflows are read-only history.')
    rt.budget_available(request, state)
    candidate = copy.deepcopy(request)
    candidate['evidence'] = list(dict.fromkeys(candidate['evidence'] + list(add_evidence)))
    new = rt.snapshot(candidate)
    rt.require(new != old, 'Refresh requires changed artifact or evidence.')
    if new['artifact_sha256'] != old['artifact_sha256']:
        rt.require(policy['pending_fix'] or not policy['history'], 'Material edits require a prior designated-writer fix ticket.')
    if policy['pending_fix']:
        rt.require(time.time() <= policy['pending_fix']['deadline'], 'Admitted writer action exceeded its deadline.', 'UNRESOLVED_BUDGET')
    rt.refresh(run_dir, add_evidence=add_evidence)
    request, state, bundle = rt.load(run_dir)
    policy = state['policy']
    if policy['pending_fix']:
        for call in state['calls']:
            if call['number'] == policy['pending_fix']['number']:
                call['status'] = 'FIX_RETURNED'
    policy['pending_fix'] = None
    for stage in policy['stages']:
        if stage.get('report'):
            stage['previous_report'] = stage['report']
        for key in ('report', 'acks', 'ack_basis', 'complete', 'exchanges', 'no_progress', 'needs_evidence', 'artifact_sha256', 'evidence_sha256'):
            stage.pop(key, None)
        stage['requires_ack'] = True
    for row in policy['findings'].values():
        row['state'], row['proposal'], row['verdicts'] = 'OPEN', None, {}
        row.pop('acknowledgments', None)
    policy.update(index=0, checks={}, acks={}, receipt=None, status='ACTIVE')
    policy.pop('handoff', None)
    policy.pop('ack_checkpoint', None)
    persist(run_dir, state)
    return status(run_dir)


def receive(run_dir, value):
    keys(value, ['origin_provider', 'origin_session_id', 'artifact_sha256', 'evidence_sha256', 'handoff_sha256', 'nonce'])
    request, state, bundle = rt.load(run_dir)
    fresh(request, state, bundle)
    policy = state['policy']
    packet = policy.get('handoff')
    rt.require(packet and all(value[key] == packet[key] for key in value), 'Receipt does not match the original-host handoff.')
    policy['receipt'] = {**value, 'received_at': time.time()}
    # Receipt is the initiating host's attestation, using the same trusted launch
    # metadata boundary as request origin identity. It never creates provider acks.
    state['handoff']['status'] = 'DELIVERED'
    persist(run_dir, state)
    return status(run_dir)


def finish(run_dir):
    request, state, bundle = rt.load(run_dir)
    policy = state['policy']
    rt.require(not policy.get('stopped'), 'Optional review was stopped.', 'STOPPED')
    if policy['status'] in ('CONSENSUS', 'REPORT_DELIVERED'):
        rt.require(rt.snapshot(request) == bundle, 'Completed review artifact changed.', 'STALE_ARTIFACT')
    else:
        fresh(request, state, bundle)
    rt.require(policy['index'] == len(policy['stages']) and all(entry.get('complete') for entry in policy['stages']),
               'Exactly the selected passes/stages must complete.')
    for stage in policy['stages']:
        report_for(run_dir, state, stage['report'])
        rt.require(all(stage[key] == value for key, value in stamp(bundle).items()), 'A completed pass is stale.')
    rt.require(policy['receipt'] and policy.get('handoff') and all(policy['receipt'][key] == value for key, value in stamp(bundle).items()),
               'The original host has not acknowledged actual receipt.', 'HANDOFF_PENDING')
    if policy['report_only']:
        policy['status'] = 'REPORT_DELIVERED'
    else:
        checks_pass(policy, bundle)
        rt.require(all(row['state'] == 'CLOSED' for row in policy['findings'].values()), 'Required findings remain unresolved.', 'UNRESOLVED_DISPUTE')
        rt.require(set(policy['acks']) == set(rt.PROVIDERS) and policy.get('acks_basis') == acknowledgment_basis(policy, bundle),
                   'Both native providers must acknowledge the exact final evidence and ledger.')
        # Completed legacy reports remain history; new completion must validate
        # the exact current context and every cached report again.
        if policy['status'] != 'CONSENSUS' or 'ack_checkpoint' in policy:
            validate_ack_checkpoint(run_dir, request, state, bundle, policy['stages'][-1], policy['acks'])
        for provider, ack in policy['acks'].items():
            report = report_for(run_dir, state, ack['report'])
            rt.require(report['identity']['provider'] == provider and report['result']['status'] == 'CLEAN'
                       and all(ack[key] == value for key, value in stamp(bundle).items()), 'Native acknowledgment is stale or invalid.')
        policy['status'] = 'CONSENSUS'
    persist(run_dir, state)
    return status(run_dir)


def stop(run_dir, value):
    keys(value, ['reason'])
    rt.require(isinstance(value['reason'], str) and value['reason'].strip(), 'A stopping reason is required.')
    _, state, _ = rt.load(run_dir)
    policy = state['policy']
    rt.require(policy['status'] not in ('CONSENSUS', 'REPORT_DELIVERED'), 'Completed reviews remain history.')
    if state['status'] == 'RUNNING':
        pid = state['calls'][-1].get('child_pid') if state['calls'] else None
        rt.require(type(pid) is int and pid > 1, 'Child identity is unknown; investigate before stopping.', 'BUSY')
        try:
            rt.os.killpg(pid, 0)
        except ProcessLookupError:
            pass  # Dead interrupted child: stopping needs no renewed deadline.
        except PermissionError:
            raise rt.ReviewError('BUSY', 'Cannot verify child exit; investigate before stopping.')
        else:
            raise rt.ReviewError('BUSY', 'Cancel the live child before stopping.')
    policy.setdefault('stopped', {**value, 'at': time.time(), 'previous_status': policy['status']})
    policy['status'] = 'STOPPED'
    persist(run_dir, state)
    return status(run_dir)


def resume(run_dir):
    request, state, bundle = rt.load(run_dir)
    if state['policy']['status'] in ('CONSENSUS', 'REPORT_DELIVERED'):
        return status(run_dir)
    fresh(request, state, bundle)
    if state['status'] not in ('READY', 'REVIEWED'):
        rt.resume(run_dir)
    _, state, _ = rt.load(run_dir)
    state['policy']['status'] = 'ACTIVE'
    persist(run_dir, state)
    return status(run_dir)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    select = sub.add_parser('select')
    select.add_argument('--count', action='append')
    select.add_argument('--source', choices=('explicit', 'interactive'), default='explicit')
    select.add_argument('--unattended', action='store_true')
    select.add_argument('--resume')
    sub.add_parser('preflight')
    init = sub.add_parser('init')
    init.add_argument('--cross-provider', action='store_true')
    init.add_argument('--request')
    init.add_argument('--checks')
    init.add_argument('--run-dir')
    init.add_argument('--mode', choices=('plan', 'etp', 'adrev'))
    init.add_argument('--writer-session-id')
    init.add_argument('--light-review', action='store_true')
    init.add_argument('--report-only', action='store_true')
    commands = ('review', 'critic', 'rebuttal', 'advance', 'acknowledge', 'propose', 'record-check',
                'fix', 'amend', 'extend', 'refresh', 'receive', 'finish', 'status', 'resume', 'stop')
    for name in commands:
        command = sub.add_parser(name)
        command.add_argument('--run-dir', required=True)
        if name in ('propose', 'record-check', 'fix', 'amend', 'extend', 'receive', 'stop'):
            command.add_argument('--file', required=True)
        if name == 'refresh':
            command.add_argument('--add-evidence', action='append', default=[])
    args = parser.parse_args(argv)
    try:
        if args.command == 'select':
            rt.require(not args.count or len(set(args.count)) == 1, 'Contradictory review counts require one explicit selection.')
            result = selection(args.count[0] if args.count else None, args.source, args.unattended, args.resume)
        elif args.command == 'preflight':
            result = preflight()
        elif args.command == 'init' and not args.cross_provider:
            result = lead_review()
        elif args.command == 'init':
            rt.require(all((args.request, args.checks, args.run_dir, args.mode, args.writer_session_id)),
                       'Cross-provider init requires request, checks, run-dir, mode and writer-session-id.')
            result = initialize(rt.read_json(args.request), args.run_dir, args.mode, rt.read_json(args.checks),
                                args.writer_session_id, args.light_review, args.report_only, cross_provider=True)
        else:
            rt.require((Path(args.run_dir) / 'state.json').is_file(), 'Run does not exist.')
            with rt.file_lock(Path(args.run_dir) / '.policy.lock'):
                if args.command in ('review', 'critic', 'rebuttal'):
                    result = do_review(args.run_dir, args.command)
                elif args.command in ('propose', 'record-check', 'fix', 'amend', 'extend', 'receive', 'stop'):
                    function = record_check if args.command == 'record-check' else globals()[args.command]
                    result = function(args.run_dir, payload(args.run_dir, args.file))
                elif args.command == 'refresh':
                    result = refresh(args.run_dir, args.add_evidence)
                else:
                    result = globals()[args.command](args.run_dir)
        print(json.dumps(result, indent=2))
        return 0
    except (rt.ReviewError, OSError, ValueError, KeyError, TypeError) as error:
        code = error.status if isinstance(error, rt.ReviewError) else 'INVALID_REQUEST'
        if code not in ('BUSY', 'INVALID_REQUEST') and getattr(args, 'run_dir', None) and (Path(args.run_dir) / 'state.json').exists():
            try:
                _, state, _ = rt.load(args.run_dir)
                if 'policy' in state:
                    state['policy']['status'] = code
                    persist(args.run_dir, state)
            except (rt.ReviewError, OSError, ValueError, KeyError):
                pass
        print(json.dumps({'status': code, 'error': str(error)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
