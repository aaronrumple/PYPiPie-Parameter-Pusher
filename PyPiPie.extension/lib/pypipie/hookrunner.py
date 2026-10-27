# -*- coding: utf-8 -*-
"""Entry point for the pyRevit event hooks. Never raises, never shows UI."""
import io
import os
import datetime

from pypipie import APP_NAME

LOG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "pyRevit", APP_NAME)
LOG_FILE = os.path.join(LOG_DIR, "push.log")
MAX_LOG_BYTES = 512 * 1024


def _event_doc():
    try:
        from pyrevit import EXEC_PARAMS
        args = EXEC_PARAMS.event_args
    except Exception:
        args = None
    if args is None:
        return None
    try:
        return args.Document
    except Exception:
        return None


def _log(lines):
    try:
        if not os.path.isdir(LOG_DIR):
            os.makedirs(LOG_DIR)
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > MAX_LOG_BYTES:
            os.remove(LOG_FILE)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with io.open(LOG_FILE, "a", encoding="utf-8") as f:
            for ln in lines:
                f.write(u"{} {}\n".format(stamp, ln))
    except Exception:
        pass


def run_hook(trigger, doc=None):
    """trigger: 'save' | 'sync' | 'print' | 'export'"""
    try:
        doc = doc or _event_doc()
        if doc is None or doc.IsFamilyDocument or doc.IsReadOnly or doc.IsLinked:
            return
        from pypipie import storage, engine
        cfg = storage.load(doc)
        if not cfg["mappings"]:
            return
        if not cfg["settings"].get(storage.TRIGGER_SETTING.get(trigger, ""), True):
            return
        if not any(m.get("enabled", True) for m in cfg["mappings"]):
            return
        report = engine.run(doc, cfg, trigger=trigger)
        _log(engine.summarise(report))
    except Exception as ex:
        _log(["{} hook '{}' failed: {}".format(APP_NAME, trigger, ex)])
