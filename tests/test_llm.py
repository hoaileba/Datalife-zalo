"""Stream guards (llm.py): degenerate output is stopped early, ordinary output is not."""
from datamate.llm import comment_flood, repeated_lines


def _reply(kinds):
    items = ['# why %d' % i if k == '#' else 'x%d = %d' % (i, i) for i, k in enumerate(kinds)]
    return '# Plan\n# not code\nAnswer type: number\n```python\n' + '\n'.join(items)


def test_comment_flood_only_when_comments_dominate():
    assert not comment_flood(_reply('cccccccc####cccc##cc###c#c'), 12)        # comments between code lines: let through
    assert not comment_flood(_reply('cccc' + '#' * 12), 12)                   # many comments, still a program
    assert comment_flood(_reply('cc' + '#' * 40), 40)
    assert not comment_flood('# a\n' * 20 + 'Answer type: number', 12)       # before the code block nothing counts


def test_repeated_lines():
    assert repeated_lines('\n'.join(['df = df[df["a"] > 1]'] * 6))
    assert not repeated_lines('\n'.join(f'x{i} = {i} + something' for i in range(30)))
