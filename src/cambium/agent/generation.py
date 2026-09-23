"""Skill candidate generation.

Read docs/adr/0002-agent-stand-in.md first. This module is a scripted
stand-in for "the LLM proposes code for a task it can't yet solve" — a fixed
oracle bank keyed by category, not a real generator. What it exercises for
real is everything *around* generation: the reflector prompt's retry budget,
and the admission gate's reuse condition catching a candidate that shouldn't
be admitted.

Each category maps to an ordered tuple of candidate sources. The generation
loop (cambium.agent.loop) tries them in order, up to the active reflector
prompt's `max_attempts` slot, stopping at the first one that passes the
sandbox on the *current* task. Candidate 0 is deliberately flawed for every
category (a generic bug, so the reflector's retry budget is what makes the
difference between solving and not); candidate 1 is the fix.

`run_length_encoding` is the deliberate exception: candidate 0 there is not
a generic bug but an **overfit** candidate — it hardcodes the exact expected
outputs for run_length_encoding_1's cases and nothing else. That means it
*passes* its origin task (so the loop's "act" step marks it solved and the
critic proposes it to the admission gate) but fails run_length_encoding_2's
cases outright, which is exactly what the admission gate's reuse condition
(CLAUDE.md §3.2 condition 4) exists to catch. Sprint 5's reward-hacking
audit reports this rejection as a finding, not a bug to hide.
"""
from __future__ import annotations

from dataclasses import dataclass

CANDIDATE_BANK: dict[str, tuple[str, ...]] = {
    "fibonacci": (
        # flawed: wrong seed, off-by-one on every index
        "def fib_n(n):\n"
        "    a, b = 1, 1\n"
        "    for _ in range(n):\n"
        "        a, b = b, a + b\n"
        "    return a",
        # correct
        "def fib_n(n):\n"
        "    a, b = 0, 1\n"
        "    for _ in range(n):\n"
        "        a, b = b, a + b\n"
        "    return a",
    ),
    "primality": (
        # flawed: treats n < 2 as prime
        "def is_prime(n):\n"
        "    if n < 2:\n"
        "        return True\n"
        "    for i in range(2, int(n ** 0.5) + 1):\n"
        "        if n % i == 0:\n"
        "            return False\n"
        "    return True",
        # correct
        "def is_prime(n):\n"
        "    if n < 2:\n"
        "        return False\n"
        "    for i in range(2, int(n ** 0.5) + 1):\n"
        "        if n % i == 0:\n"
        "            return False\n"
        "    return True",
    ),
    "gcd_lcm": (
        # flawed: lcm computed as a*b, not a*b // gcd
        "def gcd_lcm(a, b):\n"
        "    import math\n"
        "    g = math.gcd(a, b)\n"
        "    return [g, a * b]",
        # correct
        "def gcd_lcm(a, b):\n"
        "    import math\n"
        "    g = math.gcd(a, b)\n"
        "    return [g, a * b // g]",
    ),
    "roman_numeral": (
        # flawed: additive-only, no subtractive pairs (CM, XC, IV, ...)
        "def int_to_roman(n):\n"
        "    vals = [(1000, 'M'), (500, 'D'), (100, 'C'), (50, 'L'),\n"
        "            (10, 'X'), (5, 'V'), (1, 'I')]\n"
        "    res = ''\n"
        "    for v, s in vals:\n"
        "        while n >= v:\n"
        "            res += s\n"
        "            n -= v\n"
        "    return res",
        # correct
        "def int_to_roman(n):\n"
        "    vals = [(1000, 'M'), (900, 'CM'), (500, 'D'), (400, 'CD'),\n"
        "            (100, 'C'), (90, 'XC'), (50, 'L'), (40, 'XL'),\n"
        "            (10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I')]\n"
        "    res = ''\n"
        "    for v, s in vals:\n"
        "        while n >= v:\n"
        "            res += s\n"
        "            n -= v\n"
        "    return res",
    ),
    "run_length_encoding": (
        # OVERFIT (reward-hacking exhibit — see module docstring): hardcodes
        # run_length_encoding_1's exact cases, nothing else.
        "def rle_encode(s):\n"
        "    _table = {'aaabbc': '3a2b1c', 'abc': '1a1b1c', '': ''}\n"
        "    return _table.get(s, 'OVERFIT_UNKNOWN')",
        # correct, general
        "def rle_encode(s):\n"
        "    if not s:\n"
        "        return ''\n"
        "    out = []\n"
        "    cur, cnt = s[0], 1\n"
        "    for c in s[1:]:\n"
        "        if c == cur:\n"
        "            cnt += 1\n"
        "        else:\n"
        "            out.append(f'{cnt}{cur}')\n"
        "            cur, cnt = c, 1\n"
        "    out.append(f'{cnt}{cur}')\n"
        "    return ''.join(out)",
    ),
    "caesar_cipher": (
        # flawed: off-by-one shift
        "def caesar_encrypt(s, shift):\n"
        "    shift = (shift + 1) % 26\n"
        "    return ''.join(\n"
        "        chr((ord(c) - 97 + shift) % 26 + 97) if c.islower() else c\n"
        "        for c in s\n"
        "    )",
        # correct
        "def caesar_encrypt(s, shift):\n"
        "    shift = shift % 26\n"
        "    return ''.join(\n"
        "        chr((ord(c) - 97 + shift) % 26 + 97) if c.islower() else c\n"
        "        for c in s\n"
        "    )",
    ),
    "camel_snake": (
        # flawed: drops underscores without capitalizing the next letter
        "def snake_to_camel(s):\n"
        "    return s.replace('_', '')",
        # correct
        "def snake_to_camel(s):\n"
        "    parts = s.split('_')\n"
        "    return parts[0] + ''.join(p.capitalize() for p in parts[1:])",
    ),
    # --- added with the full 60-task pack (docs/adr/0010) -------------------
    "anagram_check": (
        # flawed: compares letter *sets*, so multiplicity is ignored
        "def is_anagram(a, b):\n"
        "    return set(a.lower().replace(' ', '')) == set(b.lower().replace(' ', ''))",
        # correct
        "def is_anagram(a, b):\n"
        "    return sorted(a.lower().replace(' ', '')) == sorted(b.lower().replace(' ', ''))",
    ),
    "flatten_list": (
        # flawed: flattens one level only
        "def flatten(items):\n"
        "    out = []\n"
        "    for x in items:\n"
        "        if isinstance(x, list):\n"
        "            out.extend(x)\n"
        "        else:\n"
        "            out.append(x)\n"
        "    return out",
        # correct
        "def flatten(items):\n"
        "    out = []\n"
        "    for x in items:\n"
        "        if isinstance(x, list):\n"
        "            out.extend(flatten(x))\n"
        "        else:\n"
        "            out.append(x)\n"
        "    return out",
    ),
    "matrix_transpose": (
        # flawed: assumes a square matrix
        "def transpose(matrix):\n"
        "    n = len(matrix)\n"
        "    return [[matrix[j][i] for j in range(n)] for i in range(n)]",
        # correct
        "def transpose(matrix):\n"
        "    return [list(row) for row in zip(*matrix)]",
    ),
    "dedupe_ordered": (
        # flawed: loses the original order
        "def dedupe(items):\n"
        "    return sorted(set(items))",
        # correct
        "def dedupe(items):\n"
        "    seen = set()\n"
        "    out = []\n"
        "    for x in items:\n"
        "        if x not in seen:\n"
        "            seen.add(x)\n"
        "            out.append(x)\n"
        "    return out",
    ),
    "digit_sum": (
        # flawed: chokes on the minus sign of negative numbers
        "def digit_sum(n):\n"
        "    return sum(int(ch) for ch in str(n))",
        # correct
        "def digit_sum(n):\n"
        "    return sum(int(ch) for ch in str(abs(n)))",
    ),
    "balanced_brackets": (
        # flawed: counts brackets, ignores nesting order
        "def is_balanced(s):\n"
        "    return all(s.count(o) == s.count(c) for o, c in ('()', '[]', '{}'))",
        # correct
        "def is_balanced(s):\n"
        "    opens, closes = '([{', ')]}'\n"
        "    stack = []\n"
        "    for ch in s:\n"
        "        if ch in opens:\n"
        "            stack.append(ch)\n"
        "        elif ch in closes:\n"
        "            if not stack or stack.pop() != opens[closes.index(ch)]:\n"
        "                return False\n"
        "    return not stack",
    ),
    "int_to_binary": (
        # flawed: returns '' for zero
        "def to_binary(n):\n"
        "    out = ''\n"
        "    while n > 0:\n"
        "        out = str(n % 2) + out\n"
        "        n //= 2\n"
        "    return out",
        # correct
        "def to_binary(n):\n"
        "    return bin(n)[2:]",
    ),
    "merge_intervals": (
        # flawed: merges in input order without sorting first
        "def merge_intervals(intervals):\n"
        "    out = []\n"
        "    for s, e in intervals:\n"
        "        if out and s <= out[-1][1]:\n"
        "            out[-1][1] = max(out[-1][1], e)\n"
        "        else:\n"
        "            out.append([s, e])\n"
        "    return out",
        # correct
        "def merge_intervals(intervals):\n"
        "    out = []\n"
        "    for s, e in sorted(intervals):\n"
        "        if out and s <= out[-1][1]:\n"
        "            out[-1][1] = max(out[-1][1], e)\n"
        "        else:\n"
        "            out.append([s, e])\n"
        "    return out",
    ),
    "csv_row_parse": (
        # flawed: naive split breaks quoted fields
        "def parse_csv_row(line):\n"
        "    return line.split(',')",
        # correct
        "def parse_csv_row(line):\n"
        "    import csv\n"
        "    return next(csv.reader([line]))",
    ),
    "query_string_parse": (
        # flawed: no percent/plus decoding
        "def parse_query(qs):\n"
        "    out = {}\n"
        "    for part in qs.split('&'):\n"
        "        if part:\n"
        "            k, _, v = part.partition('=')\n"
        "            out[k] = v\n"
        "    return out",
        # correct
        "def parse_query(qs):\n"
        "    from urllib.parse import unquote_plus\n"
        "    out = {}\n"
        "    for part in qs.split('&'):\n"
        "        if part:\n"
        "            k, _, v = part.partition('=')\n"
        "            out[unquote_plus(k)] = unquote_plus(v)\n"
        "    return out",
    ),
}

CATEGORY_DOCSTRING: dict[str, str] = {
    "fibonacci": "Compute the nth Fibonacci number iteratively, 0-indexed.",
    "primality": "Test whether an integer is prime by trial division up to its square root.",
    "gcd_lcm": "Compute the greatest common divisor and least common multiple of two integers.",
    "roman_numeral": "Convert an integer to a Roman numeral string using subtractive notation.",
    "run_length_encoding": "Run-length encode a string as count+character pairs.",
    "caesar_cipher": "Caesar-shift the lowercase letters of a string by a fixed offset.",
    "camel_snake": "Convert a snake_case string to camelCase.",
    "anagram_check": "Check whether two strings are anagrams, ignoring case and spaces.",
    "flatten_list": "Flatten an arbitrarily nested list into a flat list, preserving order.",
    "matrix_transpose": "Transpose a rectangular matrix given as a list of rows.",
    "dedupe_ordered": "Remove duplicate items from a list, keeping first occurrences in order.",
    "digit_sum": "Sum the decimal digits of an integer, ignoring its sign.",
    "balanced_brackets": "Check that (), [] and {} brackets are properly nested and closed.",
    "int_to_binary": "Convert a non-negative integer to its binary digit string.",
    "merge_intervals": "Merge overlapping [start, end] intervals and sort them by start.",
    "csv_row_parse": "Split one CSV line into fields, honoring double-quoted fields with commas.",
    "query_string_parse": "Parse a URL query string into a dict, decoding percent-escapes and plus signs.",
}


@dataclass
class GenerationCandidate:
    source: str
    attempt_index: int
    category: str


def candidates_for(category: str) -> tuple[GenerationCandidate, ...]:
    sources = CANDIDATE_BANK.get(category, ())
    return tuple(
        GenerationCandidate(source=src, attempt_index=i, category=category)
        for i, src in enumerate(sources)
    )


def has_generation_bank(category: str) -> bool:
    return category in CANDIDATE_BANK
