# -*- coding: utf-8 -*-
# PyPiPie parameter pusher - runs enabled mappings (export trigger).
# Must stay silent: any problem is written to %APPDATA%\pyRevit\PyPiPie\push.log
from pypipie.hookrunner import run_hook

run_hook("export")
