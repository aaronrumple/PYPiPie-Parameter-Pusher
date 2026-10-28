# -*- coding: utf-8 -*-
"""Tests for mapping grouping / merging in storage.py. Pure Python - Revit is stubbed.

    cd DataPusher.extension/lib
    python ../tests/test_storage.py
"""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))

for _n in ("System", "Autodesk", "Autodesk.Revit", "Autodesk.Revit.DB", "Autodesk.Revit.DB.ExtensibleStorage"):
    sys.modules.setdefault(_n, types.ModuleType(_n))
_sys = sys.modules["System"]
_sys.Guid, _sys.String, _sys.Int32 = (lambda s: s), str, int
sys.modules["Autodesk.Revit.DB"].FilteredElementCollector = object
sys.modules["Autodesk.Revit.DB"].Transaction = object
for _n in ("AccessLevel", "DataStorage", "Entity", "Schema", "SchemaBuilder"):
    setattr(sys.modules["Autodesk.Revit.DB.ExtensibleStorage"], _n, object)

from pypipie import storage as s  # noqa: E402


def ref(name, typ=False):
    return {"name": name, "type": typ, "bip": None, "guid": None}


def pair(src, dst, rule=u"", enabled=True):
    return {"src": ref(src), "dst": ref(dst), "rule": rule, "enabled": enabled, "rule_on": True}


def mapping(mid, pairs, enabled=True, rel="host", a="OST_Walls", b="OST_Doors", name=None):
    m = {"id": mid, "cat_a": a, "cat_b": b, "cat_a_name": "Walls", "cat_b_name": "Doors",
         "relation": rel, "relation_opts": {}, "pairs": pairs, "enabled": enabled}
    m["name"] = name or s.default_name(m)
    return m


def cfg(*maps):
    return s.normalise({"mappings": list(maps)})


def test_group_key():
    assert s.group_key(mapping("1", [])) == s.group_key(mapping("2", []))
    assert s.group_key(mapping("1", [])) != s.group_key(mapping("2", [], rel="room"))
    k1 = mapping("1", [], rel="key")
    k2 = mapping("2", [], rel="key")
    k1["relation_opts"] = {"key_a": ref("Mark"), "key_b": ref("Mark")}
    k2["relation_opts"] = {"key_a": ref("Mark"), "key_b": ref("Comments")}
    assert s.group_key(k1) != s.group_key(k2)


def test_consolidate_screenshot_case():
    # the screenshot: three Walls -> Doors (host) mappings, one pair each
    c = cfg(mapping("1", [pair("Width", "Comments")]),
            mapping("2", [pair("Width", "Comments")]),
            mapping("3", [pair("Width", "Comments", rule="value * 2")]),
            mapping("4", [pair("Width", "Comments")], b="OST_Windows"))
    assert len(s.duplicate_groups(c)) == 1
    assert s.consolidate(c) == 2
    assert len(c["mappings"]) == 2
    doors = c["mappings"][0]["pairs"]
    assert len(doors) == 2                      # exact duplicate dropped
    assert doors[0]["enabled"] and not doors[1]["enabled"]   # conflicting target kept, switched off
    assert s.duplicate_groups(c) == []


def test_consolidate_keeps_disabled_behaviour():
    c = cfg(mapping("1", [pair("A", "X")], enabled=False),
            mapping("2", [pair("B", "Y")]))
    s.consolidate(c)
    m = c["mappings"][0]
    assert m["enabled"]
    on = dict((p["dst"]["name"], p["enabled"]) for p in m["pairs"])
    assert on == {"X": False, "Y": True}


def test_add_pairs_modes():
    g = mapping("1", [pair("A", "X")])
    assert s.add_pairs(g, [pair("B", "X")], "skip") == (0, 0, 1)
    assert s.add_pairs(g, [pair("B", "X")], "replace") == (0, 1, 0)
    assert g["pairs"][0]["src"]["name"] == "B"
    assert s.add_pairs(g, [pair("C", "Z")], "replace") == (1, 0, 0)
    assert len(s.pair_conflicts(g, [pair("D", "Z"), pair("E", "W")])) == 1


def test_import_merges_by_pairing():
    c = cfg(mapping("1", [pair("A", "X")]))
    incoming = cfg(mapping("9", [pair("B", "X"), pair("C", "Y")]))
    s.merge(c, incoming)
    assert len(c["mappings"]) == 1
    names = [(p["src"]["name"], p["dst"]["name"]) for p in c["mappings"][0]["pairs"]]
    assert names == [("B", "X"), ("C", "Y")]    # incoming wins on the same target


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok  " + name)
