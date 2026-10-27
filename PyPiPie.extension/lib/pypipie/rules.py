# -*- coding: utf-8 -*-
"""Mapping rules: small Python snippets that transform the incoming value.

A rule is either a single expression            value * 1.1
or a short script that sets / returns `value`  if not value:
                                                    value = "N/A"

Variables available inside a rule
    value    incoming source value (text / number in display units / True-False / element name / None)
    text     source value as displayed in Revit
    target   current value of the target parameter (same conventions)
    a(name)  read another parameter of the A (source) element by name (instance, then type)
    b(name)  read another parameter of the B (target) element by name
    a_info / b_info   dict: id, name, category

Return SKIP to leave the target untouched; return None (or '') for "empty".

Rules run in a restricted sandbox: no imports, no file/system access, no double-underscore
or .NET (PascalCase) attributes, no while-loops, and only primitive values are passed in.
That keeps rules safe to run automatically on save/sync, even when they arrive in a
mapping file or project from someone else.
"""
import ast
import math
import re

from pypipie import guard

# --------------------------------------------------------------------------
# sentinel + helper library exposed to rules
# --------------------------------------------------------------------------


class _Skip(object):
    def __repr__(self):
        return "SKIP"

    def __nonzero__(self):  # py2 / IronPython
        return False
    __bool__ = __nonzero__


SKIP = _Skip()
MAX_RANGE = 10000


def _s(v):
    """None-safe text."""
    if v is None:
        return u""
    if isinstance(v, bool):
        return u"Yes" if v else u"No"
    if isinstance(v, float):
        return fmt(v, 6)
    try:
        return unicode(v)  # noqa: F821  (IronPython / py2)
    except NameError:
        return str(v)


def fmt(v, decimals=2):
    """Number to text without trailing zeros: fmt(3.5000) -> '3.5'."""
    if v is None or v == "":
        return u""
    try:
        f = float(v)
    except Exception:
        return _s(v)
    out = (u"%." + str(int(decimals)) + u"f") % f
    if "." in out:
        out = out.rstrip(u"0").rstrip(u".")
    return u"0" if out in (u"-0", u"") else out


_NUM_RE = re.compile(r"[-+]?\d[\d,]*\.?\d*(?:[eE][-+]?\d+)?|[-+]?\.\d+")


def num(v, default=None):
    """First number found in v: num('Level 3') -> 3.0, num('1,250 SF') -> 1250.0."""
    if v is None:
        return default
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    m = _NUM_RE.search(_s(v))
    if not m:
        return default
    try:
        return float(m.group(0).replace(",", ""))
    except Exception:
        return default


def to_int(v, default=None):
    n = num(v)
    return default if n is None else int(round(n))


def as_bool(v):
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    if isinstance(v, (int, float)):
        return v != 0
    return _s(v).strip().lower() in ("yes", "y", "true", "t", "1", "on", "x", u"✓")


def switch(v, cases, default=None, ignore_case=True):
    """switch(value, {"A": "Alpha", "B": "Bravo"}, default=value)"""
    if v in cases:
        return cases[v]
    if ignore_case:
        key = _s(v).strip().lower()
        for k, out in cases.items():
            if _s(k).strip().lower() == key:
                return out
    return default


def when(*args):
    """when(cond1, result1, cond2, result2, ..., default)  - an if/elif/else chain in one line."""
    n = len(args)
    for i in range(0, n - 1, 2):
        if args[i]:
            return args[i + 1]
    return args[-1] if n % 2 == 1 else None


def iff(cond, yes, no=None):
    return yes if cond else no


def between(v, lo, hi):
    try:
        return lo <= v <= hi
    except Exception:
        return False


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def round_to(v, step=1.0):
    return round(float(v) / step) * step if step else v


def floor_to(v, step=1.0):
    return math.floor(float(v) / step) * step if step else v


def ceil_to(v, step=1.0):
    return math.ceil(float(v) / step) * step if step else v


def pad(v, width, char="0"):
    """pad(7, 3) -> '007'"""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    width = int(width)
    if width > guard.MAX_WIDTH:
        raise guard.PathologicalError(u"pad() width over {:,}".format(guard.MAX_WIDTH))
    return _s(v).rjust(width, char[:1] or "0")


def join(sep, *items):
    """join(' - ', a, b, c) skipping empty items."""
    return _s(sep).join(_s(i) for i in items if i not in (None, "") and i is not SKIP)


def contains(textv, sub, ignore_case=True):
    t, s = _s(textv), _s(sub)
    return s.lower() in t.lower() if ignore_case else s in t


def re_find(pattern, textv, group=0, default=None):
    """Regex search with a hard timeout (see guard.REGEX_TIMEOUT)."""
    try:
        hit = guard.regex_search(pattern, _s(textv), group)
    except guard.PathologicalError:
        raise
    except Exception:
        return default
    return default if hit is None else hit


def re_test(pattern, textv):
    return guard.regex_search(pattern, _s(textv), 0) is not None


def re_sub(pattern, repl, textv):
    return guard.regex_sub(pattern, repl, _s(textv))


def _safe_range(*args):
    r = range(*args)
    if len(r) > MAX_RANGE:
        raise guard.PathologicalError("range() limited to {} items in rules".format(MAX_RANGE))
    return r


HELPERS = {
    "SKIP": SKIP, "fmt": fmt, "num": num, "to_int": to_int, "as_bool": as_bool,
    "switch": switch, "when": when, "iff": iff, "between": between, "clamp": clamp,
    "round_to": round_to, "floor_to": floor_to, "ceil_to": ceil_to, "pad": pad,
    "join": join, "contains": contains, "re_find": re_find, "re_test": re_test,
    "re_sub": re_sub, "text_of": _s,
    "floor": math.floor, "ceil": math.ceil, "sqrt": math.sqrt, "pi": math.pi,
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "radians": math.radians,
    "degrees": math.degrees, "log": math.log, "log10": math.log10, "hypot": math.hypot,
}

_SAFE_BUILTIN_NAMES = (
    "abs", "all", "any", "bool", "dict", "enumerate", "filter", "float", "int", "isinstance",
    "len", "list", "map", "max", "min", "pow", "reversed", "round", "set", "sorted", "str",
    "sum", "tuple", "zip", "unicode", "True", "False", "None",
)

try:
    import __builtin__ as _bi  # py2 / IronPython
except ImportError:
    import builtins as _bi

SAFE_BUILTINS = dict((n, getattr(_bi, n)) for n in _SAFE_BUILTIN_NAMES if hasattr(_bi, n))
SAFE_BUILTINS["range"] = _safe_range
SAFE_BUILTINS["xrange"] = _safe_range
if "unicode" not in SAFE_BUILTINS:
    SAFE_BUILTINS["unicode"] = str

# --------------------------------------------------------------------------
# sandbox check
# --------------------------------------------------------------------------
_FORBIDDEN_NODES = tuple(t for t in (getattr(ast, n, None) for n in (
    "Import", "ImportFrom", "Global", "Nonlocal", "While", "ClassDef", "FunctionDef",
    "AsyncFunctionDef", "AsyncFor", "AsyncWith", "Await", "Yield", "YieldFrom", "Exec",
    "With", "Try", "TryExcept", "TryFinally", "Raise", "Delete")) if t is not None)

_FORBIDDEN_NAMES = set([
    "open", "file", "exec", "eval", "execfile", "compile", "__import__", "getattr", "setattr",
    "delattr", "hasattr", "globals", "locals", "vars", "dir", "type", "object", "input",
    "raw_input", "reload", "help", "breakpoint", "memoryview", "super", "classmethod",
    "staticmethod", "property", "id", "callable", "clr", "System", "Autodesk",
])


def _allowed_attrs():
    names = set()
    types = [str, list, dict, int, float, set, tuple, bool]
    try:
        types.append(unicode)  # noqa: F821
    except NameError:
        pass
    for t in types:
        for n in dir(t):
            if n[:1].islower() and not n.startswith("_"):
                names.add(n)
    names.discard("mro")
    return names


ALLOWED_ATTRS = _allowed_attrs()


class RuleError(Exception):
    pass


def _check_nodes(nodes):
    for root in nodes:
        for node in ast.walk(root):
            if _FORBIDDEN_NODES and isinstance(node, _FORBIDDEN_NODES):
                raise RuleError(u"'{}' is not allowed in rules (line {}).".format(
                    type(node).__name__, max(1, getattr(node, "lineno", 2) - 1)))
            if isinstance(node, ast.Name):
                if node.id.startswith("_") or node.id in _FORBIDDEN_NAMES:
                    raise RuleError(u"Name '{}' is not allowed in rules (line {}).".format(
                        node.id, max(1, node.lineno - 1)))
            elif isinstance(node, ast.Attribute):
                if node.attr not in ALLOWED_ATTRS:
                    raise RuleError(u"Attribute '.{}' is not allowed in rules (line {}). "
                                    u"Only text/number/list methods can be used.".format(
                                        node.attr, max(1, node.lineno - 1)))


def _parse(code):
    src = _wrap(code)
    try:
        tree = ast.parse(src)
    except SyntaxError as ex:
        raise RuleError(u"Syntax error on line {}: {}".format(max(1, (ex.lineno or 2) - 1), ex.msg))
    return src, tree


def check(code):
    """Raise RuleError if the code is invalid, outside the sandbox, or certainly pathological.
    Returns the list of non-blocking warnings [(line, message)]."""
    src, tree = _parse(code)
    user = tree.body[0].body  # only the user's code, not the wrapper
    _check_nodes(user)
    findings = guard.analyze(user, code)
    for sev, line, msg in findings:
        if sev == "block":
            raise RuleError(u"Line {}: {}".format(line, msg))
    return [(line, msg) for sev, line, msg in findings if sev == "warn"]


def lint(code):
    """Warnings only (never raises). [(line, message)]"""
    try:
        return check(code)
    except RuleError:
        return []


ARGS = ("value", "text", "target", "a", "b", "a_info", "b_info")


def _is_expression(code):
    try:
        ast.parse(code, mode="eval")
        return True
    except SyntaxError:
        return False


def _wrap(code):
    """Wrap user code in `def __rule__(...)`; expressions become `return (expr)`."""
    code = (code or "").replace("\t", "    ").rstrip()
    lines = code.splitlines()
    ind = min([len(l) - len(l.lstrip()) for l in lines if l.strip()] or [0])
    lines = [l[ind:] for l in lines]  # tolerate pasted, indented snippets
    code = u"\n".join(lines).strip("\n")
    if _is_expression(code.strip()):
        body = u"    return (" + code.strip() + u")\n"
    else:
        body = u"".join(u"    " + l + u"\n" for l in lines) + u"    return value\n"
    return u"def __rule__({}):\n{}".format(", ".join(ARGS), body)


def compile_rule(code):
    """Compile rule text into a callable f(value, text, target, a, b, a_info, b_info)."""
    if not (code or "").strip():
        return None
    check(code)
    src, tree = _parse(code)
    func = tree.body[0]
    func.body = [guard.GuardTransformer().visit(n) for n in func.body]
    ast.fix_missing_locations(tree)
    budget = guard.Budget()
    builtins = dict(SAFE_BUILTINS)
    g = {"__builtins__": builtins}
    g.update(HELPERS)
    guards = guard.make_guards(budget)
    builtins["pow"] = guards.pop("pow")
    g.update(guards)
    try:
        exec(compile(tree, "<rule>", "exec"), g)
    except SyntaxError as ex:
        raise RuleError(u"Syntax error: {}".format(ex.msg))
    return guard.guarded(g["__rule__"], budget)


class RuleCache(object):
    """Compile each distinct rule once per push run."""

    def __init__(self):
        self._c = {}

    def get(self, code):
        if code not in self._c:
            try:
                self._c[code] = (compile_rule(code), None)
            except RuleError as ex:
                self._c[code] = (None, ex)
            except Exception as ex:
                self._c[code] = (None, RuleError(_s(ex)))
        return self._c[code]


# --------------------------------------------------------------------------
# templates shown in the editor
# --------------------------------------------------------------------------
TEMPLATES = [
    ("Switch / case", u'''# Map incoming values to new ones (case-insensitive)
value = switch(value, {
    "A": "Alpha",
    "B": "Bravo",
}, default=value)'''),
    ("If / then / else", u'''if value is None or value == "":
    value = "N/A"
elif contains(value, "temp"):
    value = "TEMPORARY"
else:
    value = value.upper()'''),
    ("One-line if/elif (when)", u'''when(value < 100, "Small", value < 500, "Medium", "Large")'''),
    ("Math", u'''# Numbers are in project display units (ft, m, SF ...)
value * 1.10 + 2'''),
    ("Round to step", u'''round_to(value, 0.5)'''),
    ("Prefix / suffix", u'''"RM-{}".format(value)'''),
    ("Zero-pad number", u'''pad(to_int(value), 3)'''),
    ("Combine parameters", u'''join(" - ", a("Number"), a("Name"))'''),
    ("Extract with regex", u'''# First run of digits in the source text
re_find(r"(\\d+)", text, 1)'''),
    ("Text -> Yes/No", u'''as_bool(value) or contains(value, "required")'''),
    ("Don't overwrite", u'''# Leave targets that already have a value alone
if target not in (None, ""):
    return SKIP
return value'''),
    ("Number from text", u'''num(value, default=0)'''),
]

REFERENCE = u"""VARIABLES
value     incoming value (text, number in display units,
          True/False for Yes/No, element name, or None)
text      source as displayed in Revit
target    current target value
a("P")    other parameter on the A element
b("P")    other parameter on the B element
a_info / b_info   {'id', 'name', 'category'}

RESULT
Set or return value. Return SKIP to leave the
target untouched. None or '' = empty.

HELPERS
switch(v, {k: out}, default)
when(c1, r1, c2, r2, ..., default)
iff(cond, yes, no)    between(v, lo, hi)
num(v, default)       to_int(v)
as_bool(v)            fmt(v, decimals)
round_to / floor_to / ceil_to(v, step)
clamp(v, lo, hi)      pad(v, width, '0')
join(sep, *items)     contains(t, sub)
re_find(pat, t, group)  re_test(pat, t)
re_sub(pat, repl, t)  text_of(v)
floor ceil sqrt pi sin cos tan radians
degrees log log10 hypot  + abs min max
round len sum sorted str int float ...

Text methods work: value.upper(),
.strip(), .replace(a, b), .format(...)

NOT ALLOWED
import, while, def/class, try, open, eval,
_private and .NET (Capitalised) attributes,
self-calling lambdas, a ** b ** c towers.

SAFETY LIMITS (per element)
100,000 loop iterations  0.5 s run time
text/lists up to 1,000,000 items
integers up to ~1,200 digits
regex calls time out after 0.25 s
15 s total per rule per push
Over a limit -> that element is reported
as a rule error; the save carries on.
"""


# --------------------------------------------------------------------------
# Revit value adapters (imported lazily so the sandbox above is testable alone)
# --------------------------------------------------------------------------
def read_friendly(units, param):
    """Parameter -> plain Python value used inside rules."""
    from Autodesk.Revit.DB import StorageType
    from pypipie import revitutil as ru
    from pypipie import convert as cv
    if param is None or cv.is_empty(param):
        return None
    st = param.StorageType
    try:
        spec = param.Definition.GetDataType().TypeId
    except Exception:
        spec = ""
    if st == StorageType.String:
        return param.AsString() or u""
    if st == StorageType.Integer:
        v = param.AsInteger()
        return bool(v) if ru.is_yesno(spec) else v
    if st == StorageType.Double:
        return float(units.to_display(param.AsDouble(), spec))
    if st == StorageType.ElementId:
        e = units.doc.GetElement(param.AsElementId())
        return ru.element_name(e) if e is not None else None
    return None


def to_target(units, result, dst_p, dst_ref):
    """Rule result -> ('ok'|'empty'|'skip'|'fail', raw value for dst_p)."""
    from Autodesk.Revit.DB import ElementId, StorageType
    from pypipie import revitutil as ru
    from pypipie import convert as cv
    if result is SKIP:
        return "skip", None
    if result is None or (isinstance(result, (str, type(u""))) and result == u""):
        return "empty", None
    D = dst_p.StorageType
    spec = dst_ref.get("spec", "")
    try:
        if D == StorageType.String:
            return "ok", _s(result)
        if D == StorageType.Integer:
            if ru.is_yesno(spec):
                return "ok", 1 if as_bool(result) else 0
            if isinstance(result, bool):
                return "ok", int(result)
            n = num(result)
            return ("ok", int(round(n))) if n is not None else ("fail", None)
        if D == StorageType.Double:
            if isinstance(result, (bool, int, float)):
                return "ok", float(units.to_internal(float(result), spec))
            v = units.parse(_s(result), spec)
            return ("ok", v) if v is not None else ("fail", None)
        if D == StorageType.ElementId:
            if isinstance(result, ElementId):
                return "ok", result
            if isinstance(result, int) and not isinstance(result, bool):
                return "ok", ElementId(result)
            cur = units.doc.GetElement(dst_p.AsElementId())
            cls = cur.GetType() if cur is not None else None
            if cls is None and "material" in spec.lower():
                import clr
                from Autodesk.Revit.DB import Material
                cls = clr.GetClrType(Material)
            if cls is None:
                return "fail", None
            hit = units.element_by_name(cls, _s(result))
            return ("ok", hit) if hit is not None else ("fail", None)
    except Exception:
        return "fail", None
    return "fail", None


def _reader(units, doc, el):
    """a(name) / b(name): read a parameter by name from an element, then its type."""
    from pypipie import revitutil as ru
    cache = {}

    def read(name):
        if name in cache:
            return cache[name]
        val = None
        if el is not None:
            p = el.LookupParameter(name)
            if p is None:
                t = ru.element_type(doc, el)
                p = t.LookupParameter(name) if t is not None else None
            val = read_friendly(units, p)
        cache[name] = val
        return val
    return read


def _info(el):
    from pypipie import revitutil as ru
    if el is None:
        return {"id": None, "name": u"", "category": u""}
    try:
        cat = el.Category.Name if el.Category is not None else u""
    except Exception:
        cat = u""
    return {"id": ru.eid_val(el.Id), "name": ru.element_name(el), "category": cat}


def evaluate(fn, units, a_el, b_el, sp, dp, dst_ref):
    """Run a compiled rule for one link. Returns (status, raw_for_dst, friendly_result).

    status: ok | empty | skip | fail | error  (error -> friendly_result holds the message)
    """
    from pypipie import revitutil as ru
    doc = units.doc
    value = read_friendly(units, sp)
    text = ru.as_text(doc, sp) if sp is not None else u""
    target = read_friendly(units, dp)
    try:
        result = fn(value, text, target, _reader(units, doc, a_el), _reader(units, doc, b_el),
                    _info(a_el), _info(b_el))
    except Exception as ex:
        return "error", None, u"{}: {}".format(type(ex).__name__, ex)
    status, raw = to_target(units, result, dp, dst_ref)
    return status, raw, result


def preview(doc, mapping, pair, code, limit=12):
    """Dry-run a rule against the first few linked elements. Returns list of row dicts."""
    from pypipie import revitutil as ru
    from pypipie import convert as cv
    from pypipie import relations
    fn = compile_rule(code)  # raises RuleError
    units = cv.Units(doc)
    stats = {"unmatched": 0, "ambiguous": 0, "errors": []}
    a_elems = ru.collect_instances(doc, mapping["cat_a"])
    b_elems = a_elems if mapping["cat_a"] == mapping["cat_b"] else ru.collect_instances(doc, mapping["cat_b"])
    links = relations.build_pairs(doc, mapping, a_elems, b_elems, stats)
    rows = []
    src_ref, dst_ref = pair["src"], pair["dst"]
    for a_el, b_el in links:
        if len(rows) >= limit:
            break
        sh = ru.element_type(doc, a_el) if src_ref.get("type") else a_el
        dh = ru.element_type(doc, b_el) if dst_ref.get("type") else b_el
        sp = ru.find_param(sh, src_ref) if sh is not None else None
        dp = ru.find_param(dh, dst_ref) if dh is not None else None
        row = {"a": ru.element_name(a_el), "b": ru.element_name(b_el),
               "in": read_friendly(units, sp), "out": None, "status": "fail"}
        if dp is None:
            row["status"], row["out"] = "error", u"target parameter missing"
        elif fn is None:
            row["status"], row["out"] = "ok", row["in"]
        else:
            status, raw, res = evaluate(fn, units, a_el, b_el, sp, dp, dst_ref)
            row["status"], row["out"] = status, res
        rows.append(row)
    return rows, len(links)


def test_value(code, value, target=None):
    """Run a rule on a typed value (no model access). Returns (result, error)."""
    fn = compile_rule(code)
    if fn is None:
        return value, None
    try:
        return fn(value, _s(value), target, lambda n: None, lambda n: None,
                  {"id": None, "name": u"", "category": u""},
                  {"id": None, "name": u"", "category": u""}), None
    except Exception as ex:
        return None, u"{}: {}".format(type(ex).__name__, ex)


def sandbox(code, samples=(), kind="text"):
    """Stress-run a rule on probe values in a background thread (see guard.sandbox_test).
    kind: 'number' | 'integer' | 'bool' | 'text' - what the source parameter delivers."""
    return guard.sandbox_test(compile_rule, code, samples, kind=kind)


def describe(result):
    """Short display of a rule result with its kind."""
    if result is SKIP:
        return u"SKIP (target left as is)"
    if result is None:
        return u"(empty)"
    if isinstance(result, bool):
        return u"{}  · yes/no".format("Yes" if result else "No")
    if isinstance(result, (int, float)):
        return u"{}  · number".format(fmt(result, 6))
    return u"“{}”  · text".format(_s(result))
