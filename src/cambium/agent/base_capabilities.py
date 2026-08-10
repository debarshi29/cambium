"""Base capabilities: what the agent can solve with no library at all.

These back the `library-off` baseline curve (CLAUDE.md §4) and the "does the
agent already know this" check the generation loop makes before it bothers
synthesizing a skill. Three of the ten task categories are covered here on
purpose — the other seven exist specifically to require a synthesized,
admitted skill, so that any lift the library shows is attributable to the
library and not to the base agent quietly being able to do everything.
"""
from __future__ import annotations

BASE_CAPABILITY_SOURCE: dict[str, str] = {
    "string_reverse": '''
def reverse_string(s):
    return s[::-1]
'''.strip(),
    "word_count": '''
def word_count(s):
    return len(s.split())
'''.strip(),
    "palindrome_check": '''
def is_palindrome(s):
    return s == s[::-1]
'''.strip(),
}


def has_base_capability(category: str) -> bool:
    return category in BASE_CAPABILITY_SOURCE


def base_capability_source(category: str) -> str:
    return BASE_CAPABILITY_SOURCE[category]
