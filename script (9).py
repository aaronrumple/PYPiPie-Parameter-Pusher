# -*- coding: utf-8 -*-
"""Pair parameters between two categories and store the mapping in the project."""
__title__ = "Map\nParameters"
__author__ = "Data Pusher"

from pyrevit import revit
from pypipie import mapper

mapper.run(revit.doc)
