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
    settings = dict(DEFAULT_SETTINGS)
    settings.update(cfg.get("settings") or {})
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
        maps.append(m)
    cfg["mappings"] = maps
    return cfg


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


def merge(cfg, incoming, replace=False, take_settings=False):
    """Merge `incoming` mappings into cfg. Same id -> replaced. Returns count."""
    if replace:
        cfg["mappings"] = []
    for m in incoming["mappings"]:
        upsert_mapping(cfg, m)
    if take_settings:
        cfg["settings"].update(incoming.get("settings") or {})
    return len(incoming["mappings"])
