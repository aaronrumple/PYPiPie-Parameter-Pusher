# -*- coding: utf-8 -*-
"""How an element of category A is related to an element of category B.

Each relation turns (A elements, B elements) into (source, target) pairs.
A target receives values from exactly one source; if a relation produces
several sources for one target, the first wins and the rest count as ambiguous.
"""
from Autodesk.Revit.DB import (
    BuiltInParameter, FamilyInstance, LocationCurve, LocationPoint, ViewSheet
)

from pypipie import revitutil as ru


class Relation(object):
    def __init__(self, key, label, help_text, cat_a=None, cat_b=None,
                 same_cat=False, needs_keys=False, allow_same=False):
        self.key = key
        self.label = label
        self.help = help_text
        self.cat_a = cat_a          # required category A key (or tuple) or None
        self.cat_b = cat_b          # required category B key (or tuple) or None
        self.same_cat = same_cat    # A must equal B
        self.needs_keys = needs_keys
        self.allow_same = allow_same or same_cat  # may A and B be the same category?

    def validate(self, cat_a, cat_b):
        """Return an error string, or '' when the categories suit this relation."""
        if not cat_a or not cat_b:
            return "Pick a category in both columns."
        if self.same_cat and cat_a != cat_b:
            return "'{}' needs the same category in A and B.".format(self.label)
        if cat_a == cat_b and not self.allow_same:
            return "'{}' needs two different categories.".format(self.label)
        for want, got, col in ((self.cat_a, cat_a, "A"), (self.cat_b, cat_b, "B")):
            if want:
                wants = want if isinstance(want, tuple) else (want,)
                if got not in wants:
                    return "'{}' needs category {} = {}.".format(
                        self.label, col, " or ".join(w.replace("OST_", "") for w in wants))
        return ""


RELATIONS = [
    Relation("same", "Same element",
             "Copy one parameter to another on the same element (A and B are the same category). "
             "Type parameters are read from / written to the element's type.",
             same_cat=True),
    Relation("key", "Matching key value",
             "Pair A and B elements whose key parameters have the same value "
             "(text compare, case-insensitive). E.g. Rooms.Number = Doors.'Room Number'. "
             "Works within one category too (an element never matches itself).",
             needs_keys=True, allow_same=True),
    Relation("host", "Host -> hosted",
             "B elements receive values from their host (e.g. Walls -> Doors/Windows)."),
    Relation("room", "Room -> elements in room",
             "B elements receive values from the room they are in "
             "(doors/windows use To Room, then From Room).",
             cat_a="OST_Rooms"),
    Relation("space", "Space -> elements in space",
             "B elements receive values from the MEP space they are in.",
             cat_a="OST_MEPSpaces"),
    Relation("level", "Level -> elements on level",
             "B elements receive values from their associated level.",
             cat_a="OST_Levels"),
    Relation("sheet", "Sheet -> placed views",
             "Views receive values from the sheet they are placed on.",
             cat_a="OST_Sheets", cat_b="OST_Views"),
    Relation("super", "Parent family -> nested",
             "Shared nested family instances receive values from their parent instance "
             "(same or different category).", allow_same=True),
    Relation("sub", "Nested -> parent family",
             "Parent family instances receive values from the shared nested instance inside them "
             "(same or different category). A parent with several nested A elements is skipped as ambiguous.",
             allow_same=True),
    Relation("dependent", "Parent view -> dependent views",
             "Dependent views receive values from their parent (primary) view.",
             cat_a="OST_Views", cat_b="OST_Views", allow_same=True),
    Relation("assembly", "Assembly -> members",
             "Assembly members receive values from their assembly.",
             cat_a="OST_Assemblies"),
    Relation("group", "Group -> members",
             "Group members receive values from their group.",
             cat_a=("OST_IOSModelGroups", "OST_IOSDetailGroups")),
]

BY_KEY = dict((r.key, r) for r in RELATIONS)

# Preferred relation when a category pair is picked (first valid wins).
_PREFERENCE = ["same", "dependent", "room", "space", "level", "sheet", "assembly", "group", "key"]


def available(cat_a, cat_b):
    """Relations valid for this category pair."""
    if not cat_a or not cat_b:
        return list(RELATIONS)
    return [r for r in RELATIONS if not r.validate(cat_a, cat_b)]


def default_for(cat_a, cat_b):
    valid = set(r.key for r in available(cat_a, cat_b))
    for k in _PREFERENCE:
        if k in valid:
            return k
    return "key"


def is_self_pair(relation_key, src, dst):
    """Same element + same parameter = a pointless (and blocked) pair."""
    from pypipie.revitutil import ref_key
    return relation_key == "same" and ref_key(src) == ref_key(dst)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _phase_of(doc, el):
    try:
        pid = el.CreatedPhaseId
        if ru.is_valid_id(pid):
            ph = doc.GetElement(pid)
            if ph is not None:
                return ph
    except Exception:
        pass
    phases = doc.Phases
    return phases[phases.Size - 1] if phases.Size else None


def _point_of(el):
    loc = el.Location
    if isinstance(loc, LocationPoint):
        return loc.Point
    if isinstance(loc, LocationCurve):
        return loc.Curve.Evaluate(0.5, True)
    try:
        bb = el.get_BoundingBox(None)
        if bb is not None:
            return (bb.Min + bb.Max) * 0.5
    except Exception:
        pass
    return None


def _room_of(doc, el, spaces=False):
    phase = _phase_of(doc, el)
    if phase is None:
        return None
    if isinstance(el, FamilyInstance):
        try:
            if spaces:
                r = el.get_Space(phase)
            else:
                r = el.get_ToRoom(phase) or el.get_FromRoom(phase) or el.get_Room(phase)
            if r is not None:
                return r
        except Exception:
            pass
    pt = _point_of(el)
    if pt is None:
        return None
    try:
        return doc.GetSpaceAtPoint(pt, phase) if spaces else doc.GetRoomAtPoint(pt, phase)
    except Exception:
        return None


_LEVEL_BIPS = []
for _n in ("FAMILY_LEVEL_PARAM", "INSTANCE_REFERENCE_LEVEL_PARAM", "SCHEDULE_LEVEL_PARAM",
           "WALL_BASE_CONSTRAINT", "LEVEL_PARAM", "ROOM_LEVEL_ID", "STAIRS_BASE_LEVEL_PARAM"):
    try:
        _LEVEL_BIPS.append(getattr(BuiltInParameter, _n))
    except Exception:
        pass


def _level_id_of(el):
    try:
        gl = getattr(el, "GenLevel", None)  # views
        if gl is not None:
            return gl.Id
    except Exception:
        pass
    try:
        lid = el.LevelId
        if ru.is_valid_id(lid):
            return lid
    except Exception:
        pass
    for bip in _LEVEL_BIPS:
        try:
            p = el.get_Parameter(bip)
            if p is not None and ru.is_valid_id(p.AsElementId()):
                return p.AsElementId()
        except Exception:
            continue
    return None


def _id_or_none(el):
    return el.Id if el is not None else None


def _norm(text):
    return (text or "").strip().lower()


# --------------------------------------------------------------------------
# main entry
# --------------------------------------------------------------------------
def build_pairs(doc, mapping, a_elems, b_elems, stats):
    """Return list of (source_element, target_element)."""
    rel = mapping.get("relation", "same")
    pairs = []
    a_by_id = dict((ru.eid_val(a.Id), a) for a in a_elems)

    def bump(key):
        stats[key] = stats.get(key, 0) + 1

    def via(getter, not_applicable=None):
        """getter(b) -> id of b's A element. not_applicable(b) -> True when b can't have one at
        all (e.g. a top-level family for Parent -> nested); those aren't counted as unmatched."""
        for b in b_elems:
            if not_applicable is not None:
                try:
                    na = not_applicable(b)
                except Exception:
                    na = False
                if na:
                    bump("not_applicable")
                    continue
            try:
                sid = getter(b)
            except Exception:
                sid = None
            src = a_by_id.get(ru.eid_val(sid)) if sid is not None else None
            if src is None:
                bump("unmatched")
            else:
                pairs.append((src, b))

    if rel == "same":
        pairs = [(b, b) for b in b_elems]

    elif rel == "key":
        opts = mapping.get("relation_opts") or {}
        ka, kb = opts.get("key_a"), opts.get("key_b")
        if not ka or not kb:
            stats["errors"].append("Key parameters are not set.")
            return []
        index = {}
        for a in a_elems:
            host = ru.element_type(doc, a) if ka.get("type") else a
            k = _norm(ru.as_text(doc, ru.find_param(host, ka)))
            if not k:
                continue
            index.setdefault(k, []).append(a)
        for b in b_elems:
            host = ru.element_type(doc, b) if kb.get("type") else b
            k = _norm(ru.as_text(doc, ru.find_param(host, kb)))
            hits = index.get(k) if k else None
            if hits:
                bid = ru.eid_val(b.Id)
                hits = [a for a in hits if ru.eid_val(a.Id) != bid]
            if not hits:
                stats["unmatched"] += 1
            elif len(hits) > 1:
                stats["ambiguous"] += 1
            else:
                pairs.append((hits[0], b))

    elif rel == "host":
        via(lambda b: b.Host.Id if getattr(b, "Host", None) is not None else None)

    elif rel == "room":
        via(lambda b: _id_or_none(_room_of(doc, b)))

    elif rel == "space":
        via(lambda b: _id_or_none(_room_of(doc, b, True)))

    elif rel == "level":
        via(_level_id_of)

    elif rel == "sheet":
        view_to_sheet = {}
        for s in a_elems:
            if not isinstance(s, ViewSheet):
                continue
            for vid in s.GetAllPlacedViews():
                view_to_sheet[ru.eid_val(vid)] = s
        for b in b_elems:
            s = view_to_sheet.get(ru.eid_val(b.Id))
            if s is None:
                stats["unmatched"] += 1
            else:
                pairs.append((s, b))

    elif rel == "super":
        via(lambda b: b.SuperComponent.Id,
            not_applicable=lambda b: getattr(b, "SuperComponent", None) is None)

    elif rel == "sub":
        for b in b_elems:
            try:
                kids = list(b.GetSubComponentIds())
            except Exception:  # not a family instance
                kids = []
            if not kids:
                bump("not_applicable")  # nothing nested in it
                continue
            hits = [a_by_id[ru.eid_val(k)] for k in kids if ru.eid_val(k) in a_by_id]
            if not hits:
                bump("unmatched")
            elif len(hits) > 1:
                bump("ambiguous")
            else:
                pairs.append((hits[0], b))

    elif rel == "dependent":
        via(lambda b: b.GetPrimaryViewId() if ru.is_valid_id(b.GetPrimaryViewId()) else None)

    elif rel == "assembly":
        via(lambda b: b.AssemblyInstanceId if ru.is_valid_id(b.AssemblyInstanceId) else None)

    elif rel == "group":
        via(lambda b: b.GroupId if ru.is_valid_id(b.GroupId) else None)

    else:
        stats["errors"].append("Unknown relation '{}'".format(rel))

    return pairs
