"""One question: at most `max_calls` model turns. Each turn the model writes ONE program that ends with
result = {"type", "answer"[, "reason", "checked"]}; the host runs it and submits at once when the answer has the
type's shape and passes the checks. "look" is shown, never submitted; "abstain" ends the question; "unanswerable"
comes back once with the rows and date ranges of the shop's tables and is submitted only with "checked": True.

In:  question dict {id, question, as_of}, `Context` (llm, catalog, business, tables path, config).
Out: `Outcome` (answer_type, answer, reason, calls, trace). Never raises: any failure ends in abstain.
Turn outcomes: program error / cut output / no program -> the error goes back to the model; a result that fails
the checks -> it goes back (the model fixes it, or returns it again with "checked": True, or abstains);
the same failing program twice in a row, the deadline or the call cap -> abstain.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from . import prompt, sandbox
from .answer import AnswerError, finalize, issues, retype
from .catalog import lookup

STOPPED = {
    'repetition': 'Output started repeating the same lines and was stopped. Write a short program with no repeated statements.',
    'comments': 'Output was stopped: the code block filled with comment lines. Think in REASON; in the code, one comment per block and only short ones elsewhere.',
    'length': 'Output reached the token cap. Write REASON with only what this question needs, and the program complete.',
}
TRACE = 3000                                     # chars of the step trace shown for a repair
TAIL = 1500
RESULT = 20000                                   # chars of a program result kept in the trace (logs only)


@dataclass
class Context:
    llm: object
    catalog: dict
    business: object
    tables_path: str
    config: dict
    system: str = prompt.SYSTEM          # the one system prompt (v5: the same for every set)


@dataclass
class Outcome:
    answer_type: str
    answer: object = None
    reason: str = ''
    calls: int = 0
    trace: list = field(default_factory=list)


def _echo(action):
    return action                                    # the history shows the action as prompt.render_action writes it


def _limits(cfg, deadline):
    wall = max(1.0, min(cfg['sandbox']['wall_seconds'], deadline - time.monotonic()))
    return sandbox.Limits(memory_bytes=int(cfg['sandbox']['memory_gib'] * (1 << 30)), cpu_seconds=cfg['sandbox']['cpu_seconds'],
                          wall_seconds=wall)


def _clip(text, keep=TAIL):                          # the head and the end of a long output, the cut said
    return text if len(text) <= keep else f'{text[:keep - 400]}\n[... {len(text) - keep} characters cut ...]\n{text[-400:]}'


LOOKED = ('Now write the program that computes the answer: REASON, ASKED, RULES, PLAN, the ```python block (start with CAUSE only if '
          'the look showed a mistake in your plan).')
FLAGGED = ('The result may be wrong (see issues). Fix the program (start with CAUSE:); if it is truly right, resend the same '
           'program with "checked": True in its result line (the answer must stay the same); if the data cannot support an '
           'answer, return {"type": "abstain"}.')
UNANSWERABLE = ('Before "unanswerable" is submitted, check it against the evidence (rows and date ranges of every '
                'shop table). If the data truly cannot answer (no such column or table, or the period wholly outside the '
                "shop's dates for the asked kind of event), return the same result with \"checked\": True; otherwise compute "
                'the answer (a period partly inside the data is computed on that part).')


def _run_program(action, question, ctx, deadline, trace, flagged):
    """(outcome (kind, answer) to end with, or None; observation or None). `flagged`: what the previous turn's result
    came back flagged as: 'unanswerable', ('answer', its JSON) or None; "checked": True submits only that result."""
    started = time.monotonic()
    run = sandbox.execute(action['code'], ctx.tables_path, question['as_of'], _limits(ctx.config, deadline))
    res = run.result if run.ok else {}
    event = {'event': 'execution', 'turn': action['turn'], 'code': action['code'], 'ok': run.ok, 'stdout': _clip(run.stdout),
             'trace': run.trace[-TRACE:], 'answer_type': res.get('type'), 'seconds': round(time.monotonic() - started, 3),
             'result': json.dumps(res, ensure_ascii=False, default=str)[:RESULT] if run.ok else None}
    trace.append(event)
    steps = {'trace': run.trace[-TRACE:]} if run.trace else {}       # shown only when the program needs a repair
    if not run.ok and run.error.get('type') == 'NoResult':      # only prints: a look without its result line
        event.update(explore=True, no_result=True)
        return None, {'status': 'looked', 'stdout': _clip(run.stdout), 'next': 'No result was assigned, so this was a look '
                      '(end a look with result = {"type": "look"}). ' + LOOKED}
    if not run.ok:
        event['error'] = run.error
        return None, {'status': 'error', 'error': run.error_text()[:3500], 'stdout': _clip(run.stdout), **steps}
    kind = res['type']
    if kind == 'look':                                          # looked at the data: shown, never submitted
        event['explore'] = True
        return None, {'status': 'looked', 'stdout': _clip(run.stdout), 'next': LOOKED}
    if kind == 'abstain':
        return ('abstain', None), None
    if kind == 'unanswerable':
        if res['checked'] and flagged == 'unanswerable':
            return ('unanswerable', None), None
        event['issues'] = ['unanswerable not checked yet']
        return None, {'status': 'not_finalized', 'flag': 'unanswerable', 'issues': ['unanswerable: ' + (res['reason'] or 'no reason given')],
                      'evidence': res.get('evidence') or [], 'stdout': _clip(run.stdout), 'next': UNANSWERABLE}
    try:
        answer = finalize(kind, res['answer'])
    except AnswerError as exc:
        return None, {'status': 'error', 'error': str(exc), 'stdout': _clip(run.stdout), **steps}
    problems = event['issues'] = issues(kind, answer, question['question'])
    same = json.dumps(answer, ensure_ascii=False, sort_keys=True)
    if not problems or (res['checked'] and flagged == ('answer', same)):      # confirmed: the flagged answer, unchanged
        kind, answer = retype(kind, answer)
        if kind != 'unanswerable' or (res['checked'] and flagged == 'unanswerable'):   # "unanswerable" as a value: checked too
            return (kind, answer), None
        problems = event['issues'] = ['the answer says unanswerable']
        return None, {'status': 'not_finalized', 'flag': 'unanswerable', 'issues': problems, 'evidence': res.get('evidence') or [], 'stdout': _clip(run.stdout), 'next': UNANSWERABLE}
    return None, {'status': 'not_finalized', 'flag': ('answer', same), 'issues': problems, 'result': json.dumps(answer, ensure_ascii=False)[:TAIL],
                  'stdout': _clip(run.stdout), **steps, 'next': FLAGGED}


def _read_reply(reply, terminal):
    """(action, observation): observation is set when the reply cannot be acted on."""
    if reply.finish in STOPPED:
        return {'action': 'invalid'}, {'status': 'error', 'error': STOPPED[reply.finish]}
    try:
        return prompt.parse_action(reply.text, terminal), None
    except prompt.ActionError as exc:
        return {'action': 'invalid'}, {'status': 'error', 'error': str(exc)}


def solve(question, ctx: Context, deadline: float) -> Outcome:
    history, trace, previous_failure, flagged = [], [], None, None
    matches = lookup(question['question'], ctx.business)
    max_calls = ctx.config['agent']['max_calls']
    out = lambda kind, reason, calls, answer=None: Outcome(kind, answer, reason, calls, trace)
    for turn in range(max_calls):
        if time.monotonic() > deadline - 5:
            return out('abstain', 'deadline', turn)
        terminal = turn == max_calls - 1
        messages = prompt.messages(ctx.catalog, question['question'], question['as_of'], matches, history, max_calls - turn,
                                   terminal, ctx.system)
        try:
            reply = ctx.llm.chat(messages, deadline=deadline)
        except Exception as exc:
            trace.append({'event': 'llm_error', 'error': f'{type(exc).__name__}: {exc}'[:500]})
            return out('abstain', 'llm_error', turn + 1)
        trace.append({'event': 'model', 'turn': turn, 'output': reply.text, 'finish': reply.finish, 'usage': reply.usage,
                      'seconds': reply.seconds, **({'reasoning': reply.reasoning} if reply.reasoning else {}),
                      **({'meta': reply.meta} if reply.meta else {})})
        if reply.finish == 'deadline':
            return out('abstain', 'deadline', turn + 1)
        action, observation = _read_reply(reply, terminal)
        if observation is None:
            ended, observation = _run_program({**action, 'turn': turn}, question, ctx, deadline, trace, flagged)
            if ended is not None:
                kind, answer = ended
                reason = 'model_decision' if kind in ('abstain', 'unanswerable') else 'confirmed' if flagged and trace[-1].get('issues') else 'auto_finalized'
                return out(kind, reason, turn + 1, answer)
        flag = observation.pop('flag', None)                  # host-side only: never shown to the model
        flagged = flag if observation['status'] != 'error' else flagged   # an error turn keeps the earlier flag
        trace.append({'event': 'observation', 'turn': turn, 'observation': observation})
        failure = (action.get('code'), observation['error']) if observation['status'] == 'error' else None
        if failure and failure == previous_failure:
            return out('abstain', 'repeated_error', turn + 1)
        previous_failure = failure
        history.append((_echo(action), observation))
    return out('abstain', 'call_cap', max_calls)
