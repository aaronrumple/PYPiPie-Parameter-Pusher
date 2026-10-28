# -*- coding: utf-8 -*-
"""Report of all parameter mappings: enable/disable, edit, delete,
import/export to other projects, and automatic-run settings."""
__title__ = "Mappings"
__author__ = "Data Pusher"

from pyrevit import revit
from pypipie import manager

manager.run(revit.doc)
