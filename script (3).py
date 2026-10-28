# -*- coding: utf-8 -*-
"""Push all enabled parameter mappings now.
Shift+Click: push without showing the results window."""
__title__ = "Push\nNow"
__author__ = "Data Pusher"

from pyrevit import revit, EXEC_PARAMS
from pypipie import storage, engine, ui

doc = revit.doc
cfg = storage.load(doc)
if not any(m.get("enabled", True) for m in cfg["mappings"]):
    if ui.ask("This project has no enabled parameter mappings.", "Push Now",
              ("Create a mapping", "Close")) == "Create a mapping":
        from pypipie import mapper
        mapper.run(doc)
else:
    report = engine.run(doc, cfg, trigger="manual")
    if not EXEC_PARAMS.config_mode:
        ui.show_push_report(report)
