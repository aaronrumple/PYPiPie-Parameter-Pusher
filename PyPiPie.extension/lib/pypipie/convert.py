# -*- coding: utf-8 -*-
"""Data-type compatibility and value conversion between Revit parameters.

Compatibility levels (from best to worst):
    exact         same storage and data type - raw internal value is copied
    convert       safe conversion (number -> text, unit-aware number <-> Number)
    lossy         may lose information or fail for some values
                  (text -> number parsing, rounding, Yes/No coercion, name lookup)
    incompatible  not allowed (e.g. Length -> Area, Element -> Number)
"""
import clr
import System

from Autodesk.Revit.DB import (
    ElementId, FilteredElementCollector, ForgeTypeId, Material,
    StorageType, UnitFormatUtils, UnitUtils
)

from pypipie import revitutil as ru

EXACT, CONVERT, LOSSY, INCOMPATIBLE = "exact", "convert", "lossy", "incompatible"
LEVEL_ORDER = {EXACT: 0, CONVERT: 1, LOSSY: 2, INCOMPATIBLE: 3}

LEVEL_LABEL = {
    EXACT: u"✓ exact",
    CONVERT: u"↻ converts",
    LOSSY: u"⚠ lossy",
    INCOMPATIBLE: u"✕ incompatible",
}

TRUE_WORDS = set(["yes", "y", "true", "t", "1", "on", "x", u"✓"])
FALSE_WORDS = set(["no", "n", "false", "f", "0", "off", ""])


# --------------------------------------------------------------------------
# Compatibility (works on refs only - used by the UI)
# --------------------------------------------------------------------------
def classify(src, dst):
    """Return (level, reason) for pushing ref `src` into ref `dst`."""
    S, D = src.get("storage"), dst.get("storage")
    s, d = ru.spec_base(src.get("spec")), ru.spec_base(dst.get("spec"))
    s_lbl = ru.spec_label(src.get("spec"), S)
    d_lbl = ru.spec_label(dst.get("spec"), D)

    if dst.get("ro"):
        return INCOMPATIBLE, "Target parameter is read-only"
    if S not in ("String", "Integer", "Double", "ElementId") or \
       D not in ("String", "Integer", "Double", "ElementId"):
        return INCOMPATIBLE, "Unsupported storage type"

    if S == D and (s == d or (S == "String" and s in ru.SPEC_TEXT and d in ru.SPEC_TEXT)):
        return EXACT, "Same data type ({})".format(d_lbl)

    if D == "String":
        if S == "ElementId":
            return CONVERT, "Element name written as text"
        return CONVERT, "{} written as formatted text".format(s_lbl)

    if S == "String":
        if D == "Double":
            return LOSSY, "Text parsed as {} (values that don't parse are skipped)".format(d_lbl)
        if D == "Integer":
            if ru.is_yesno(d):
                return LOSSY, "Text read as Yes/No (yes/no, true/false, 1/0)"
            return LOSSY, "Text parsed as whole number"
        if D == "ElementId":
            return LOSSY, "Text matched to an element by name"

    if S == "Double" and D == "Double":
        if ru.is_number(s) or ru.is_number(d):
            return CONVERT, "{} -> {} using project display units".format(s_lbl, d_lbl)
        return INCOMPATIBLE, "Different units: {} vs {}".format(s_lbl, d_lbl)

    if S == "Integer" and D == "Integer":
        if ru.is_yesno(s) or ru.is_yesno(d):
            return LOSSY, "Integer <-> Yes/No (non-zero = Yes)"
        return EXACT, "Integer"

    if S == "Integer" and D == "Double":
        if ru.is_yesno(s):
            return LOSSY, "Yes/No written as 1 / 0"
        return CONVERT, "Integer -> {} (display units)".format(d_lbl)

    if S == "Double" and D == "Integer":
        if ru.is_yesno(d):
            return LOSSY, "Non-zero -> Yes"
        return LOSSY, "{} rounded to whole number (display units)".format(s_lbl)

    if S == "ElementId" and D == "ElementId":
        return INCOMPATIBLE, "Different element types ({} vs {})".format(s_lbl, d_lbl)

    return INCOMPATIBLE, "{} cannot be written to {}".format(s_lbl, d_lbl)


def rule_can_fix(src, dst):
    """An incompatible pair can still be used when a rule produces the target value."""
    ok = ("String", "Integer", "Double", "ElementId")
    return (not dst.get("ro")) and src.get("storage") in ok and dst.get("storage") in ok


RULE_LABEL = u"\u0192 rule"


# --------------------------------------------------------------------------
# Runtime conversion helpers
# --------------------------------------------------------------------------
class Units(object):
    """Per-run cache of project units and name lookups."""

    def __init__(self, doc):
        self.doc = doc
        self.units = doc.GetUnits()
        self._unit_of = {}
        self._names = {}

    def unit_for(self, spec):
        if spec not in self._unit_of:
            u = None
            if ru.is_measurable(spec):
                try:
                    u = self.units.GetFormatOptions(ForgeTypeId(spec)).GetUnitTypeId()
                except Exception:
                    u = None
            self._unit_of[spec] = u
        return self._unit_of[spec]

    def to_display(self, value, spec):
        u = self.unit_for(spec)
        return UnitUtils.ConvertFromInternalUnits(value, u) if u is not None else value

    def to_internal(self, value, spec):
        u = self.unit_for(spec)
        return UnitUtils.ConvertToInternalUnits(value, u) if u is not None else value

    def parse(self, text, spec):
        """Parse user text ("10' 6\"", "3.5 m2", "12") into an internal double."""
        text = (text or "").strip()
        if not text:
            return None
        if spec:
            try:
                ref = clr.Reference[System.Double]()
                if UnitFormatUtils.TryParse(self.units, ForgeTypeId(spec), text, ref):
                    return float(ref.Value)
            except Exception:
                pass
        try:
            return self.to_internal(float(text.replace(",", "")), spec)
        except Exception:
            return None

    def element_by_name(self, cls, name):
        key = (str(cls), name.strip().lower())
        if key not in self._names:
            hit = None
            try:
                for e in FilteredElementCollector(self.doc).OfClass(cls):
                    if ru.element_name(e).strip().lower() == key[1]:
                        hit = e.Id
                        break
            except Exception:
                hit = None
            self._names[key] = hit
        return self._names[key]


def is_empty(param):
    if param is None:
        return True
    try:
        if not param.HasValue:
            return True
    except Exception:
        pass
    if param.StorageType == StorageType.String:
        return not (param.AsString() or "")
    if param.StorageType == StorageType.ElementId:
        return not ru.is_valid_id(param.AsElementId())
    return False


def raw_value(param):
    st = param.StorageType
    if st == StorageType.String:
        return param.AsString() or ""
    if st == StorageType.Integer:
        return param.AsInteger()
    if st == StorageType.Double:
        return param.AsDouble()
    if st == StorageType.ElementId:
        return param.AsElementId()
    return None


def values_equal(a, b):
    if isinstance(a, float) or isinstance(b, float):
        try:
            return abs(float(a) - float(b)) < 1e-9
        except Exception:
            return False
    if isinstance(a, ElementId) and isinstance(b, ElementId):
        return ru.eid_val(a) == ru.eid_val(b)
    return a == b


def _to_bool(text):
    t = (text or "").strip().lower()
    if t in TRUE_WORDS:
        return 1
    if t in FALSE_WORDS:
        return 0
    try:
        return 1 if float(t) != 0 else 0
    except Exception:
        return None


def convert(units, src_p, src_ref, dst_p, dst_ref):
    """Convert the value of src_p into a raw value suitable for dst_p.

    Returns (status, value) where status is 'ok', 'empty' or 'fail'.
    """
    doc = units.doc
    S, D = src_p.StorageType, dst_p.StorageType
    s_spec, d_spec = src_ref.get("spec", ""), dst_ref.get("spec", "")

    if is_empty(src_p):
        return "empty", None

    # ---- to text ---------------------------------------------------------
    if D == StorageType.String:
        if S == StorageType.String:
            return "ok", src_p.AsString() or ""
        return "ok", ru.as_text(doc, src_p)

    # ---- from text -------------------------------------------------------
    if S == StorageType.String:
        text = src_p.AsString() or ""
        if D == StorageType.Double:
            v = units.parse(text, d_spec)
            return ("ok", v) if v is not None else ("fail", None)
        if D == StorageType.Integer:
            if ru.is_yesno(d_spec):
                b = _to_bool(text)
                return ("ok", b) if b is not None else ("fail", None)
            try:
                return "ok", int(round(float(text.strip().replace(",", ""))))
            except Exception:
                return "fail", None
        if D == StorageType.ElementId:
            cur = doc.GetElement(dst_p.AsElementId())
            cls = cur.GetType() if cur is not None else None
            if cls is None and "material" in d_spec.lower():
                cls = clr.GetClrType(Material)
            if cls is None:
                return "fail", None
            hit = units.element_by_name(cls, text)
            return ("ok", hit) if hit is not None else ("fail", None)

    # ---- numeric ---------------------------------------------------------
    if S == StorageType.Double and D == StorageType.Double:
        if ru.spec_base(s_spec) == ru.spec_base(d_spec):
            return "ok", src_p.AsDouble()
        disp = units.to_display(src_p.AsDouble(), s_spec)
        return "ok", float(units.to_internal(disp, d_spec))

    if S == StorageType.Integer and D == StorageType.Integer:
        v = src_p.AsInteger()
        if ru.is_yesno(d_spec):
            return "ok", 1 if v else 0
        return "ok", v

    if S == StorageType.Integer and D == StorageType.Double:
        return "ok", float(units.to_internal(float(src_p.AsInteger()), d_spec))

    if S == StorageType.Double and D == StorageType.Integer:
        disp = units.to_display(src_p.AsDouble(), s_spec)
        if ru.is_yesno(d_spec):
            return "ok", 1 if abs(disp) > 1e-9 else 0
        return "ok", int(round(disp))

    if S == StorageType.ElementId and D == StorageType.ElementId:
        return "ok", src_p.AsElementId()

    return "fail", None


def blank_for(dst_p):
    """Value used to clear a target when 'push empty values' is on."""
    if dst_p.StorageType == StorageType.String:
        return ""
    if dst_p.StorageType == StorageType.ElementId:
        return ElementId.InvalidElementId
    return None  # numbers are never blanked


def set_value(param, value):
    st = param.StorageType
    if st == StorageType.String:
        return param.Set(value if value is not None else "")
    if st == StorageType.Integer:
        return param.Set(int(value))
    if st == StorageType.Double:
        return param.Set(float(value))
    if st == StorageType.ElementId:
        return param.Set(value)
    return False
