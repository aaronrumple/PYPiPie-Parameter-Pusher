# -*- coding: utf-8 -*-
"""Tests for the rule sandbox and guards. Pure Python - no Revit needed.

    cd DataPusher.extension/lib
    python -m pytest ../tests -q        (or: python ../tests/test_rules.py)
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))

from pypipie import rules as r  # noqa: E402

FUNCTIONAL = [
    ("value * 2", 5, 10),
    ("switch(value, {'a': 'Alpha'}, default=value)", "A", "Alpha"),
    ("when(value < 100, 'Small', value < 500, 'Med', 'Large')", 250, "Med"),
    ("if not value:\n    value = 'N/A'", None, "N/A"),
    ("  x = value + 1\n  value = x * 2", 1, 4),
    ("pad(to_int(value), 3)", "7", "007"),
    ("re_find(r'(\\d+)', text, 1)", "Room 204B", "204"),
    ("'RM-{}'.format(value)", 12, "RM-12"),
    ("round_to(value, 0.5)", 3.3, 3.5),
    ("value.upper().strip()", " ab ", "AB"),
    ("[c for c in value if c.isdigit()]", "a1b2", ["1", "2"]),
    ("t = 0\nfor i in range(10):\n    t += i\nvalue = t", 0, 45),
    ("pow(value, 2)", 3, 9),
    ("sorted([3, 1, 2], key=lambda x: -x)", 0, [3, 2, 1]),
    ("'%05.1f' % value", 3.14159, "003.1"),
]

SANDBOX_BLOCKED = [
    "import os", "__import__('os')", "value.__class__", "value.GetType()", "open('x')",
    "while True:\n    pass", "def f():\n    pass", "getattr(value, 'x')", "().__class__",
    "switch.func_globals", "try:\n    x = 1\nexcept:\n    pass", "x = 1 +",
]

PATHOLOGICAL_BLOCKED = [
    "10**10**10", "2**100000", "2**(10*10000)", "'x' * 10**9", "[0] * (1000*2000)",
    "1 << 100000", "range(10**8)", "'%0999999d' % value", "'{:>{w}}'.format(value, w=5)",
    "f = lambda x: f(x)\nvalue = f(1)", "(lambda g: g(g))(lambda g: g(g))",
    "items = [1]\nitems[0] *= 5",
]

WARNED = ["2 ** value", "'-' * value",
          "t = 0\nfor x in range(100):\n    for y in range(100):\n        t = t + x * y\nvalue = t",
          "re_test(r'(a+)+$', text)"]

# IronPython 2.7 drops all but the first `for` of a comprehension, so these are refused
MULTI_FOR = ["[x*y for x in range(3) for y in range(2)]",
             "{k: v for k in 'ab' for v in 'cd'}",
             "sum(x for x in range(3) for y in range(2))"]

RUNTIME_GUARDED = [
    ("2 ** value", 10 ** 7),
    ("'-' * value", 10 ** 9),
    ("s = 'ab'\nfor i in range(40):\n    s = s + s\nvalue = s", 0),
    ("x = 3\nfor i in range(100):\n    x = x * x\nvalue = x", 0),
    ("t = 0\nfor i in range(5000):\n    for j in range(5000):\n        t += 1\nvalue = t", 0),
    ("value.rjust(10**8)", "x"),
    ("'a'.replace('a', 'b'*900000).replace('b', 'cc')", 0),
    ("pad(1, 10**9)", 0),
]


def test_functional():
    for code, value, expected in FUNCTIONAL:
        res, err = r.test_value(code, value)
        assert err is None, (code, err)
        assert res == expected, (code, res, expected)


def test_skip():
    res, _ = r.test_value("if target:\n    return SKIP\nreturn value", "x", target="t")
    assert res is r.SKIP


def test_templates_compile_and_finish():
    for name, code in r.TEMPLATES:
        r.compile_rule(code)
        assert r.sandbox(code)["finished"], name


def test_sandbox_blocks():
    for code in SANDBOX_BLOCKED:
        try:
            r.check(code)
        except r.RuleError:
            continue
        raise AssertionError("not blocked: %r" % code)


def test_pathological_blocked():
    for code in PATHOLOGICAL_BLOCKED:
        try:
            r.check(code)
        except r.RuleError:
            continue
        raise AssertionError("not blocked: %r" % code)


def test_multi_for_comprehensions_refused():
    for code in MULTI_FOR:
        try:
            r.check(code)
        except r.RuleError as ex:
            assert "comprehension" in ex.args[0], ex
            continue
        raise AssertionError("not refused: %r" % code)
    r.check("[x for x in 'for']")              # 'for' inside a string is fine
    r.check("# for a in b\n[x for x in 'ab']")  # ... and inside a comment


def test_issue_from_screenshot():
    code = "# Transform the incoming value, e.g.\nvalue = value.upper()\nvalue\n"
    assert r.test_value(code, "adsfasdf") == ("ADSFASDF", None)


def test_warnings():
    for code in WARNED:
        assert r.lint(code), code


def test_runtime_guards_are_fast():
    for code, value in RUNTIME_GUARDED:
        t0 = time.time()
        res, err = r.test_value(code, value)
        assert err and "PathologicalError" in err, (code, res, err)
        assert time.time() - t0 < 2.0, code


def test_empty_sources_not_probed_by_default():
    # the push failure from the screenshot: value.upper() on an empty Comments
    assert not r.sandbox("value.upper()", kind="text")["errors"]
    assert r.sandbox("value.upper()", kind="text", include_empty=True)["errors"]


def test_sandbox_reports_guard_hits():
    rep = r.sandbox("2 ** to_int(value, 0)", kind="number")
    assert rep["finished"] and rep["guard_hits"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok  " + name)
