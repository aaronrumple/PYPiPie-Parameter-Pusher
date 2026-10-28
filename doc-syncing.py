# -*- coding: utf-8 -*-
# Data Pusher - runs enabled mappings (sync trigger).
# Must stay silent: any problem is written to %APPDATA%\pyRevit\DataPusher\push.log
from pypipie.hookrunner import run_hook

run_hook("sync")
