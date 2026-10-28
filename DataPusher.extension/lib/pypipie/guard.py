# -*- coding: utf-8 -*-
"""Protection against pathological rules.

Three layers:
  1. analyze()      static lint of the rule's AST - 'block' findings refuse the rule,
                    'warn' findings are shown in the editor.
  2. Guarded code   every rule is compiled through GuardTransformer, so arithmetic,
                    string building, loops and method calls go through checked helpers
                    with size, iteration and time budgets. This works even when the rule
                    runs unattended during save/sync.
  3. sandbox_test() runs the rule against probe values on a background thread with a
                    timeout, before it can be saved.
"""
import ast
import math
import sys
import re
import time
import threading

# --------------------------------------------------------------------------
# limits
# --------------------------------------------------------------------------
MAX_SEQ = 1000000          # longest text / list a rule may build
MAX_INT_BITS = 4096        # biggest integer (about 1230 digits)
MAX_ITER = 100000          # loop / comprehension iterations per call
MAX_CALL_SECONDS = 0.5     # wall time per rule call
MAX_TOTAL_SECONDS = 15.0   # wall time per rule per push run
MAX_WIDTH = 10000          # padding / format widths
REGEX_TIMEOUT = 0.25       # seconds per regex call
MAX_LINES = 80
SANDBOX_TIMEOUT = 3.0


MAX_ALLOC = 20000000       # total characters/items a single call may create

try:
    _INT = (int, long)  # noqa: F821  (py2 / IronPython big ints)
except NameError:
    _INT = (int,)
_TEXT = (str, type(u""))


class PathologicalError(Exception):
    """Raised when a rule trips a runtime guard."""


# --------------------------------------------------------------------------
# small AST helpers (py2/IronPython and py3 compatible)
# --------------------------------------------------------------------------
_HAS_CONSTANT = hasattr(ast, "Constant")
_PY2 = sys.version_info[0] == 2


def _const_value(node):
    """Return (True, value) for literal numbers/strings, else (False, None)."""
    if _HAS_CONSTANT and isinstance(node, ast.Constant):
        return True, node.value
    if hasattr(ast, "Num") and type(node).__name__ == "Num":
        return True, node.n
    if hasattr(ast, "Str") and type(node).__name__ == "Str":
        return True, node.s
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        ok, v = _const_value(node.operand)
        if ok and isinstance(v, (int, float)):
            return True, -v
    return False, None


def _fold(node):
    """Constant-fold simple integer arithmetic. Huge results come back as float('inf')."""
    ok, v = _const_value(node)
    if ok:
        return ok, v
    if isinstance(node, ast.BinOp):
        lok, lv = _fold(node.left)
        rok, rv = _fold(node.right)
        if not (lok and rok) or not all(isinstance(x, (int, float)) for x in (lv, rv)):
            return False, None
        op = type(node.op).__name__
        try:
            if op == "Pow":
                if isinstance(lv, float) and math.isinf(lv) or isinstance(rv, float) and math.isinf(rv):
                    return True, float("inf")
                if rv > 0 and rv * max(1, abs(int(lv)).bit_length()) > 128:
                    return True, float("inf")
                return True, lv ** rv
            if op == "Mult":
                return True, lv * rv
            if op == "Add":
                return True, lv + rv
            if op == "Sub":
                return True, lv - rv
            if op == "LShift":
                return True, float("inf") if rv > 128 else int(lv) << int(rv)
        except Exception:
            return False, None
    return False, None


def _str_node(s):
    return ast.Constant(value=s) if _HAS_CONSTANT else ast.Str(s=s)


def _name(id_):
    return ast.Name(id=id_, ctx=ast.Load())


def _call(func, args, keywords=None, starargs=None, kwargs=None):
    node = ast.Call(func=func, args=list(args), keywords=list(keywords or []))
    if _PY2:  # Python 2 / IronPython 2.7 Call nodes carry starargs / kwargs
        node.starargs = starargs
        node.kwargs = kwargs
    return node


def _is_seq_literal(node):
    ok, v = _const_value(node)
    if ok and isinstance(v, (str, type(u""))):
        return True
    return isinstance(node, (ast.List, ast.Tuple))


def _bits(n):
    try:
        return abs(int(n)).bit_length()
    except Exception:
        return 0


_FMT_WIDTH_RE = re.compile(r"\{[^{}]*:[^{}]*\{|\{[^{}]*:[^{}]*?\d{5,}|%[-+ #0]*(\*|\d{5,})|%[-+ #0]*\d*\.(\*|\d{5,})")
_NESTED_QUANT_RE = re.compile(r"\((?:[^()\\]|\\.)*[+*}](?:[^()\\]|\\.)*\)\s*[+*{]")

_OPS = {"Pow": "pow", "Mult": "mul", "LShift": "lshift", "Add": "add", "Mod": "mod"}


# --------------------------------------------------------------------------
# 1. static analysis
# --------------------------------------------------------------------------
def analyze(nodes, code=u""):
    """Lint user nodes. Returns a list of (severity, line, message); severity 'block' or 'warn'."""
    out = []

    def add(sev, node, msg):
        out.append((sev, max(1, getattr(node, "lineno", 2) - 1), msg))

    lines = [l for l in (code or u"").splitlines() if l.strip()]
    if len(lines) > MAX_LINES:
        out.append(("warn", 1, u"Long rule ({} lines). Rules run once per element - keep them short.".format(
            len(lines))))

    lambda_names = set()
    for root in nodes:
        for node in ast.walk(root):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Lambda):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        lambda_names.add(t.id)

    def loop_depth(node, depth=0):
        if isinstance(node, ast.For):
            depth += 1
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            depth += len(node.generators)
        best = depth
        for child in ast.iter_child_nodes(node):
            best = max(best, loop_depth(child, depth))
        return best

    for root in nodes:
        if loop_depth(root) >= 2:
            add("warn", root, u"Nested loops multiply the work per element "
                              u"(limit: {:,} iterations per element).".format(MAX_ITER))
        for node in ast.walk(root):
            if isinstance(node, ast.BinOp):
                op = type(node.op).__name__
                lok, lv = _fold(node.left)
                rok, rv = _fold(node.right)
                if op == "Pow":
                    if isinstance(node.right, ast.BinOp) and isinstance(node.right.op, ast.Pow):
                        add("block", node, u"Power tower (a ** b ** c) - results explode in size.")
                    elif rok and rv == float("inf"):
                        add("block", node, u"Exponent is itself huge - result explodes in size.")
                    elif lok and rok and isinstance(lv, int) and isinstance(rv, int) and rv > 0 and \
                            rv * max(1, _bits(lv)) > MAX_INT_BITS:
                        add("block", node, u"{} ** {} is far too large to compute.".format(lv, rv))
                    elif not rok:
                        add("warn", node, u"Exponent comes from data - huge results are stopped at runtime.")
                elif op == "Mult":
                    for seq, other in ((node.left, node.right), (node.right, node.left)):
                        if _is_seq_literal(seq):
                            ok, n = _fold(other)
                            if ok and isinstance(n, (int, float)) and n > MAX_SEQ:
                                add("block", node, u"Repeating text/list that many times is too large.")
                            elif not ok:
                                add("warn", node, u"Repeating text/list by a data value - capped at "
                                                  u"{:,} items at runtime.".format(MAX_SEQ))
                elif op == "LShift":
                    if rok and isinstance(rv, int) and rv > MAX_INT_BITS:
                        add("block", node, u"Shift by {} bits is far too large.".format(rv))
            elif isinstance(node, ast.Call):
                fname = node.func.id if isinstance(node.func, ast.Name) else (
                    node.func.attr if isinstance(node.func, ast.Attribute) else None)
                if fname in ("range", "xrange"):
                    for a in node.args:
                        ok, v = _fold(a)
                        if ok and isinstance(v, (int, float)) and abs(v) > 10000:
                            add("block", node, u"range() is limited to 10,000 items in rules.")
                if fname in ("re_find", "re_test", "re_sub") and node.args:
                    ok, pat = _const_value(node.args[0])
                    if ok and isinstance(pat, (str, type(u""))) and _NESTED_QUANT_RE.search(pat):
                        add("warn", node, u"Regex has nested repetition like (a+)+ which can backtrack "
                                          u"badly; each regex call times out after {}s.".format(REGEX_TIMEOUT))
            elif isinstance(node, ast.AugAssign) and not isinstance(node.target, ast.Name) and \
                    type(node.op).__name__ in _OPS:
                add("block", node, u"Use 'x = x + ...' style for lists/dict items, "
                                   u"e.g. items[0] = items[0] + 1 (keeps the size guards working).")
            elif isinstance(node, ast.Lambda):
                params = set()
                for a in node.args.args:
                    params.add(getattr(a, "arg", None) or getattr(a, "id", None))
                for sub in ast.walk(node.body):
                    if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and \
                            (sub.func.id in lambda_names or sub.func.id in params):
                        add("block", node, u"A lambda that calls itself or a passed-in function can "
                                           u"recurse forever and crash Revit.")
                        break
            ok, v = _const_value(node) if not isinstance(node, (ast.BinOp, ast.Call)) else (False, None)
            if ok and isinstance(v, (str, type(u""))) and _FMT_WIDTH_RE.search(v):
                add("block", node, u"Format string with a huge or computed width/precision.")
    # de-duplicate
    seen, uniq = set(), []
    for f in out:
        if f not in seen:
            seen.add(f)
            uniq.append(f)
    return uniq


# --------------------------------------------------------------------------
# 2. runtime guards
# --------------------------------------------------------------------------
class GuardTransformer(ast.NodeTransformer):
    """Route risky operations through _g_* helpers. Only applied to user code."""

    def visit_BinOp(self, node):
        self.generic_visit(node)
        op = _OPS.get(type(node.op).__name__)
        if op is None:
            return node
        return ast.copy_location(_call(_name("_g_bin"), [_str_node(op), node.left, node.right]), node)

    def visit_AugAssign(self, node):
        self.generic_visit(node)
        op = _OPS.get(type(node.op).__name__)
        if op is None or not isinstance(node.target, ast.Name):
            return node
        value = _call(_name("_g_bin"), [_str_node(op), _name(node.target.id), node.value])
        new = ast.Assign(targets=[ast.Name(id=node.target.id, ctx=ast.Store())], value=value)
        return ast.copy_location(new, node)

    def visit_For(self, node):
        self.generic_visit(node)
        node.iter = ast.copy_location(_call(_name("_g_iter"), [node.iter]), node.iter)
        return node

    def visit_comprehension(self, node):
        self.generic_visit(node)
        node.iter = _call(_name("_g_iter"), [node.iter])
        return node

    def visit_Call(self, node):
        self.generic_visit(node)
        if isinstance(node.func, ast.Attribute):
            new = _call(_name("_g_meth"), [node.func.value, _str_node(node.func.attr)] + list(node.args),
                        node.keywords, getattr(node, "starargs", None), getattr(node, "kwargs", None))
            return ast.copy_location(new, node)
        return node


class Budget(object):
    def __init__(self):
        self.total = 0.0
        self.start = 0.0
        self.iters = 0
        self.alloc = 0

    def begin(self):
        if self.total > MAX_TOTAL_SECONDS:
            raise PathologicalError(u"rule used more than {:.0f}s in this run".format(MAX_TOTAL_SECONDS))
        self.start = time.time()
        self.iters = 0
        self.alloc = 0

    def grow(self, x):
        try:
            if isinstance(x, (_TEXT, list, tuple)):
                self.alloc += len(x)
        except Exception:
            return
        if self.alloc > MAX_ALLOC:
            raise PathologicalError(u"rule built more than {:,} characters/items".format(MAX_ALLOC))

    def end(self):
        self.total += time.time() - self.start
        if self.total > MAX_TOTAL_SECONDS:
            raise PathologicalError(u"rule used more than {:.0f}s in this run".format(MAX_TOTAL_SECONDS))

    def check(self):
        if time.time() - self.start > MAX_CALL_SECONDS:
            raise PathologicalError(u"rule took longer than {}s for one element".format(MAX_CALL_SECONDS))


def _too_long(x):
    try:
        return isinstance(x, (str, type(u""), list, tuple)) and len(x) > MAX_SEQ
    except Exception:
        return False


def make_guards(budget):
    """Guard functions bound to one budget, injected into the rule's globals."""

    def g_bin(op, a, b):
        budget.check()
        ints = isinstance(a, _INT) and isinstance(b, _INT)
        if op == "pow":
            if ints and b > 0 and b * max(1, _bits(a)) > MAX_INT_BITS:
                raise PathologicalError(u"{} ** {} is too large".format(a, b))
            return a ** b
        if op == "mul":
            if ints and _bits(a) + _bits(b) > MAX_INT_BITS:
                raise PathologicalError(u"integer product too large")
            for seq, n in ((a, b), (b, a)):
                if isinstance(n, _INT) and isinstance(seq, (_TEXT, list, tuple)):
                    if len(seq) * max(0, n) > MAX_SEQ:
                        raise PathologicalError(u"repeated text/list would exceed {:,} items".format(MAX_SEQ))
            r = a * b
            budget.grow(r)
            return r
        if op == "lshift":
            if ints and (b > MAX_INT_BITS or _bits(a) + b > MAX_INT_BITS):
                raise PathologicalError(u"shift too large")
            return a << b
        if op == "add":
            r = a + b
            if _too_long(r):
                raise PathologicalError(u"text/list grew beyond {:,} items".format(MAX_SEQ))
            budget.grow(r)
            return r
        if op == "mod":
            if isinstance(a, _TEXT) and _FMT_WIDTH_RE.search(a):
                raise PathologicalError(u"format width too large")
            r = a % b
            budget.grow(r)
            return r
        raise PathologicalError(u"unknown operator")

    def g_iter(it):
        for item in it:
            budget.iters += 1
            if budget.iters > MAX_ITER:
                raise PathologicalError(u"more than {:,} loop iterations".format(MAX_ITER))
            if budget.iters % 256 == 0:
                budget.check()
            yield item

    def g_meth(obj, name, *args, **kw):
        budget.check()
        if name in ("rjust", "ljust", "center", "zfill") and args:
            if isinstance(args[0], _INT) and args[0] > MAX_WIDTH:
                raise PathologicalError(u"{}() width over {:,}".format(name, MAX_WIDTH))
        elif name == "expandtabs" and args and isinstance(args[0], _INT) and args[0] > 100:
            raise PathologicalError(u"expandtabs() size too large")
        elif name == "format" and isinstance(obj, (str, type(u""))):
            if _FMT_WIDTH_RE.search(obj):
                raise PathologicalError(u"format width too large")
        elif name == "replace" and len(args) >= 2 and isinstance(obj, (str, type(u""))):
            old, new = args[0], args[1]
            count = obj.count(old) if old else len(obj) + 1
            if len(obj) + count * max(0, len(new) - len(old)) > MAX_SEQ:
                raise PathologicalError(u"replace() result too large")
        result = getattr(obj, name)(*args, **kw)
        if _too_long(result):
            raise PathologicalError(u"{}() result exceeds {:,} items".format(name, MAX_SEQ))
        budget.grow(result)
        return result

    def g_pow(a, b, mod=None):
        if mod is not None:
            return pow(a, b, mod)
        return g_bin("pow", a, b)

    return {"_g_bin": g_bin, "_g_iter": g_iter, "_g_meth": g_meth, "pow": g_pow}


def guarded(fn, budget):
    """Wrap a compiled rule so each call gets a fresh per-call budget."""
    def run(*args):
        budget.begin()
        try:
            return fn(*args)
        finally:
            budget.end()
    run.budget = budget
    return run


# --------------------------------------------------------------------------
# regex with a hard timeout (.NET Regex under IronPython, plain re elsewhere)
# --------------------------------------------------------------------------
try:
    import clr  # noqa: F401
    from System import TimeSpan
    from System.Text.RegularExpressions import Regex, RegexOptions, RegexMatchTimeoutException
    _NET = True
except Exception:
    _NET = False


def _to_net_pattern(p):
    p = re.sub(r"\(\?P<", "(?<", p)
    return re.sub(r"\(\?P=(\w+)\)", r"\\k<\1>", p)


def _net_regex(pattern):
    return Regex(_to_net_pattern(pattern), getattr(RegexOptions, "None"), TimeSpan.FromSeconds(REGEX_TIMEOUT))


def regex_search(pattern, text, group=0):
    """Returns the group text, or None. Raises PathologicalError on timeout."""
    if _NET:
        try:
            m = _net_regex(pattern).Match(text)
        except RegexMatchTimeoutException:
            raise PathologicalError(u"regex took longer than {}s".format(REGEX_TIMEOUT))
        if not m.Success:
            return None
        g = m.Groups[group] if isinstance(group, int) else m.Groups[str(group)]
        return g.Value if g.Success else None
    m = re.search(pattern, text)
    if not m:
        return None
    return m.group(group)


def regex_sub(pattern, repl, text):
    if _NET:
        try:
            net_repl = re.sub(r"\\(\d)", r"$\1", repl)
            return _net_regex(pattern).Replace(text, net_repl)
        except RegexMatchTimeoutException:
            raise PathologicalError(u"regex took longer than {}s".format(REGEX_TIMEOUT))
    return re.sub(pattern, repl, text)


# --------------------------------------------------------------------------
# 3. sandbox test
# --------------------------------------------------------------------------
PROBES = {
    "number": [None, 0.0, 1.0, -1.0, 2.5, 0.000001, 1000000.0, -1000000.0, 1e15],
    "integer": [None, 0, 1, -1, 7, 1000000, -1000000],
    "bool": [None, True, False],
    "text": [None, u"", u"abc", u"A-101", u"Level 3", u"123", u"  padded  ", u"x" * 2000],
}


def probe_kind(storage, yesno=False):
    if storage == "Double":
        return "number"
    if storage == "Integer":
        return "bool" if yesno else "integer"
    return "text"


def sandbox_test(compile_fn, code, samples=(), timeout=SANDBOX_TIMEOUT, kind="text", include_empty=True):
    """Run the rule on probe values in a background thread.

    compile_fn(code) must return a guarded callable. Returns a dict:
      finished, elapsed, rows [(input, target, status, result_or_message, ms)],
      guard_hits, errors
    """
    fn = compile_fn(code)
    base = PROBES.get(kind, PROBES["text"])
    probes = list(samples) + [p for p in base if p not in samples]
    if not include_empty:  # the rule never sees empty sources, so don't probe them
        probes = [p for p in probes if p is not None and p != u""]
    state = {"rows": [], "done": False}
    dummy = lambda name: None  # noqa: E731
    info = {"id": None, "name": u"", "category": u""}

    def work():
        for target in (None, u"existing"):
            for p in probes:
                t0 = time.time()
                try:
                    res = fn(p, p if isinstance(p, (str, type(u""))) else (u"" if p is None else u"%s" % p),
                             target, dummy, dummy, info, info)
                    state["rows"].append((p, target, "ok", res, (time.time() - t0) * 1000.0))
                except PathologicalError as ex:
                    state["rows"].append((p, target, "guard", u"%s" % ex, (time.time() - t0) * 1000.0))
                except Exception as ex:
                    state["rows"].append((p, target, "error", u"{}: {}".format(type(ex).__name__, ex),
                                          (time.time() - t0) * 1000.0))
        state["done"] = True

    t = threading.Thread(target=work)
    t.daemon = True
    start = time.time()
    t.start()
    t.join(timeout)
    rows = list(state["rows"])
    return {
        "finished": state["done"],
        "elapsed": time.time() - start,
        "rows": rows,
        "guard_hits": [r for r in rows if r[2] == "guard"],
        "errors": [r for r in rows if r[2] == "error"],
        "slowest_ms": max([r[4] for r in rows] or [0]),
    }
