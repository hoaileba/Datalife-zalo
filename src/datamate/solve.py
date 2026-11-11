"""One question: at most `max_calls` model turns. Each turn the model writes a program (or decides); the host
runs it, and submits at once when the result has the declared shape and passes the checks.

In:  question dict {id, question, as_of}, `Context` (llm, catalog, business, tables path, config).
Out: `Outcome` (answer_type, answer, reason, calls, trace). Never raises: any failure ends in abstain.
Turn outcomes: program error / cut output / invalid JSON -> the error goes back to the model; result that fails
the checks -> the result goes back (the model fixes it, confirms it with an answer action, or abstains);
the same failing program twice in a row, the deadline or the call cap -> abstain.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from . import prompt, sandbox
from .answer import ALL_ZERO, AnswerError, finalize, issues, retype
from .catalog import lookup

STOPPED = {
    'repetition': 'Output started repeating the same lines and was stopped. Write a short program with no repeated statements.',
    'comments': 'Output was stopped: the code block filled with comment lines. Reason before the code block; keep comments short.',
    'length': 'Output reached the token cap. Write a shorter answer: tighter reasoning, the code complete.',
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
    system: str = prompt.SYSTEM          # this set's system prompt (its cookbook without the recipes it changed)


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


def _run_program(action, question, ctx, deadline, trace):
    """(answer to submit or None, last result or None, observation or None)."""
    started = time.monotonic()
    run = sandbox.execute(action['code'], ctx.tables_path, question['as_of'], _limits(ctx.config, deadline))
    event = {'event': 'execution', 'turn': action['turn'], 'code': action['code'], 'ok': run.ok, 'stdout': _clip(run.stdout),
             'trace': run.trace[-TRACE:], 'answer_type': action['answer_type'], 'seconds': round(time.monotonic() - started, 3),
             'result': json.dumps(run.result, ensure_ascii=False, default=str)[:RESULT] if run.ok else None}
    trace.append(event)
    steps = {'trace': run.trace[-TRACE:]} if run.trace else {}       # shown only when the program needs a repair
    if action['answer_type'] == prompt.EXPLORE:                 # looked at the data: shown, never submitted
        event['explore'] = True
        shown = run.result if run.ok else None
        return None, None, {'status': 'explored', 'stdout': _clip(run.stdout),
                            **({'result': json.dumps(shown, ensure_ascii=False, default=str)[:TAIL]} if shown is not None else {}),
                            **({'error': run.error_text()[:3500]} if not run.ok and run.error.get('type') != 'NoResult' else {}),
                            'next': 'Now write the program that computes the answer: its Answer type line, then the ```python block.'}
    if not run.ok:
        event['error'] = run.error
        return None, None, {'status': 'error', 'error': run.error_text()[:3500], 'stdout': _clip(run.stdout), **steps}
    try:
        answer = finalize(action['answer_type'], run.result)
    except AnswerError as exc:
        return None, None, {'status': 'error', 'error': str(exc), 'stdout': _clip(run.stdout), **steps}
    problems = event['issues'] = issues(action['answer_type'], answer, question['question'])
    if not problems:
        return answer, run.result, None
    return None, run.result, {'status': 'not_finalized', 'issues': problems, 'result': json.dumps(answer, ensure_ascii=False)[:TAIL],
                              'stdout': _clip(run.stdout), **steps, 'next': 'The result may be wrong (see issues). Fix the program; if '
                              'it is truly right, submit it as it is: reply "Answer type: <its type>" and why, with no code '
                              'block; if the data cannot support it, reply "Answer type: abstain".'}


def _read_reply(reply, terminal):
    """(action, observation): observation is set when the reply cannot be acted on."""
    if reply.finish in STOPPED:
        return {'action': 'invalid'}, {'status': 'error', 'error': STOPPED[reply.finish]}
    try:
        return prompt.parse_action(reply.text, terminal), None
    except prompt.ActionError as exc:
        return {'action': 'invalid'}, {'status': 'error', 'error': str(exc)}


def solve(question, ctx: Context, deadline: float) -> Outcome:
    history, trace, last, previous_failure, confirmable, zero_programs = [], [], None, None, False, set()
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
        if observation is None and action['action'] == 'answer':
            kind = action['answer_type']
            if kind in ('unanswerable', 'abstain'):
                return out(kind, 'model_decision', turn + 1)
            if last is None:
                observation = {'status': 'error', 'error': 'No program has produced a result yet: write a ```python block with its Answer type.'}
            elif not confirmable:
                observation = {'status': 'error', 'error': f'A result where {ALL_ZERO} cannot be confirmed yet: fix the '
                               'filters so they match rows, or check it with a different program (two programs giving 0 '
                               'can be confirmed), or reply "Answer type: abstain" or "Answer type: unanswerable".'}
            else:
                try:
                    kind, answer = retype(kind, finalize(kind, last))
                    return out(kind, 'confirmed', turn + 1, answer)
                except AnswerError as exc:
                    observation = {'status': 'error', 'error': str(exc)}
        if observation is None:
            answer, result, observation = _run_program({**action, 'turn': turn}, question, ctx, deadline, trace)
            if result is not None:
                zero = observation is not None and any(i.startswith(ALL_ZERO) for i in observation.get('issues', []))
                zero_programs |= {action.get('code')} if zero else set()
                last, confirmable = result, not zero or len(zero_programs) >= 2      # 0 from two different programs
            if answer is not None:
                kind, answer = retype(action['answer_type'], answer)
                return out(kind, 'auto_finalized', turn + 1, answer)
        trace.append({'event': 'observation', 'turn': turn, 'observation': observation})
        failure = (action.get('code'), observation['error']) if observation['status'] == 'error' else None
        if failure and failure == previous_failure:
            return out('abstain', 'repeated_error', turn + 1)
        previous_failure = failure
        history.append((_echo(action), observation))
    return out('abstain', 'call_cap', max_calls)
