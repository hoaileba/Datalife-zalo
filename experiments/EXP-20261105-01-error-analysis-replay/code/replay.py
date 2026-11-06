from __future__ import annotations

import re
import sys
import threading

from datamate_agent import agent

EXAMPLE = re.compile(r"^- (.*)\n  (FINAL \w+: .*)$", flags=re.M)
ANCHORS = (("print(revenue(clock.month(5, 2026)))", "print(<hàm>(<kỳ>))"), ("revenue(clock.month(5, 2026))", "<hàm>(<kỳ>)"))
context = threading.local()
original_solve = agent.solve
original_read = agent.read_data
original_build = agent.build_system


def solve(*, question, hints, **kwargs):
    match = EXAMPLE.search(hints)
    context.reminder = f"\n\nNhắc lại câu hỏi: {question['question']}\nVí dụ giống nhất:\n- {match.group(1)}\n  {match.group(2)}" if match else f"\n\nNhắc lại câu hỏi: {question['question']}"
    return original_solve(question=question, hints=hints, **kwargs)


def read_data(*args, **kwargs):
    output = original_read(*args, **kwargs)
    return output if output.startswith("ERROR") else output + context.reminder


def neutral_build(**kwargs):
    system = original_build(**kwargs)
    for old, new in ANCHORS:
        system = system.replace(old, new)
    return system


def main() -> int:
    arm, *rest = sys.argv[1:]
    agent.solve = solve
    agent.read_data = read_data
    if arm == "neutral":
        agent.build_system = neutral_build
    return agent.main(rest)


if __name__ == "__main__":
    raise SystemExit(main())
