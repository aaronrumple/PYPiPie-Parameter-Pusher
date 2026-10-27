# -*- coding: utf-8 -*-
"""Revit API helpers shared by PyPiPie: ids, categories, parameter references,
spec (data type) helpers and element collection.

Targets Revit 2022+ (ForgeTypeId API). Works with both ElementId.IntegerValue
(<= 2023) and ElementId.Value (2024+).
"""
import System
from System import Guid

from Autodesk.Revit.DB import (
    BuiltInCategory, BuiltInParameter, Category, ElementId,
    FilteredElementCollector, ForgeTypeId, LabelUtils, SpecTypeId,
    StorageType, UnitUtils, View
)


# `StorageType.None` is a syntax error in Python, so fetch it by name.
ST_NONE = getattr(StorageType, "None")


# --------------------------------------------------------------------------
# ElementId helpers
# --------------------------------------------------------------------------
def eid_val(eid):
    """Integer value of an ElementId across Revit versions."""
    if eid is None:
        return -1
    try:
        return int(eid.Value)
    except AttributeError:
        return int(eid.IntegerValue)


def is_valid_id(eid):
    return eid is not None and eid != ElementId.InvalidElementId


# --------------------------------------------------------------------------
# Categories (stored portably as BuiltInCategory enum names)
# --------------------------------------------------------------------------
def category_key(cat):
    """Portable key for a Category: 'OST_Doors' etc."""
    v = eid_val(cat.Id)
    if v < 0:
        try:
            return str(System.Enum.ToObject(BuiltInCategory, v))
        except Exception:
            pass
    return "NAME:" + cat.Name


def category_from_key(doc, key):
    """Resolve a stored category key to a Category in this document (or None)."""
    if not key:
        return None
    if key.startswith("NAME:"):
        name = key[5:]
        for cat in doc.Settings.Categories:
            if cat.Name == name:
                return cat
        return None
    try:
        bic = getattr(BuiltInCategory, key)
        return Category.GetCategory(doc, bic)
    except Exception:
        return None


def list_categories(doc):
    """Top-level categories that can carry parameters, sorted by name."""
    out = []
    for cat in doc.Settings.Categories:
        try:
            if cat.Parent is not None:
                continue
            if not (cat.AllowsBoundParameters or eid_val(cat.Id) in _EXTRA_CATS):
                continue
            out.append(cat)
        except Exception:
            continue
    out.sort(key=lambda c: c.Name.lower())
    return out


_EXTRA_CATS = set()
for _n in ("OST_Views", "OST_Sheets", "OST_Levels", "OST_Assemblies",
           "OST_IOSModelGroups", "OST_IOSDetailGroups"):
    try:
        _EXTRA_CATS.add(int(getattr(BuiltInCategory, _n)))
    except Exception:
        pass


def collect_instances(doc, cat_key):
    """All non-type elements of a category (view templates excluded)."""
    cat = category_from_key(doc, cat_key)
    if cat is None:
        return []
    elems = (FilteredElementCollector(doc)
             .OfCategoryId(cat.Id)
             .WhereElementIsNotElementType()
             .ToElements())
    out = []
    for e in elems:
        if isinstance(e, View) and e.IsTemplate:
            continue
        out.append(e)
    return out


def element_type(doc, el):
    try:
        tid = el.GetTypeId()
    except Exception:
        return None
    if not is_valid_id(tid):
        return None
    return doc.GetElement(tid)


def element_name(el):
    try:
        return el.Name
    except Exception:
        return ""


# --------------------------------------------------------------------------
# Specs / data types
# --------------------------------------------------------------------------
def spec_base(type_id):
    """'autodesk.spec.aec:length-2.0.0' -> 'autodesk.spec.aec:length'."""
    if not type_id:
        return ""
    return type_id.split("-")[0]


def _tid(fid):
    try:
        return fid.TypeId
    except Exception:
        return ""


SPEC_YESNO = spec_base(_tid(SpecTypeId.Boolean.YesNo))
SPEC_INT = spec_base(_tid(SpecTypeId.Int.Integer))
SPEC_NUMBER = spec_base(_tid(SpecTypeId.Number))
SPEC_TEXT = set()
for _n in ("Text", "MultilineText", "Url"):
    try:
        SPEC_TEXT.add(spec_base(_tid(getattr(SpecTypeId.String, _n))))
    except Exception:
        pass


def is_yesno(spec):
    return spec_base(spec) == SPEC_YESNO


def is_number(spec):
    return spec_base(spec) == SPEC_NUMBER


_MEASURABLE = {}


def is_measurable(spec):
    if not spec:
        return False
    if spec not in _MEASURABLE:
        try:
            _MEASURABLE[spec] = bool(UnitUtils.IsMeasurableSpec(ForgeTypeId(spec)))
        except Exception:
            _MEASURABLE[spec] = False
    return _MEASURABLE[spec]


_LABELS = {}


def spec_label(spec, storage):
    """Human label for a data type, e.g. 'Length', 'Yes/No', 'Text'."""
    if spec:
        if spec not in _LABELS:
            label = ""
            try:
                label = LabelUtils.GetLabelForSpec(ForgeTypeId(spec))
            except Exception:
                pass
            if not label:
                # category-typed (family type) params, or unknown specs
                label = spec.split(":")[-1].split("-")[0].replace(".", " ").title()
            _LABELS[spec] = label
        return _LABELS[spec]
    return {"String": "Text", "Integer": "Integer", "Double": "Number",
            "ElementId": "Element"}.get(storage, storage)


# --------------------------------------------------------------------------
# Parameter references (portable dicts)
# --------------------------------------------------------------------------
def make_ref(param, is_type):
    """Portable description of a parameter. Stored in the mapping JSON."""
    d = param.Definition
    bip = None
    try:
        b = d.BuiltInParameter
        if b != BuiltInParameter.INVALID:
            bip = str(b)
    except Exception:
        pass
    guid = None
    try:
        if param.IsShared:
            guid = str(param.GUID)
    except Exception:
        pass
    spec = ""
    try:
        spec = d.GetDataType().TypeId
    except Exception:
        pass
    return {
        "name": d.Name,
        "bip": bip,
        "guid": guid,
        "type": bool(is_type),
        "storage": str(param.StorageType),
        "spec": spec,
        "ro": bool(param.IsReadOnly),
    }


def ref_key(ref):
    """Stable identity for a ref (scope + identity)."""
    ident = ref.get("bip") or ref.get("guid") or ("N:" + ref.get("name", ""))
    return ("T|" if ref.get("type") else "I|") + ident


def ref_label(ref):
    return "{}{}".format(ref.get("name", "?"), " [Type]" if ref.get("type") else "")


def find_param(el, ref):
    """Find the parameter described by `ref` on `el` (instance or type element)."""
    if el is None or not ref:
        return None
    p = None
    bip = ref.get("bip")
    if bip:
        try:
            p = el.get_Parameter(getattr(BuiltInParameter, bip))
        except Exception:
            p = None
        if p is not None:
            return p
    guid = ref.get("guid")
    if guid:
        try:
            p = el.get_Parameter(Guid(guid))
        except Exception:
            p = None
        if p is not None:
            return p
    if not bip:  # built-ins are never looked up by (localized) name
        try:
            p = el.LookupParameter(ref.get("name"))
        except Exception:
            p = None
    return p


# Built-ins that report IsReadOnly = False but can't (or must not) be pushed into.
_ALWAYS_RO = set()
for _n in ("EDITED_BY", "ID_PARAM", "ELEM_CATEGORY_PARAM", "ELEM_CATEGORY_PARAM_MT",
           "ELEM_FAMILY_PARAM", "SYMBOL_FAMILY_NAME_PARAM", "ALL_MODEL_FAMILY_NAME",
           "SYMBOL_FAMILY_AND_TYPE_NAMES_PARAM", "HOST_ID_PARAM", "ELEM_ROOM_ID", "DESIGN_OPTION_ID"):
    try:
        _ALWAYS_RO.add(str(getattr(BuiltInParameter, _n)))
    except Exception:
        pass


def _driven_by_global(param):
    """True when the value is locked to a global parameter."""
    try:
        return is_valid_id(param.GetAssociatedGlobalParameter())
    except Exception:
        return False


def _in_group(el):
    try:
        return is_valid_id(el.GroupId)
    except Exception:
        return False


def writable(param, el=None):
    """Can PyPiPie write this parameter on this element right now?"""
    if param is None:
        return False
    try:
        if param.IsReadOnly:
            return False
        b = param.Definition.BuiltInParameter
        if str(b) in _ALWAYS_RO:
            return False
    except Exception:
        return False
    if _driven_by_global(param):
        return False
    return True


def gather_params(doc, cat_key, sample=60):
    """List parameter refs available on instances (and their types) of a category.

    Each ref gets 'ro' = True when the parameter is read-only on ANY sampled element
    (or type). Read-only-ness that only comes from the element's situation - it sits in a
    group, or the value is locked to a global parameter - is not held against the
    parameter; those elements are skipped one by one at push time.

    Returns (refs sorted by name, instance_count).
    """
    elems = collect_instances(doc, cat_key)
    found = {}
    types_seen = set()

    def visit(owner, is_type):
        situational = (not is_type) and _in_group(owner)
        for p in owner.Parameters:
            try:
                if p.StorageType == ST_NONE:
                    continue
                r = make_ref(p, is_type)
                ro = not writable(p)
                if ro and (situational or (not p.IsReadOnly and _driven_by_global(p))):
                    ro = None  # read-only here for situational reasons only - don't count
            except Exception:
                continue
            k = ref_key(r)
            if k not in found:
                r["ro"] = False
                r["_seen"] = 0
                found[k] = r
            if ro is not None:
                found[k]["_seen"] += 1
                if ro:
                    found[k]["ro"] = True

    for el in elems[:sample]:
        visit(el, False)
        t = element_type(doc, el)
        if t is not None and eid_val(t.Id) not in types_seen:
            types_seen.add(eid_val(t.Id))
            visit(t, True)

    refs = []
    for r in found.values():
        if r.pop("_seen") == 0:
            r["ro"] = True  # only ever seen in situational read-only state - can't vouch for it
        refs.append(r)
    refs.sort(key=lambda r: (r["name"].lower(), r["type"]))
    return refs, len(elems)


def as_text(doc, param):
    """Display text of any parameter (used for key matching and text targets)."""
    if param is None:
        return ""
    st = param.StorageType
    try:
        if st == StorageType.String:
            return param.AsString() or ""
        vs = param.AsValueString()
        if vs:
            return vs
        if st == StorageType.Integer:
            return str(param.AsInteger())
        if st == StorageType.Double:
            return repr(param.AsDouble())
        if st == StorageType.ElementId:
            e = doc.GetElement(param.AsElementId())
            return element_name(e) if e is not None else ""
    except Exception:
        pass
    return ""
