# -*- coding: utf-8 -*-
"""Tests for the Parent family <-> nested relationships. Revit is stubbed.

    cd DataPusher.extension/lib
    python ../tests/test_relations.py
"""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))

for _n in ("System", "Autodesk", "Autodesk.Revit", "Autodesk.Revit.DB"):
    sys.modules.setdefault(_n, types.ModuleType(_n))
_db = sys.modules["Autodesk.Revit.DB"]
for _n in ("BuiltInParameter", "FamilyInstance", "LocationCurve", "LocationPoint", "ViewSheet"):
    setattr(_db, _n, type(_n, (object,), {}))

_ru = types.ModuleType("pypipie.revitutil")
_ru.eid_val = lambda eid: -1 if eid is None else eid.v
_ru.is_valid_id = lambda eid: eid is not None and eid.v >= 0
import pypipie  # noqa: E402
sys.modules["pypipie.revitutil"] = _ru
pypipie.revitutil = _ru

from pypipie import relations  # noqa: E402


class Id(object):
    def __init__(self, v):
        self.v = v


class El(object):
    def __init__(self, v, parent=None):
        self.Id = Id(v)
        self.SuperComponent = parent
        self.kids = []
        if parent is not None:
            parent.kids.append(self)

    def GetSubComponentIds(self):
        return [k.Id for k in self.kids]


def stats():
    return {"unmatched": 0, "ambiguous": 0, "not_applicable": 0, "errors": []}


def model():
    p1, p2, p3, p4 = El(1), El(2), El(3), El(4)       # parent fixtures
    c1, c2 = El(11, p1), El(12, p2)                 # one connector each
    c3a, c3b = El(13, p3), El(14, p3)               # p3 has two connectors
    every = [p1, p2, p3, p4, c1, c2, c3a, c3b]      # same category: all lighting fixtures
    return every, (p1, p2, p3, p4), (c1, c2, c3a, c3b)


def test_nested_to_parent():
    every, (p1, p2, p3, p4), (c1, c2, c3a, c3b) = model()
    st = stats()
    pairs = relations.build_pairs(None, {"relation": "sub"}, every, every, st)
    got = sorted((a.Id.v, b.Id.v) for a, b in pairs)
    assert got == [(11, 1), (12, 2)], got        # child -> its parent
    assert st["ambiguous"] == 1                    # p3 has two nested children
    assert st["not_applicable"] == 5               # p4 + the 4 connectors have nothing nested
    assert st["unmatched"] == 0


def test_nested_to_parent_other_category():
    every, parents, kids = model()
    st = stats()
    pairs = relations.build_pairs(None, {"relation": "sub"}, [kids[0]], list(parents), st)
    assert [(a.Id.v, b.Id.v) for a, b in pairs] == [(11, 1)]
    assert st["unmatched"] == 2 and st["not_applicable"] == 1   # p2, p3 have kids not in A; p4 none


def test_parent_to_nested_top_level_not_counted_as_unmatched():
    every, parents, kids = model()
    st = stats()
    pairs = relations.build_pairs(None, {"relation": "super"}, every, every, st)
    assert sorted((a.Id.v, b.Id.v) for a, b in pairs) == [(1, 11), (2, 12), (3, 13), (3, 14)]
    assert st["not_applicable"] == 4 and st["unmatched"] == 0   # the 4 top-level parents


def test_relation_listed_and_allows_same_category():
    rel = relations.BY_KEY["sub"]
    assert rel.validate("OST_LightingFixtures", "OST_LightingFixtures") == ""
    assert rel.validate("OST_GenericModel", "OST_LightingFixtures") == ""


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok  " + name)
