# -*- coding: utf-8 -*-
"""Mappings window: every mapping with its pairs in one scrolling list.

Each mapping row: expand, enable, name/categories/relationship, pair count, health,
Edit / Push / Delete. Each pair row: enable, parameters, conversion, rule (ƒ), delete.
Below the list: automatic-run settings and project options; footer: New, Import, Export,
Push all, Save, Close.
"""
import os

from System.Windows import FontWeights, Thickness, Visibility
from System.Windows.Controls import Border, SelectionMode, StackPanel, TextBlock
from System.Windows.Media import Brushes

from pyrevit import forms

from pypipie import revitutil as ru
from pypipie import convert as cv
from pypipie import relations
from pypipie import storage
from pypipie import engine
from pypipie import ui

BADGE_BRUSH = {cv.EXACT: "Good", cv.CONVERT: "Accent", cv.LOSSY: "Warn", cv.INCOMPATIBLE: "Bad"}
AUTO_EXPAND_MAX = 6          # mappings with more pairs start collapsed
SETTINGS = ("on_save", "on_sync", "on_print", "on_export", "push_empty", "rules_enabled")

_BODY = u'''
<Grid>
  <Grid.RowDefinitions>
    <RowDefinition Height="Auto"/>
    <RowDefinition Height="Auto"/>
    <RowDefinition Height="*"/>
    <RowDefinition Height="Auto"/>
    <RowDefinition Height="Auto"/>
  </Grid.RowDefinitions>

  <StackPanel Margin="0,0,40,8">
    <TextBlock Text="Parameter mappings" FontSize="17" FontWeight="SemiBold"/>
    <TextBlock x:Name="sub_tb" Style="{StaticResource Caption}"/>
  </StackPanel>

  <Grid Grid.Row="1" Margin="0,0,0,6">
    <Grid.ColumnDefinitions>
      <ColumnDefinition Width="260"/><ColumnDefinition Width="Auto"/><ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/>
    </Grid.ColumnDefinitions>
    <Grid>
      <TextBox x:Name="filter_tb" ToolTip="Filter by mapping name, category or parameter"/>
      <TextBlock x:Name="filter_hint" Text="Filter mappings…" IsHitTestVisible="False" Margin="8,0,0,0"
                 VerticalAlignment="Center" Foreground="{DynamicResource Sub}"/>
    </Grid>
    <StackPanel Grid.Column="1" Orientation="Horizontal" Margin="8,0,0,0">
      <Button x:Name="expand_b" Content="Expand all"/>
      <Button x:Name="collapse_b" Content="Collapse all"/>
      <Button x:Name="merge_b" Content="Merge duplicates" Margin="12,0,0,0" Visibility="Collapsed"
              ToolTip="Combine mappings that share the same categories and relationship into one"/>
    </StackPanel>
    <TextBlock Grid.Column="2" Style="{StaticResource Caption}" Margin="12,0" VerticalAlignment="Center"
               TextTrimming="CharacterEllipsis"
               Text="Ctrl/Shift-click rows to select several (Export, Delete key)"/>
    <Button x:Name="new_b" Grid.Column="3" Content="New mapping…" Style="{StaticResource Primary}" MinWidth="120"/>
  </Grid>

  <Grid Grid.Row="2">
    <ListBox x:Name="maps_list" ScrollViewer.CanContentScroll="False"
             ScrollViewer.VerticalScrollBarVisibility="Auto" Padding="0"/>
    <TextBlock x:Name="empty_tb" HorizontalAlignment="Center" VerticalAlignment="Center" TextAlignment="Center"
               Foreground="{DynamicResource Sub}" Visibility="Collapsed"
               Text="No mappings in this project yet.&#x0a;Click New mapping… to create one."/>
  </Grid>

  <Border Grid.Row="3" Margin="0,8,0,0" Padding="10,6" Background="{DynamicResource Header}"
          BorderBrush="{DynamicResource Border}" BorderThickness="1" CornerRadius="4">
    <WrapPanel>
      <TextBlock Style="{StaticResource Caption}" Text="RUN AUTOMATICALLY" Margin="0,0,12,0" VerticalAlignment="Center"/>
      <CheckBox x:Name="on_save_cb" Content="On save" Margin="0,3,16,3"/>
      <CheckBox x:Name="on_sync_cb" Content="On sync" Margin="0,3,16,3"/>
      <CheckBox x:Name="on_print_cb" Content="Before print" Margin="0,3,16,3"/>
      <CheckBox x:Name="on_export_cb" Content="Before export" Margin="0,3,28,3"/>
      <TextBlock Style="{StaticResource Caption}" Text="OPTIONS" Margin="0,0,12,0" VerticalAlignment="Center"/>
      <CheckBox x:Name="push_empty_cb" Content="Clear targets when source is empty" Margin="0,3,16,3"
                ToolTip="Off: an empty source leaves the target as it is. On: text and element targets are cleared (numbers never are)."/>
      <CheckBox x:Name="rules_enabled_cb" Content="Mapping rules (ƒ)" Margin="0,3,16,3"
                ToolTip="Allow pairs to carry Python rules. Off: rules are kept but never run, ƒ buttons are hidden on pairs without a rule, and the rule engine isn't loaded at all."/>
    </WrapPanel>
  </Border>

  <Grid Grid.Row="4" Margin="0,10,0,0">
    <Grid.ColumnDefinitions><ColumnDefinition Width="Auto"/><ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/></Grid.ColumnDefinitions>
    <StackPanel Orientation="Horizontal">
      <Button x:Name="import_b" Content="Import…" Margin="0"/>
      <Button x:Name="export_b" Content="Export…"/>
      <Button x:Name="push_all_b" Content="Push all enabled" Margin="16,0,0,0"/>
    </StackPanel>
    <TextBlock x:Name="status_tb" Grid.Column="1" Margin="12,0" VerticalAlignment="Center" TextWrapping="Wrap"/>
    <StackPanel Grid.Column="2" Orientation="Horizontal">
      <Button x:Name="save_b" Content="Save" Style="{StaticResource Primary}"/>
      <Button x:Name="close_b" Content="Close"/>
    </StackPanel>
  </Grid>
</Grid>'''


def _first_code_line(code):
    lines = [l.strip() for l in code.splitlines() if l.strip() and not l.strip().startswith("#")]
    if not lines:
        return u"(comments only)"
    return lines[0] + (u" …" if len(lines) > 1 else u"")


class _Health(object):
    """Mapping health checks with caches, so a long list stays quick to redraw."""

    def __init__(self, doc):
        self.doc = doc
        self.ro = {}        # cat_b -> read-only target keys
        self.rule_err = {}  # code -> error text or None

    def _rule_error(self, code):
        if code not in self.rule_err:
            from pypipie import rules  # only loaded when a rule exists
            try:
                rules.check(code)
                self.rule_err[code] = None
            except rules.RuleError as ex:
                self.rule_err[code] = ex.args[0]
        return self.rule_err[code]

    def issues(self, m, settings):
        doc = self.doc
        out = []
        if ru.category_from_key(doc, m.get("cat_a")) is None:
            out.append(u"category A '{}' missing".format(m.get("cat_a_name")))
        cat_b_ok = ru.category_from_key(doc, m.get("cat_b")) is not None
        if not cat_b_ok:
            out.append(u"category B '{}' missing".format(m.get("cat_b_name")))
        rel = relations.BY_KEY.get(m.get("relation"))
        if rel is None:
            out.append("unknown relationship")
        else:
            err = rel.validate(m.get("cat_a"), m.get("cat_b"))
            if err:
                out.append(err)
        pairs = m.get("pairs", [])
        if not pairs:
            out.append("no pairs")
        if cat_b_ok:
            if m["cat_b"] not in self.ro:
                self.ro[m["cat_b"]] = set(ru.ref_key(r) for r in ru.gather_params(doc, m["cat_b"])[0]
                                          if r.get("ro"))
        fed = {}
        for p in pairs:
            if p.get("enabled", True):
                fed.setdefault(ru.ref_key(p["dst"]), []).append(p)
        for ps in fed.values():
            if len(ps) > 1:
                out.append(u"'{}' is fed by {} enabled pairs ({}) – the last one wins; switch one off".format(
                    ru.ref_label(ps[0]["dst"]), len(ps), u", ".join(ru.ref_label(q["src"]) for q in ps)))
        for p in pairs:
            label = ru.ref_label(p["dst"])
            if relations.is_self_pair(m.get("relation"), p["src"], p["dst"]):
                out.append(u"'{}' is paired with itself on the same element".format(label))
            if cat_b_ok and ru.ref_key(p["dst"]) in self.ro[m["cat_b"]]:
                out.append(u"target '{}' is read-only".format(label))
            state = storage.rule_state(settings, p)
            if state == storage.RULE_ON:
                err = self._rule_error(p["rule"].strip())
                if err:
                    out.append(u"rule on '{}': {}".format(label, err))
            elif cv.classify(p["src"], p["dst"])[0] == cv.INCOMPATIBLE and p.get("enabled", True):
                out.append({storage.RULE_NONE: u"'{}' needs a rule",
                            storage.RULE_OFF: u"'{}' needs its rule, which is switched off",
                            storage.RULE_GLOBAL_OFF: u"'{}' needs its rule; mapping rules are off"}
                           [state].format(label))
        return out


class ManagerWindow(ui.ThemedWindow):
    def __init__(self, doc, cfg, allow_new=True):
        ui.ThemedWindow.__init__(self, _BODY, "Mappings", width=1060, height=780, min_w=820, min_h=520,
                                 help_topic="mappings")
        self.doc = doc
        self.cfg = storage.clone(cfg)
        self.saved = False
        self.dirty = False
        self.health = _Health(doc)
        self.items = {}      # mapping id -> ListBoxItem
        self.expanded = {}   # mapping id -> bool
        self.maps_list.SelectionMode = SelectionMode.Extended

        s = self.cfg["settings"]
        for name in SETTINGS:
            cb = getattr(self, name + "_cb")
            cb.IsChecked = bool(s.get(name))
            cb.Checked += self._on_setting
            cb.Unchecked += self._on_setting

        self.filter_tb.TextChanged += lambda s_, e: self._apply_filter()
        self.expand_b.Click += lambda s_, e: self._expand_all(True)
        self.collapse_b.Click += lambda s_, e: self._expand_all(False)
        self.merge_b.Click += lambda s_, e: self._merge_duplicates()
        self.maps_list.KeyDown += self._on_key
        self.new_b.Click += lambda s_, e: self._new()
        self.import_b.Click += lambda s_, e: self._import()
        self.export_b.Click += lambda s_, e: self._export()
        self.push_all_b.Click += lambda s_, e: self._push(None)
        self.save_b.Click += lambda s_, e: self._save()
        self.close_b.Click += lambda s_, e: self.Close()
        self.Closing += self._on_closing
        if not allow_new:
            self.new_b.Visibility = Visibility.Collapsed

        self._rebuild()
        dups = storage.duplicate_groups(self.cfg)
        if dups:
            self._status(u"{} category pairing(s) are split over several mappings – "
                         u"Merge duplicates combines them.".format(len(dups)), "Accent")

    # ------------------------------------------------------------------ helpers
    @property
    def settings(self):
        return self.cfg["settings"]

    def _status(self, text, brush="Sub"):
        self.status_tb.Text = text
        self.status_tb.SetResourceReference(TextBlock.ForegroundProperty, brush)

    def _mark_dirty(self, text=u"Unsaved changes"):
        self.dirty = True
        self._status(text, "Warn")

    def _selected(self):
        return [it.Tag for it in self.maps_list.SelectedItems]

    def _summary(self):
        maps = self.cfg["mappings"]
        enabled = sum(1 for m in maps if m.get("enabled", True))
        n_pairs = sum(len(m.get("pairs", [])) for m in maps)
        n_rules = sum(1 for m in maps for p in m.get("pairs", []) if storage.has_rule(p))
        txt = u"{} mapping(s), {} enabled  ·  {} pair(s)".format(len(maps), enabled, n_pairs)
        if n_rules:
            txt += u"  ·  {} rule(s){}".format(n_rules, u"" if self.settings.get("rules_enabled")
                                                    else u" (rules off)")
        txt += u"  ·  stored in '{}'".format(self.doc.Title)
        self.sub_tb.Text = txt
        self.empty_tb.Visibility = Visibility.Collapsed if maps else Visibility.Visible
        dups = storage.duplicate_groups(self.cfg)
        self.merge_b.Visibility = Visibility.Visible if dups else Visibility.Collapsed
        self.merge_b.Content = u"Merge duplicates ({})".format(sum(len(g) - 1 for g in dups))

    def _sync_boxes(self):
        for name in SETTINGS:
            cb = getattr(self, name + "_cb")
            if bool(cb.IsChecked) != bool(self.settings.get(name)):
                cb.IsChecked = bool(self.settings.get(name))  # fires _on_setting

    def _on_setting(self, sender, args):
        before = self.settings.get("rules_enabled")
        for name in SETTINGS:
            self.settings[name] = bool(getattr(self, name + "_cb").IsChecked)
        if before != self.settings.get("rules_enabled"):
            self._rebuild()
            self._mark_dirty(u"Mapping rules turned {} – unsaved".format(
                "on" if self.settings["rules_enabled"] else "off (rules are kept, not run)"))
        else:
            self._mark_dirty()

    # ------------------------------------------------------------------ list
    def _rebuild(self, select_ids=None):
        keep = set(select_ids if select_ids is not None else [m["id"] for m in self._selected()])
        self.maps_list.Items.Clear()
        self.items = {}
        for m in self.cfg["mappings"]:
            it = ui.lb_item(self._card(m), m)
            it.Padding = Thickness(0)
            self.items[m["id"]] = it
            self.maps_list.Items.Add(it)
            if m["id"] in keep:
                it.IsSelected = True
        self._summary()
        self._apply_filter()

    def _redraw(self, m):
        it = self.items.get(m["id"])
        if it is not None:
            it.Content = self._card(m)
        self._summary()

    def _card(self, m):
        pairs = m.get("pairs", [])
        issues = self.health.issues(m, self.settings)
        expanded = self.expanded.get(m["id"], len(pairs) <= AUTO_EXPAND_MAX)
        rel = relations.BY_KEY.get(m.get("relation"))

        def toggle_map(s_, e, m=m):
            m["enabled"] = bool(s_.IsChecked)
            self._mark_dirty()
            self._summary()

        rel_txt = rel.label if rel else m.get("relation")
        if m.get("name") == storage.default_name(m):
            sub = rel_txt  # the name already says A -> B
        else:
            sub = u"{} → {}  ·  {}".format(m.get("cat_a_name"), m.get("cat_b_name"), rel_txt)
        if m.get("relation") == "key":
            o = m.get("relation_opts") or {}
            sub += u"  ({} = {})".format(ru.ref_label(o.get("key_a") or {}), ru.ref_label(o.get("key_b") or {}))
        n_on = sum(1 for p in pairs if p.get("enabled", True))
        n_rules = sum(1 for p in pairs if storage.rule_active(self.settings, p))
        count = u"{}/{} pairs".format(n_on, len(pairs)) + (u"  ·  ƒ {}".format(n_rules) if n_rules else u"")

        title = ui.two_line(m.get("name", "?"), sub)
        title.Children[0].FontWeight = FontWeights.SemiBold
        title.Children[0].FontSize = 13
        title.Background = Brushes.Transparent  # whole area double-clickable
        title.MouseLeftButtonDown += lambda s_, e, m=m: self._edit(m) if e.ClickCount == 2 else None
        title.ToolTip = u"Double-click to edit"
        health = ui.tb(u"⚠ {} issue{}".format(len(issues), "" if len(issues) == 1 else "s"), "Bad", size=11) \
            if issues else ui.tb(u"✓ ok", "Good", size=11)
        if issues:
            health.ToolTip = u"\n".join(issues)

        header = ui.columns([
            ui.icon_button(u"▾" if expanded else u"▸", "Show / hide pairs",
                           lambda m=m: self._toggle_expand(m), width=26),
            ui.checkbox(m.get("enabled", True), toggle_map, "Enable / disable this mapping"),
            title,
            ui.tb(count, "Sub", margin=(8, 0, 12, 0)),
            health,
            ui.icon_button(u"Edit…", "Add, remove or change pairs; change categories or relationship",
                           lambda m=m: self._edit(m), width=56),
            ui.icon_button("Push", "Push this mapping now (uses what's shown here, even if unsaved)",
                           lambda m=m: self._push([m["id"]]), width=50),
            ui.icon_button(u"✕", "Delete this mapping", lambda m=m: self._delete([m])),
        ], [28, 26, "*", "auto", 90, "auto", "auto", "auto"])
        header.Children[0].Margin = Thickness(0)
        header.Children[4].Margin = Thickness(0, 0, 4, 0)

        body = StackPanel()
        body.Margin = Thickness(54, 4, 0, 2)
        body.Visibility = Visibility.Visible if expanded else Visibility.Collapsed
        for p in pairs:
            body.Children.Add(self._pair_row(m, p))
        for msg in issues:
            body.Children.Add(ui.tb(u"⚠ " + msg, "Bad", size=11, margin=(4, 2, 0, 0), wrap=True))

        stack = StackPanel()
        stack.Children.Add(header)
        stack.Children.Add(body)
        card = Border()
        card.Child = stack
        card.Padding = Thickness(4, 6, 4, 6)
        card.BorderThickness = Thickness(0, 0, 0, 1)
        card.SetResourceReference(Border.BorderBrushProperty, "Border")
        if not m.get("enabled", True):
            stack.Opacity = 0.6
        return card

    def _pair_row(self, m, p):
        level, reason = cv.classify(p["src"], p["dst"])
        state = storage.rule_state(self.settings, p)

        def toggle_pair(s_, e, m=m, p=p):
            p["enabled"] = bool(s_.IsChecked)
            self._mark_dirty()
            self._redraw(m)

        if state == storage.RULE_ON:
            reason = u"rule: " + _first_code_line(p["rule"])
            badge = ui.tb(cv.RULE_LABEL, "Accent", size=11, margin=(8, 0, 8, 0))
        else:
            if state != storage.RULE_NONE:
                reason = u"rule {} · {}".format("off" if state == storage.RULE_OFF else "not run (rules off)",
                                                     reason)
            if level == cv.INCOMPATIBLE:
                badge = ui.tb(u"✕ needs rule", "Bad", size=11, margin=(8, 0, 8, 0))
            else:
                badge = ui.tb(cv.LEVEL_LABEL[level], BADGE_BRUSH[level], size=11, margin=(8, 0, 8, 0))

        fx = None
        if self.settings.get("rules_enabled") or state != storage.RULE_NONE:
            fx = ui.rule_button(self, state,
                                on_edit=lambda m=m, p=p: self._edit_rule(m, p),
                                on_toggle=lambda m=m, p=p: self._toggle_rule(m, p),
                                on_remove=lambda m=m, p=p: self._remove_rule(m, p))
        sw = None
        if state != storage.RULE_NONE:
            sw = ui.rule_toggle(state, lambda m=m, p=p: self._toggle_rule(m, p))
        row = ui.columns([
            ui.checkbox(p.get("enabled", True), toggle_pair, "Enable / disable this pair"),
            ui.two_line(u"{}  →  {}".format(ru.ref_label(p["src"]), ru.ref_label(p["dst"])), reason),
            badge,
            sw,
            fx,
            ui.icon_button(u"✕", "Delete this pair", lambda m=m, p=p: self._delete_pair(m, p)),
        ], [26, "*", "auto", "auto", "auto", "auto"])
        row.Margin = Thickness(0, 1, 0, 1)
        if not p.get("enabled", True):
            row.Opacity = 0.55
        return row

    # ------------------------------------------------------------------ filter / expand
    def _apply_filter(self):
        q = (self.filter_tb.Text or u"").strip().lower()
        self.filter_hint.Visibility = Visibility.Collapsed if q else Visibility.Visible
        shown = 0
        for m in self.cfg["mappings"]:
            it = self.items.get(m["id"])
            if it is None:
                continue
            hay = [m.get("name", ""), m.get("cat_a_name", ""), m.get("cat_b_name", "")]
            for p in m.get("pairs", []):
                hay += [p["src"].get("name", ""), p["dst"].get("name", "")]
            hit = (not q) or any(q in (h or u"").lower() for h in hay)
            it.Visibility = Visibility.Visible if hit else Visibility.Collapsed
            shown += 1 if hit else 0
        if q:
            self._status(u"{} of {} mapping(s) match".format(shown, len(self.cfg["mappings"])))

    def _toggle_expand(self, m):
        pairs = m.get("pairs", [])
        self.expanded[m["id"]] = not self.expanded.get(m["id"], len(pairs) <= AUTO_EXPAND_MAX)
        self._redraw(m)

    def _expand_all(self, state):
        for m in self.cfg["mappings"]:
            self.expanded[m["id"]] = state
        self._rebuild()

    def _on_key(self, sender, args):
        key = str(args.Key)
        if key == "Delete" and self._selected():
            args.Handled = True
            self._delete(self._selected())
        elif key in ("Return", "Enter") and len(self._selected()) == 1:
            args.Handled = True
            self._edit(self._selected()[0])

    # ------------------------------------------------------------------ rules
    def _edit_rule(self, m, p):
        from pypipie.rule_editor import edit_rule
        level = cv.classify(p["src"], p["dst"])[0]
        res = edit_rule(self.doc, p, m, require_rule=(level == cv.INCOMPATIBLE),
                        rules_enabled=bool(self.settings.get("rules_enabled")))
        if res is None:
            return
        p["rule"], p["rule_on"], p["rule_empty"] = res
        self._mark_dirty()
        self._redraw(m)

    def _toggle_rule(self, m, p):
        p["rule_on"] = not p.get("rule_on", True)
        self._mark_dirty(u"Rule {} for {} – unsaved".format("on" if p["rule_on"] else "off",
                                                                 ru.ref_label(p["dst"])))
        self._redraw(m)

    def _remove_rule(self, m, p):
        if ui.ask(u"Remove the rule on {} → {}?".format(ru.ref_label(p["src"]), ru.ref_label(p["dst"])),
                  "Remove rule", ("Remove", "Cancel")) != "Remove":
            return
        p["rule"], p["rule_on"] = u"", True
        self._mark_dirty()
        self._redraw(m)

    # ------------------------------------------------------------------ mapping actions
    def _new(self):
        from pypipie.mapper import MapperWindow
        w = MapperWindow(self.doc, self.cfg, persist=False)
        w.ShowDialog()
        self._sync_boxes()  # the editor may have turned mapping rules on
        if w.changed:
            self._mark_dirty()
            if w.result_id:
                self.expanded[w.result_id] = True
            self._rebuild(select_ids=[w.result_id] if w.result_id else [])
            self._scroll_to(w.result_id)

    def _edit(self, m):
        from pypipie.mapper import MapperWindow
        w = MapperWindow(self.doc, self.cfg, persist=False, edit_mapping=m)
        w.ShowDialog()
        self._sync_boxes()  # the editor may have turned mapping rules on
        if w.changed:
            self._mark_dirty()
            rid = w.result_id or m["id"]
            self._rebuild(select_ids=[rid])
            self._scroll_to(rid)

    def _scroll_to(self, mid):
        it = self.items.get(mid)
        if it is not None:
            self.maps_list.ScrollIntoView(it)

    def _merge_duplicates(self):
        dups = storage.duplicate_groups(self.cfg)
        if not dups:
            return
        lines = []
        for g in dups[:10]:
            rel = relations.BY_KEY.get(g[0].get("relation"))
            lines.append(u"• {} → {} ({}): {} mappings, {} pairs".format(
                g[0].get("cat_a_name"), g[0].get("cat_b_name"), rel.label if rel else g[0].get("relation"),
                len(g), sum(len(m.get("pairs", [])) for m in g)))
        if len(dups) > 10:
            lines.append(u"… and {} more".format(len(dups) - 10))
        if ui.ask(u"Combine mappings that share the same categories and relationship?\n\n{}\n\n"
                  u"Identical pairs are dropped. Nothing else is lost: pairs from disabled mappings, and pairs "
                  u"that would feed an already-fed target, arrive switched off.".format(u"\n".join(lines)),
                  "Merge duplicates", ("Merge", "Cancel")) != "Merge":
            return
        keep = [g[0]["id"] for g in dups]
        removed = storage.consolidate(self.cfg)
        for mid in keep:
            self.expanded[mid] = True
        self._rebuild(select_ids=keep)
        self._mark_dirty(u"Merged {} mapping(s) into {} – unsaved.".format(removed + len(keep), len(keep)))

    def _delete(self, maps):
        if not maps:
            return
        names = u"\n".join(u"• " + m.get("name", "?") for m in maps[:12])
        if len(maps) > 12:
            names += u"\n… and {} more".format(len(maps) - 12)
        if ui.ask(u"Delete {} mapping(s)?\n\n{}".format(len(maps), names), "Delete mappings",
                  ("Delete", "Cancel")) != "Delete":
            return
        ids = set(m["id"] for m in maps)
        self.cfg["mappings"] = [m for m in self.cfg["mappings"] if m["id"] not in ids]
        self._mark_dirty()
        self._rebuild(select_ids=[])

    def _delete_pair(self, m, p):
        if p in m["pairs"]:
            m["pairs"].remove(p)
        self._mark_dirty()
        self._redraw(m)

    def _push(self, ids):
        report = engine.run(self.doc, self.cfg, trigger="manual", mapping_ids=ids)
        ui.show_push_report(report)

    # ------------------------------------------------------------------ import / export
    def _export(self):
        if not self.cfg["mappings"]:
            self._status("Nothing to export.", "Warn")
            return
        sel = self._selected()
        ids = None
        if sel and len(sel) < len(self.cfg["mappings"]):
            res = ui.ask("Export which mappings?", "Export",
                         ("All ({})".format(len(self.cfg["mappings"])), "Selected ({})".format(len(sel)), "Cancel"))
            if res is None or res == "Cancel":
                return
            if res.startswith("Selected"):
                ids = [m["id"] for m in sel]
        path = forms.save_file(file_ext="json", default_name="DataPusher_mappings")
        if not path:
            return
        try:
            n = storage.export_file(self.cfg, path, ids)
            self._status(u"Exported {} mapping(s) to {}".format(n, os.path.basename(path)), "Good")
        except Exception as ex:
            ui.alert(u"Export failed:\n{}".format(ex), "Export")

    def _import(self):
        path = forms.pick_file(file_ext="json")
        if not path:
            return
        try:
            incoming = storage.read_file(path)
        except Exception as ex:
            ui.alert(u"Could not read the file:\n{}".format(ex), "Import")
            return
        n = len(incoming["mappings"])
        missing = sum(1 for m in incoming["mappings"]
                      if ru.category_from_key(self.doc, m.get("cat_a")) is None
                      or ru.category_from_key(self.doc, m.get("cat_b")) is None)
        msg = u"{} mapping(s) in {}.".format(n, os.path.basename(path))
        if missing:
            msg += u"\n{} reference categories that don't exist here (they'll be kept but skipped).".format(missing)
        n_rules = sum(1 for m in incoming["mappings"] for p in m.get("pairs", []) if storage.has_rule(p))
        if n_rules:
            msg += (u"\n{} pair(s) carry rule scripts. Rules run in a restricted sandbox, but review them "
                    u"(ƒ buttons) before saving.".format(n_rules))
            if not self.settings.get("rules_enabled"):
                msg += u" Mapping rules are off in this project, so they won't run until you turn them on."
        msg += (u"\n\nMerge adds them (same mapping id replaces the existing one).\n"
                u"Replace removes all current mappings first.")
        res = ui.ask(msg, "Import mappings", ("Merge", "Replace all", "Cancel"))
        if res not in ("Merge", "Replace all"):
            return
        take = ui.ask("Also take the automatic-run settings and options from the file?", "Import settings",
                      ("Keep mine", "Use file's")) == "Use file's"
        storage.merge(self.cfg, incoming, replace=(res == "Replace all"), take_settings=take)
        if take:
            for name in SETTINGS:
                getattr(self, name + "_cb").IsChecked = bool(self.settings.get(name))
        self._rebuild(select_ids=[m["id"] for m in incoming["mappings"]])
        self._mark_dirty(u"Imported {} mapping(s) – Save to keep them in the project.".format(n))

    # ------------------------------------------------------------------ save / close
    def _save(self):
        try:
            self.cfg = storage.save(self.doc, self.cfg)
        except Exception as ex:
            ui.alert(u"Could not save mappings to the project:\n{}".format(ex), "Save failed")
            return
        self.saved = True
        self.dirty = False
        self._rebuild()  # cfg object was replaced - rebind rows to it
        self._status("Saved to project.", "Good")

    def _on_closing(self, sender, args):
        if not self.dirty:
            return
        res = ui.ask("Save changes to the mappings before closing?", "Unsaved changes",
                     ("Save", "Discard", "Cancel"))
        if res == "Save":
            self._save()
            if self.dirty:
                args.Cancel = True
        elif res == "Discard":
            self.cfg = storage.load(self.doc)
        else:
            args.Cancel = True


def run(doc):
    cfg = storage.load(doc)
    ManagerWindow(doc, cfg).ShowDialog()
