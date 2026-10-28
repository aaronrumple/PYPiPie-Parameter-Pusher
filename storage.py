# -*- coding: utf-8 -*-
"""Mapping configuration: Extensible Storage persistence + JSON import/export.

The whole configuration is one JSON string stored on a dedicated DataStorage
element, so it travels with the project and syncs to central like any other
element.
"""
import json
import uuid
import copy
import datetime

from System import Guid, String, Int32
from Autodesk.Revit.DB import FilteredElementCollector, Transaction
from Autodesk.Revit.DB.ExtensibleStorage import (
    AccessLevel, DataStorage, Entity, Schema, SchemaBuilder
)

from pypipie import CONFIG_VERSION, APP_NAME

SCHEMA_GUID = Guid("6b1f6a42-2f6e-4c0e-9a9e-5d3f3f7f1b21")
# NOTE: schema GUID, schema name and storage name are the original PyPiPie identifiers.
# Never change them - projects that already store mappings would lose them.
SCHEMA_NAME = "PyPiPieParamPusher"
STORAGE_NAME = "PyPiPie_ParamPusher"
FIELD_JSON = "Json"
FIELD_VER = "Version"

DEFAULT_SETTINGS = {
    "on_save": True,
    "on_sync": True,
    "on_print": True,
    "on_export": True,
    "push_empty": False,     # clear text/element targets when the source is empty
    "rules_enabled": False,  # mapping rules (python) - off unless the project uses them
}

TRIGGER_SETTING = {
    "save": "on_save",
    "sync": "on_sync",
    "print": "on_print",
    "export": "on_export",
}


# --------------------------------------------------------------------------
# config object helpers (plain dicts so they serialise trivially)
# --------------------------------------------------------------------------
def new_config():
    return {"version": CONFIG_VERSION, "settings": dict(DEFAULT_SETTINGS), "mappings": []}


def normalise(cfg):
    if not isinstance(cfg, dict):
        cfg = new_config()
    cfg.setdefault("version", CONFIG_VERSION)
    stored = cfg.get("settings") or {}
    settings = dict(DEFAULT_SETTINGS)
    settings.update(stored)
    if "rules_enabled" not in stored:
        # configs from before the switch existed: keep rules working if any are present
        settings["rules_enabled"] = any(
            (p.get("rule") or "").strip()
            for m in (cfg.get("mappings") or []) if isinstance(m, dict)
            for p in (m.get("pairs") or []) if isinstance(p, dict))
    cfg["settings"] = settings
    maps = []
    for m in cfg.get("mappings") or []:
        if not isinstance(m, dict):
            continue
        m.setdefault("id", new_id())
        m.setdefault("enabled", True)
        m.setdefault("relation", "same")
        m.setdefault("relation_opts", {})
        m.setdefault("pairs", [])
        m.setdefault("name", default_name(m))
        for p in m["pairs"]:
            p.setdefault("enabled", True)
            p.setdefault("rule", u"")
            p.setdefault("rule_on", True)
            p.setdefault("rule_empty", False)  # run the rule even when the source is empty
        maps.append(m)
    cfg["mappings"] = maps
    return cfg


# --------------------------------------------------------------------------
# rule state (pure - safe to use anywhere)
# --------------------------------------------------------------------------
RULE_NONE, RULE_ON, RULE_OFF, RULE_GLOBAL_OFF = "none", "on", "off", "global_off"


def has_rule(pair):
    return bool((pair.get("rule") or "").strip())


def rule_state(settings, pair):
    """none | on | off (pair switch) | global_off (rules disabled for the project)."""
    if not has_rule(pair):
        return RULE_NONE
    if not pair.get("rule_on", True):
        return RULE_OFF
    if not (settings or {}).get("rules_enabled", False):
        return RULE_GLOBAL_OFF
    return RULE_ON


def rule_active(settings, pair):
    return rule_state(settings, pair) == RULE_ON


def new_id():
    return uuid.uuid4().hex[:12]


def default_name(m):
    return u"{} → {}".format(m.get("cat_a_name", "?"), m.get("cat_b_name", "?"))


def find_mapping(cfg, mid):
    for m in cfg["mappings"]:
        if m["id"] == mid:
            return m
    return None


def upsert_mapping(cfg, mapping):
    for i, m in enumerate(cfg["mappings"]):
        if m["id"] == mapping["id"]:
            cfg["mappings"][i] = mapping
            return
    cfg["mappings"].append(mapping)


def clone(cfg):
    return copy.deepcopy(cfg)


# --------------------------------------------------------------------------
# Extensible Storage
# --------------------------------------------------------------------------
def get_schema():
    schema = Schema.Lookup(SCHEMA_GUID)
    if schema is not None:
        return schema
    sb = SchemaBuilder(SCHEMA_GUID)
    sb.SetSchemaName(SCHEMA_NAME)
    sb.SetDocumentation("{} parameter pusher mappings (JSON)".format(APP_NAME))
    sb.SetReadAccessLevel(AccessLevel.Public)
    sb.SetWriteAccessLevel(AccessLevel.Public)
    sb.AddSimpleField(FIELD_JSON, String)
    sb.AddSimpleField(FIELD_VER, Int32)
    return sb.Finish()


def _find_storage(doc, schema):
    if schema is None:
        return None
    for ds in FilteredElementCollector(doc).OfClass(DataStorage):
        try:
            ent = ds.GetEntity(schema)
            if ent is not None and ent.IsValid():
                return ds
        except Exception:
            continue
    return None


def load(doc):
    """Read the config from the document. Always returns a normalised config."""
    schema = Schema.Lookup(SCHEMA_GUID)
    ds = _find_storage(doc, schema)
    if ds is None:
        return new_config()
    try:
        ent = ds.GetEntity(schema)
        raw = ent.Get[String](FIELD_JSON)
        return normalise(json.loads(raw) if raw else None)
    except Exception:
        return new_config()


def save(doc, cfg):
    """Write config to the document. Opens its own transaction when needed."""
    cfg = normalise(cfg)
    cfg["saved"] = datetime.datetime.now().isoformat()[:19]
    payload = json.dumps(cfg, separators=(",", ":"))
    schema = get_schema()

    t = None
    if not doc.IsModifiable:
        t = Transaction(doc, "{}: Save parameter mappings".format(APP_NAME))
        t.Start()
    try:
        ds = _find_storage(doc, schema)
        if ds is None:
            ds = DataStorage.Create(doc)
            try:
                ds.Name = STORAGE_NAME
            except Exception:
                pass
        ent = Entity(schema)
        ent.Set[String](FIELD_JSON, payload)
        ent.Set[Int32](FIELD_VER, CONFIG_VERSION)
        ds.SetEntity(ent)
        if t is not None:
            t.Commit()
    except Exception:
        if t is not None and t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    return cfg


# --------------------------------------------------------------------------
# JSON files
# --------------------------------------------------------------------------
def export_file(cfg, path, mapping_ids=None):
    out = clone(normalise(cfg))
    if mapping_ids:
        out["mappings"] = [m for m in out["mappings"] if m["id"] in mapping_ids]
    out["exported"] = datetime.datetime.now().isoformat()[:19]
    out["app"] = APP_NAME
    with open(path, "w") as f:
        f.write(json.dumps(out, indent=2, sort_keys=True))
    return len(out["mappings"])


def read_file(path):
    with open(path, "r") as f:
        data = json.loads(f.read())
    if not isinstance(data, dict) or "mappings" not in data:
        raise ValueError("Not a {} mapping file.".format(APP_NAME))
    return normalise(data)


# --------------------------------------------------------------------------
# grouping: one mapping per category pairing (A, B, relationship, keys)
# --------------------------------------------------------------------------
def _ref_id(ref):
    """Same identity as revitutil.ref_key, without importing Revit."""
    if not ref:
        return u""
    ident = ref.get("bip") or ref.get("guid") or (u"N:" + (ref.get("name") or u""))
    return (u"T|" if ref.get("type") else u"I|") + ident


def group_key(m):
    """Mappings with the same key belong in one mapping."""
    opts = m.get("relation_opts") or {}
    rel = m.get("relation", "same")
    keys = (_ref_id(opts.get("key_a")), _ref_id(opts.get("key_b"))) if rel == "key" else (u"", u"")
    return (m.get("cat_a"), m.get("cat_b"), rel) + keys


def find_group(cfg, m, exclude_id=None):
    k = group_key(m)
    for other in cfg["mappings"]:
        if other.get("id") != exclude_id and group_key(other) == k:
            return other
    return None


def pair_conflicts(group, pairs):
    """Pairs whose target is already fed (by a different source or rule) in `group`.
    Returns [(new_pair, existing_pair)]."""
    out = []
    for p in pairs:
        for q in group.get("pairs", []):
            if _ref_id(q["dst"]) == _ref_id(p["dst"]) and not _same_pair(p, q):
                out.append((p, q))
                break
    return out


def _same_pair(p, q):
    return (_ref_id(p["src"]) == _ref_id(q["src"]) and _ref_id(p["dst"]) == _ref_id(q["dst"])
            and (p.get("rule") or u"").strip() == (q.get("rule") or u"").strip())


def add_pairs(group, pairs, on_conflict="replace"):
    """Add pairs to a mapping.

    exact duplicates are dropped; a pair whose target is already fed is handled by on_conflict:
      replace - the new pair takes the existing pair's place
      skip    - the existing pair stays, the new one is dropped
      disable - the new pair is appended switched off (nothing is lost)
    Returns (added, replaced, skipped).
    """
    added = replaced = skipped = 0
    group.setdefault("pairs", [])
    for p in pairs:
        p = copy.deepcopy(p)
        if any(_same_pair(p, q) for q in group["pairs"]):
            skipped += 1
            continue
        hit = None
        for i, q in enumerate(group["pairs"]):
            if _ref_id(q["dst"]) == _ref_id(p["dst"]):
                hit = i
                break
        if hit is None:
            group["pairs"].append(p)
            added += 1
        elif on_conflict == "replace":
            group["pairs"][hit] = p
            replaced += 1
        elif on_conflict == "disable":
            p["enabled"] = False
            group["pairs"].append(p)
            added += 1
        else:
            skipped += 1
    return added, replaced, skipped


def duplicate_groups(cfg):
    """[[mapping, mapping, ...], ...] for category pairings stored as more than one mapping."""
    groups = {}
    order = []
    for m in cfg["mappings"]:
        k = group_key(m)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(m)
    return [groups[k] for k in order if len(groups[k]) > 1]


def consolidate(cfg):
    """Fold mappings that share a category pairing into one. Behaviour is preserved:
    pairs of a disabled mapping arrive switched off, and conflicting targets arrive
    switched off rather than being dropped. Returns the number of mappings removed."""
    removed = 0
    for members in duplicate_groups(cfg):
        first = members[0]
        any_on = any(m.get("enabled", True) for m in members)
        if any_on and not first.get("enabled", True):
            for p in first["pairs"]:
                p["enabled"] = False
            first["enabled"] = True
        for m in members[1:]:
            incoming = copy.deepcopy(m.get("pairs", []))
            if any_on and not m.get("enabled", True):
                for p in incoming:
                    p["enabled"] = False
            add_pairs(first, incoming, on_conflict="disable")
            if first.get("name") == default_name(first) and m.get("name") != default_name(m):
                first["name"] = m["name"]
            cfg["mappings"].remove(m)
            removed += 1
    return removed


def merge(cfg, incoming, replace=False, take_settings=False):
    """Merge `incoming` mappings into cfg. Same id -> replaced; same category pairing ->
    pairs folded into the existing mapping (incoming pairs win on the same target).
    Returns the number of mappings in the file."""
    if replace:
        cfg["mappings"] = []
    for m in incoming["mappings"]:
        if any(x["id"] == m["id"] for x in cfg["mappings"]):
            upsert_mapping(cfg, m)
            continue
        group = find_group(cfg, m)
        if group is not None:
            add_pairs(group, m.get("pairs", []), on_conflict="replace")
        else:
            cfg["mappings"].append(m)
    consolidate(cfg)
    if take_settings:
        cfg["settings"].update(incoming.get("settings") or {})
    return len(incoming["mappings"])
