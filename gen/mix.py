"""Replaced by gen.package, which reads teacher runs directly and does what this module did (caps per intent and per
question, held-out shops/industries/families from a split's meta.jsonl) on the one sample format used end to end
({"id", "prompt", "completion", "meta"}). The old module read a format no exporter writes any more.

    python -m gen.package --teacher <run> [<run> ...] --out <dir> [--cap-intent N] [--per-question N]
        [--val-shops ...] [--val-industries ...] [--val-families ...]
"""
from __future__ import annotations

import sys

if __name__ == '__main__':
    raise SystemExit('gen.mix was replaced by gen.package: ' + ' '.join(__doc__.split('\n')[4:6]).strip()
                     + ('' if len(sys.argv) < 2 else f'\n(arguments given: {" ".join(sys.argv[1:])})'))
