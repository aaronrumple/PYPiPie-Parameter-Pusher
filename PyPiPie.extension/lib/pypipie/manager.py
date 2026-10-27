# -*- coding: utf-8 -*-
"""Mappings report/manager: review, enable/disable, delete, edit, import/export, push."""
import os

from System.Windows import Thickness, Visibility
from System.Windows.Controls import Button, SelectionMode, TextBlock

from pyrevit import forms

from pypipie import revitutil as ru
from pypipie import convert as cv
from pypipie import relations
from pypipie import storage
from pypipie import engine
from pypipie import ui
from pypipie import rules
from pypipie.rule_editor import edit_rule

BADGE_BRUSH = {cv.EXACT: "Good", cv.CONVERT: "Accent", cv.LOSSY: "Warn", cv.INCOMPATIBLE: "Bad"}

_BODY = u'''
<Grid>
  <Grid.RowDefinitions>
    <RowDefinition Height="Auto"/>
    <RowDefinition Height="*"/>
    <RowDefinition Height="Auto"/>
    <RowDefinition Height="Auto"/>
    <RowDefinition Height="Auto"/>
  </Grid.RowDefinitions>

  <StackPanel Margin="0,0,0,6">
    <TextBlock Text="Parameter mappings" FontSize="17" FontWeight="SemiBold"/>
    <TextBlock x:Name="sub_tb" Style="{StaticResource Caption}"/>
  </StackPanel>

  <Grid Grid.Row="1">
    <Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="*"/></Grid.RowDefinitions>
    <TextBlock Style="{StaticResource Caption}" Text="MAPPINGS  ·  tick to enable, select to see pairs (Ctrl/Shift for several)"/>
    <ListBox x:Name="maps_list" Grid.Row="1"/>
  </Grid>

  <StackPanel Grid.Row="2">
    <TextBlock x:Name="pairs_caption" Style="{StaticResource Caption}" Text="PARAMETER PAIRS"/>
    <ListBox x:Name="pairs_list" Height="170"/>
  </StackPanel>

  <StackPanel Grid.Row="3" Margin="0,8,0,0">
    <TextBlock Style="{StaticResource Caption}" Text="RUN AUTOMATICALLY"/>
    <WrapPanel>
      <CheckBox x:Name="on_save_cb" Content="On save" Margin="0,0,18,4"/>
      <CheckBox x:Name="on_sync_cb" Content="On sync with central" Margin="0,0,18,4"/>
      <CheckBox x:Name="on_print_cb" Content="Before print" Margin="0,0,18,4"/>
      <CheckBox x:Name="on_export_cb" Content="Before export" Margin="0,0,18,4"/>
      <CheckBox x:Name="push_empty_cb" Content="Clear text/element targets when the source is empty" Margin="0,0,18,4"/>
    </WrapPanel>
  </StackPanel>

  <Grid Grid.Row="4" Margin="0,12,0,0">
    <Grid.ColumnDefinitions><ColumnDefinition Width="Auto"/><ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/></Grid.ColumnDefinitions>
    <StackPanel Orientation="Horizontal">
      <Button x:Name="new_b" Content="New…" Margin="0"/>
      <Button x:Name="edit_b" Content="Edit…"/>
      <Button x:Name="del_b" Content="Delete"/>
      <Button x:Name="import_b" Content="Import…" Margin="16,0,0,0"/>
      <Button x:Name="export_b" Content="Export…"/>
      <Button x:Name="push_sel_b" Content="Push selected" Margin="16,0,0,0"/>
      <Button x:Name="push_all_b" Content="Push all enabled"/>
    </StackPanel>
    <TextBlock x:Name="status_tb" Grid.Column="1" Margin="12,0" VerticalAlignment="Center" TextWrapping="Wrap"/>
    <StackPanel Grid.Column="2" Orientation="Horizontal">
      <Button x:Name="save_b" Content="Save" Style="{StaticResource Primary}"/>
      <Button x:Name="close_b" Content="Close"/>
    </StackPanel>
  </Grid>
</Grid>'''


def _check_mapping(doc, m, ro_cache=None):
    """Quick health check: returns a list of problems (strings)."""
    issues = []
    if ru.category_from_key(doc, m.get("cat_a")) is None:
        issues.append(u"category A '{}' missing".format(m.get("cat_a_name")))
    if ru.category_from_key(doc, m.get("cat_b")) is None:
        issues.append(u"category B '{}' missing".format(m.get("cat_b_name")))
    rel = relations.BY_KEY.get(m.get("relation"))
    if rel is None:
        issues.append("unknown relation")
    else:
        err = rel.validate(m.get("cat_a"), m.get("cat_b"))
        if err:
            issues.append(err)
    if not m.get("pairs"):
        issues.append("no pairs")
    elif any(relations.is_self_pair(m.get("relation"), p["src"], p["dst"]) for p in m["pairs"]):
        issues.append("a parameter is paired with itself on the same element")
    if m.get("cat_b") and ru.category_from_key(doc, m.get("cat_b")) is not None:
        ro_cache = ro_cache if ro_cache is not None else {}
        if m["cat_b"] not in ro_cache:
            ro_cache[m["cat_b"]] = set(ru.ref_key(r) for r in ru.gather_params(doc, m["cat_b"])[0]
                                       if r.get("ro"))
        ro_now = ro_cache[m["cat_b"]]
        for p in m.get("pairs", []):
            if ru.ref_key(p["dst"]) in ro_now:
                issues.append(u"target '{}' is read-only".format(ru.ref_label(p["dst"])))
    for p in m.get("pairs", []):
        code = (p.get("rule") or "").strip()
        if code:
            try:
                rules.check(code)
            except rules.RuleError as ex:
                issues.append(u"rule on '{}': {}".format(ru.ref_label(p["dst"]), ex.args[0]))
        elif cv.classify(p["src"], p["dst"])[0] == cv.INCOMPATIBLE:
            issues.append(u"'{}' needs a rule".format(ru.ref_label(p["dst"])))
    return issues


class ManagerWindow(ui.ThemedWindow):
    def __init__(self, doc, cfg, allow_new=True):
        ui.ThemedWindow.__init__(self, _BODY, "Mappings", width=980, height=760, min_w=760, min_h=560,
                                 help_topic="mappings")
        self.doc = doc
        self.cfg = storage.clone(cfg)
        self.saved = False
        self.dirty = False
        self._ro_cache = {}  # category -> read-only target keys (health check)
        self.maps_list.SelectionMode = SelectionMode.Extended

        s = self.cfg["settings"]
        for name in ("on_save", "on_sync", "on_print", "on_export", "push_empty"):
            cb = getattr(self, name + "_cb")
            cb.IsChecked = bool(s.get(name))
            cb.Checked += self._on_setting
            cb.Unchecked += self._on_setting

        self.maps_list.SelectionChanged += lambda s_, e: self._refresh_pairs()
        self.maps_list.MouseDoubleClick += lambda s_, e: self._edit()
        self.new_b.Click += lambda s_, e: self._new()
        self.edit_b.Click += lambda s_, e: self._edit()
        self.del_b.Click += lambda s_, e: self._delete()
        self.import_b.Click += lambda s_, e: self._import()
        self.export_b.Click += lambda s_, e: self._export()
        self.push_sel_b.Click += lambda s_, e: self._push(selected=True)
        self.push_all_b.Click += lambda s_, e: self._push(selected=False)
        self.save_b.Click += lambda s_, e: self._save()
        self.close_b.Click += lambda s_, e: self.Close()
        self.Closing += self._on_closing
        if not allow_new:
            self.new_b.Visibility = Visibility.Collapsed

        self._refresh_maps()

    # ------------------------------------------------------------------ helpers
    def _status(self, text, brush="Sub"):
        self.status_tb.Text = text
        self.status_tb.SetResourceReference(TextBlock.ForegroundProperty, brush)

    def _mark_dirty(self):
        self.dirty = True
        self._status("Unsaved changes", "Warn")

    def _selected(self):
        return [it.Tag for it in self.maps_list.SelectedItems]

    def _on_setting(self, sender, args):
        for name in ("on_save", "on_sync", "on_print", "on_export", "push_empty"):
            self.cfg["settings"][name] = bool(getattr(self, name + "_cb").IsChecked)
        self._mark_dirty()

    # ------------------------------------------------------------------ lists
    def _refresh_maps(self, keep_ids=None):
        keep_ids = keep_ids if keep_ids is not None else [m["id"] for m in self._selected()]
        self.maps_list.Items.Clear()
        maps = self.cfg["mappings"]
        enabled = sum(1 for m in maps if m.get("enabled", True))
        self.sub_tb.Text = u"{} mapping(s), {} enabled  ·  stored in '{}' (Extensible Storage)".format(
            len(maps), enabled, self.doc.Title)
        for m in maps:
            def toggle(s_, e, m=m):
                m["enabled"] = bool(s_.IsChecked)
                self._mark_dirty()
                self._refresh_counts()

            rel = relations.BY_KEY.get(m.get("relation"))
            issues = _check_mapping(self.doc, m, self._ro_cache)
            n_on = sum(1 for p in m.get("pairs", []) if p.get("enabled", True))
            sub = u"{} → {}  ·  {}".format(
                m.get("cat_a_name"), m.get("cat_b_name"), rel.label if rel else m.get("relation"))
            if m.get("relation") == "key":
                o = m.get("relation_opts") or {}
                sub += u"  ({} = {})".format(ru.ref_label(o.get("key_a") or {}), ru.ref_label(o.get("key_b") or {}))
            row = ui.columns([
                ui.checkbox(m.get("enabled", True), toggle, "Enable / disable this mapping"),
                ui.two_line(m.get("name", "?"), sub),
                ui.tb(u"{}/{} pairs".format(n_on, len(m.get("pairs", []))), "Sub", margin=(8, 0, 8, 0)),
                ui.tb(u"⚠ " + "; ".join(issues), "Bad", size=11) if issues else ui.tb(u"✓ ok", "Good", size=11),
            ], [26, "3*", 80, "2*"])
            it = ui.lb_item(row, m, "; ".join(issues) if issues else None)
            self.maps_list.Items.Add(it)
            if m["id"] in keep_ids:
                it.IsSelected = True
        if self.maps_list.SelectedItems.Count == 0 and self.maps_list.Items.Count:
            self.maps_list.SelectedIndex = 0
        self._refresh_pairs()

    def _refresh_counts(self):
        maps = self.cfg["mappings"]
        enabled = sum(1 for m in maps if m.get("enabled", True))
        self.sub_tb.Text = u"{} mapping(s), {} enabled  ·  stored in '{}' (Extensible Storage)".format(
            len(maps), enabled, self.doc.Title)

    def _refresh_pairs(self):
        self.pairs_list.Items.Clear()
        sel = self._selected()
        if len(sel) != 1:
            self.pairs_caption.Text = "PARAMETER PAIRS  ·  select one mapping"
            return
        m = sel[0]
        self.pairs_caption.Text = u"PARAMETER PAIRS  ·  {}".format(m.get("name"))
        for p in list(m.get("pairs", [])):
            level = p.get("level") or cv.classify(p["src"], p["dst"])[0]

            def toggle(s_, e, p=p):
                p["enabled"] = bool(s_.IsChecked)
                self._mark_dirty()

            rm = Button()
            rm.Content = u"✕"
            rm.MinWidth = 28
            rm.Height = 24
            rm.Padding = Thickness(4, 0, 4, 0)
            rm.ToolTip = "Delete this pair"
            rm.Click += (lambda s_, e, m=m, p=p: self._delete_pair(m, p))
            reason = cv.classify(p["src"], p["dst"])[1]
            code = (p.get("rule") or "").strip()
            has_rule = bool(code)
            if has_rule:
                first = [l for l in code.splitlines() if l.strip() and not l.strip().startswith("#")]
                reason = u"rule: " + (first[0].strip() if first else u"(comments only)") + \
                    (u" \u2026" if len(first) > 1 else u"")
            fx = ui.small_button(u"\u0192", "Edit rule" if has_rule else "Add a rule that transforms the value",
                                 lambda s_, e, m=m, p=p: self._edit_rule(m, p), accent=has_rule)
            fx.Margin = Thickness(0, 0, 4, 0)
            row = ui.columns([
                ui.checkbox(p.get("enabled", True), toggle, "Enable / disable this pair"),
                ui.two_line(u"{}  →  {}".format(ru.ref_label(p["src"]), ru.ref_label(p["dst"])), reason),
                ui.tb(cv.RULE_LABEL if has_rule else cv.LEVEL_LABEL[level],
                      "Accent" if has_rule else BADGE_BRUSH[level], size=11, margin=(8, 0, 8, 0)),
                fx, rm], [26, "*", "auto", "auto", "auto"])
            self.pairs_list.Items.Add(ui.lb_item(row, p, code or None))

    def _edit_rule(self, m, p):
        level = cv.classify(p["src"], p["dst"])[0]
        code = edit_rule(self.doc, p, m, require_rule=(level == cv.INCOMPATIBLE))
        if code is None:
            return
        p["rule"] = code
        self._mark_dirty()
        self._refresh_maps(keep_ids=[m["id"]])

    def _delete_pair(self, m, p):
        if p in m["pairs"]:
            m["pairs"].remove(p)
        self._mark_dirty()
        self._refresh_maps(keep_ids=[m["id"]])

    # ------------------------------------------------------------------ actions
    def _new(self):
        from pypipie.mapper import MapperWindow
        w = MapperWindow(self.doc, self.cfg, persist=False)
        w.ShowDialog()
        if w.changed:
            self._mark_dirty()
            self._refresh_maps(keep_ids=[self.cfg["mappings"][-1]["id"]])

    def _edit(self):
        sel = self._selected()
        if len(sel) != 1:
            self._status("Select one mapping to edit.", "Warn")
            return
        from pypipie.mapper import MapperWindow
        w = MapperWindow(self.doc, self.cfg, persist=False, edit_mapping=sel[0])
        w.ShowDialog()
        if w.changed:
            self._mark_dirty()
            self._refresh_maps(keep_ids=[sel[0]["id"]])

    def _delete(self):
        sel = self._selected()
        if not sel:
            return
        names = u"\n".join(u"• " + m.get("name", "?") for m in sel[:12])
        if ui.ask(u"Delete {} mapping(s)?\n\n{}".format(len(sel), names), "Delete mappings",
                  ("Delete", "Cancel")) != "Delete":
            return
        ids = set(m["id"] for m in sel)
        self.cfg["mappings"] = [m for m in self.cfg["mappings"] if m["id"] not in ids]
        self._mark_dirty()
        self._refresh_maps(keep_ids=[])

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
        path = forms.save_file(file_ext="json", default_name="PyPiPie_mappings")
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
        n_rules = sum(1 for m in incoming["mappings"] for p in m.get("pairs", []) if (p.get("rule") or "").strip())
        if n_rules:
            msg += (u"\n{} pair(s) carry rule scripts. Rules run in a restricted sandbox, but review them "
                    u"(\u0192 buttons) before saving.".format(n_rules))
        msg += (u"\n\nMerge adds them (same mapping id replaces the existing one).\n"
                u"Replace removes all current mappings first.")
        res = ui.ask(msg, "Import mappings", ("Merge", "Replace all", "Cancel"))
        if res not in ("Merge", "Replace all"):
            return
        take = ui.ask("Also take the automatic-run settings from the file?", "Import settings",
                      ("Keep mine", "Use file's")) == "Use file's"
        storage.merge(self.cfg, incoming, replace=(res == "Replace all"), take_settings=take)
        if take:
            for name in ("on_save", "on_sync", "on_print", "on_export", "push_empty"):
                getattr(self, name + "_cb").IsChecked = bool(self.cfg["settings"].get(name))
        self._mark_dirty()
        self._refresh_maps(keep_ids=[m["id"] for m in incoming["mappings"]])
        self._status(u"Imported {} mapping(s) - Save to keep them in the project.".format(n), "Warn")

    def _push(self, selected):
        ids = None
        if selected:
            sel = self._selected()
            if not sel:
                self._status("Select mapping(s) to push.", "Warn")
                return
            ids = [m["id"] for m in sel]
        report = engine.run(self.doc, self.cfg, trigger="manual", mapping_ids=ids)
        ui.show_push_report(report)

    def _save(self):
        try:
            self.cfg = storage.save(self.doc, self.cfg)
        except Exception as ex:
            ui.alert(u"Could not save mappings to the project:\n{}".format(ex), "Save failed")
            return
        self.saved = True
        self.dirty = False
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
