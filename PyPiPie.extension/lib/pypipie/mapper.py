# -*- coding: utf-8 -*-
"""Mapping editor: pick category A and B, pair parameters, apply, repeat."""
import copy

from System.Windows import Visibility, Thickness
from System.Windows.Controls import Button, TextBlock

from pypipie import revitutil as ru
from pypipie import convert as cv
from pypipie import relations
from pypipie import storage
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
    <RowDefinition Height="Auto"/>
  </Grid.RowDefinitions>

  <!-- header -->
  <Grid Margin="0,0,0,8">
    <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/></Grid.ColumnDefinitions>
    <StackPanel>
      <TextBlock x:Name="title_tb" Text="Parameter Pusher" FontSize="17" FontWeight="SemiBold"/>
      <TextBlock Style="{StaticResource Caption}" TextWrapping="Wrap"
                 Text="Pick a source (A) and target (B) category, pair parameters, then Apply. Repeat for more mappings."/>
    </StackPanel>
    <StackPanel Grid.Column="1" VerticalAlignment="Bottom" Margin="0,0,34,0">
      <TextBlock Style="{StaticResource Caption}" Text="MAPPING NAME (optional)"/>
      <TextBox x:Name="name_tb" Width="280"/>
    </StackPanel>
  </Grid>

  <!-- A and B columns -->
  <Grid Grid.Row="1">
    <Grid.ColumnDefinitions>
      <ColumnDefinition Width="*"/><ColumnDefinition Width="16"/><ColumnDefinition Width="*"/>
    </Grid.ColumnDefinitions>
    <Grid>
      <Grid.RowDefinitions>
        <RowDefinition Height="Auto"/><RowDefinition Height="Auto"/><RowDefinition Height="150"/>
        <RowDefinition Height="Auto"/><RowDefinition Height="Auto"/><RowDefinition Height="*"/>
      </Grid.RowDefinitions>
      <TextBlock Style="{StaticResource Caption}" Text="A  ·  SOURCE CATEGORY" FontWeight="SemiBold"/>
      <TextBox x:Name="cat_a_filter" Grid.Row="1" ToolTip="Filter categories"/>
      <ListBox x:Name="cat_a_list" Grid.Row="2" Margin="0,4,0,0"/>
      <TextBlock x:Name="param_a_caption" Grid.Row="3" Style="{StaticResource Caption}" Text="SOURCE PARAMETERS"/>
      <TextBox x:Name="param_a_filter" Grid.Row="4" ToolTip="Filter parameters"/>
      <ListBox x:Name="param_a_list" Grid.Row="5" Margin="0,4,0,0"/>
    </Grid>
    <Grid Grid.Column="2">
      <Grid.RowDefinitions>
        <RowDefinition Height="Auto"/><RowDefinition Height="Auto"/><RowDefinition Height="150"/>
        <RowDefinition Height="Auto"/><RowDefinition Height="Auto"/><RowDefinition Height="*"/>
      </Grid.RowDefinitions>
      <TextBlock Style="{StaticResource Caption}" Text="B  ·  TARGET CATEGORY" FontWeight="SemiBold"/>
      <TextBox x:Name="cat_b_filter" Grid.Row="1" ToolTip="Filter categories"/>
      <ListBox x:Name="cat_b_list" Grid.Row="2" Margin="0,4,0,0"/>
      <TextBlock x:Name="param_b_caption" Grid.Row="3" Style="{StaticResource Caption}" Text="TARGET PARAMETERS (writable)"/>
      <TextBox x:Name="param_b_filter" Grid.Row="4" ToolTip="Filter parameters"/>
      <ListBox x:Name="param_b_list" Grid.Row="5" Margin="0,4,0,0"/>
    </Grid>
  </Grid>

  <!-- relationship -->
  <StackPanel Grid.Row="2" Margin="0,8,0,0">
    <TextBlock x:Name="mode_tb" Style="{StaticResource Caption}" Text="HOW B ELEMENTS FIND THEIR A ELEMENT"/>
    <WrapPanel>
      <ComboBox x:Name="rel_cb" Width="250" Margin="0,0,12,4"/>
      <StackPanel x:Name="key_panel" Orientation="Horizontal" Margin="0,0,0,4">
        <TextBlock Text="Key A" Margin="0,0,6,0" VerticalAlignment="Center"/>
        <ComboBox x:Name="key_a_cb" Width="200" Margin="0,0,12,0"/>
        <TextBlock Text="= Key B" Margin="0,0,6,0" VerticalAlignment="Center"/>
        <ComboBox x:Name="key_b_cb" Width="200"/>
      </StackPanel>
    </WrapPanel>
    <TextBlock x:Name="rel_help" Style="{StaticResource Caption}" TextWrapping="Wrap" Margin="0,2,0,0"/>
  </StackPanel>

  <!-- add pair -->
  <Grid Grid.Row="3" Margin="0,8,0,0">
    <Grid.ColumnDefinitions><ColumnDefinition Width="Auto"/><ColumnDefinition Width="Auto"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
    <Button x:Name="add_b" Content="Add pair  A → B" Margin="0" MinWidth="140"/>
    <Button x:Name="auto_b" Grid.Column="1" Content="Auto-pair same names" Margin="6,0,0,0"
            ToolTip="Pair every A parameter with the compatible B parameter of the same name (never a parameter onto itself on the same element)"/>
    <TextBlock x:Name="compat_tb" Grid.Column="2" Margin="12,0,0,0" VerticalAlignment="Center" TextWrapping="Wrap"/>
  </Grid>

  <!-- pairs -->
  <StackPanel Grid.Row="4">
    <TextBlock x:Name="pairs_caption" Style="{StaticResource Caption}" Text="PAIRS IN THIS MAPPING"/>
    <ListBox x:Name="pairs_list" Height="140"/>
  </StackPanel>

  <!-- footer -->
  <Grid Grid.Row="5" Margin="0,12,0,0">
    <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/></Grid.ColumnDefinitions>
    <TextBlock x:Name="status_tb" VerticalAlignment="Center" TextWrapping="Wrap"/>
    <StackPanel Grid.Column="1" Orientation="Horizontal">
      <Button x:Name="manage_b" Content="Mappings…" ToolTip="Review, disable, delete, import or export mappings"/>
      <Button x:Name="new_b" Content="New" ToolTip="Clear pairs and start another mapping"/>
      <Button x:Name="apply_b" Content="Apply mapping" Style="{StaticResource Primary}" MinWidth="120"/>
      <Button x:Name="close_b" Content="Close" IsCancel="True"/>
    </StackPanel>
  </Grid>
</Grid>'''


class MapperWindow(ui.ThemedWindow):
    """persist=True  -> Apply writes to the project immediately.
    persist=False -> Apply edits `cfg` in memory and closes (used from the manager)."""

    def __init__(self, doc, cfg, persist=True, edit_mapping=None):
        ui.ThemedWindow.__init__(self, _BODY, "Parameter Pusher", width=1040, height=860,
                                 min_w=820, min_h=640, help_topic="map-parameters")
        self.doc = doc
        self.cfg = cfg
        self.persist = persist
        self.changed = False
        self._busy = False
        self._param_cache = {}
        self.cats = ru.list_categories(doc)
        self.cat_a = None   # (key, name)
        self.cat_b = None
        self.refs_a, self.refs_b = [], []
        self.sel_a = None   # selected param ref
        self.sel_b = None
        self.pairs = []     # list of pair dicts
        self.editing = None  # mapping being edited (dict)

        for r in relations.RELATIONS:
            self.rel_cb.Items.Add(ui.cb_item(r.label, r.key))
        self.rel_cb.SelectedIndex = 0

        # events
        self.cat_a_filter.TextChanged += lambda s, e: self._fill_cats("a")
        self.cat_b_filter.TextChanged += lambda s, e: self._fill_cats("b")
        self.cat_a_list.SelectionChanged += lambda s, e: self._on_cat("a")
        self.cat_b_list.SelectionChanged += lambda s, e: self._on_cat("b")
        self.param_a_filter.TextChanged += lambda s, e: self._fill_params("a")
        self.param_b_filter.TextChanged += lambda s, e: self._fill_params("b")
        self.param_a_list.SelectionChanged += lambda s, e: self._on_param("a")
        self.param_b_list.SelectionChanged += lambda s, e: self._on_param("b")
        self.param_a_list.MouseDoubleClick += lambda s, e: self._add_pair()
        self.param_b_list.MouseDoubleClick += lambda s, e: self._add_pair()
        self.rel_cb.SelectionChanged += lambda s, e: self._on_relation()
        self.add_b.Click += lambda s, e: self._add_pair()
        self.auto_b.Click += lambda s, e: self._auto_pair()
        self.apply_b.Click += lambda s, e: self._apply()
        self.new_b.Click += lambda s, e: self._reset(keep_cats=True)
        self.manage_b.Click += lambda s, e: self._manage()
        self.close_b.Click += lambda s, e: self.Close()
        if not persist:
            self.manage_b.Visibility = Visibility.Collapsed

        self._fill_cats("a")
        self._fill_cats("b")
        self._sync_relations()
        if edit_mapping is not None:
            self._load_mapping(edit_mapping)
        self._refresh_pairs()
        self._update_status()

    # ------------------------------------------------------------------ helpers
    def _status(self, text, brush="Sub"):
        self.status_tb.Text = text
        self.status_tb.SetResourceReference(TextBlock.ForegroundProperty, brush)

    def _rel(self):
        it = self.rel_cb.SelectedItem
        return relations.BY_KEY.get(it.Tag if it is not None else "same")

    def _w(self, col, name):
        return getattr(self, name.replace("#", col))

    # ------------------------------------------------------------------ categories
    def _fill_cats(self, col):
        flt = self._w(col, "cat_#_filter").Text.strip().lower()
        lst = self._w(col, "cat_#_list")
        current = self.cat_a if col == "a" else self.cat_b
        self._busy = True
        lst.Items.Clear()
        sel = None
        for c in self.cats:
            if flt and flt not in c.Name.lower():
                continue
            key = ru.category_key(c)
            it = ui.lb_item(ui.tb(c.Name), (key, c.Name))
            lst.Items.Add(it)
            if current and current[0] == key:
                sel = it
        if sel is not None:
            lst.SelectedItem = sel
            lst.ScrollIntoView(sel)
        self._busy = False

    def _on_cat(self, col, force=None):
        if self._busy:
            return
        lst = self._w(col, "cat_#_list")
        it = lst.SelectedItem
        if it is None and force is None:
            return
        val = force or it.Tag
        old = self.cat_a if col == "a" else self.cat_b
        if old and old[0] == val[0]:
            return
        if self.pairs and old is not None and force is None:
            res = ui.ask("Changing category {} clears the {} pair(s) in this mapping.".format(
                col.upper(), len(self.pairs)), "Change category", ("Clear pairs", "Keep category"))
            if res != "Clear pairs":
                self._fill_cats(col)  # restore selection
                return
            self.pairs = []
            self._refresh_pairs()
        if col == "a":
            self.cat_a, self.sel_a = val, None
        else:
            self.cat_b, self.sel_b = val, None
        refs, count = self._params_for(val[0])
        if col == "a":
            self.refs_a = refs
        else:
            self.refs_b = [r for r in refs if not r.get("ro")]
        self._w(col, "param_#_caption").Text = u"{} PARAMETERS  ·  {} element(s){}".format(
            "SOURCE" if col == "a" else "TARGET", count,
            "" if col == "a" else "  ·  read-only hidden")
        self._fill_params(col)
        if col == "a":
            self._fill_params("b")
        self._fill_keys()
        self._sync_relations(auto=True)

    def _params_for(self, cat_key):
        if cat_key not in self._param_cache:
            self._param_cache[cat_key] = ru.gather_params(self.doc, cat_key)
        return self._param_cache[cat_key]

    # ------------------------------------------------------------------ parameters
    def _param_row(self, ref, col):
        sub = u"{} · {}".format("Type" if ref.get("type") else "Instance",
                                     ru.spec_label(ref.get("spec"), ref.get("storage")))
        if ref.get("bip"):
            sub += u" · built-in"
        elif ref.get("guid"):
            sub += u" · shared"
        if col == "a" and ref.get("ro"):
            sub += u" · read-only"
        badge = None
        tip = None
        if col == "b" and self.sel_a is not None:
            level, reason = self._classify(self.sel_a, ref)
            badge = ui.tb(cv.LEVEL_LABEL[level], BADGE_BRUSH[level], size=11)
            tip = reason
        row = ui.columns([ui.two_line(ref["name"], sub), badge], ["*", "auto"])
        return ui.lb_item(row, ref, tip)

    def _fill_params(self, col):
        refs = self.refs_a if col == "a" else self.refs_b
        flt = self._w(col, "param_#_filter").Text.strip().lower()
        lst = self._w(col, "param_#_list")
        current = self.sel_a if col == "a" else self.sel_b
        self._busy = True
        lst.Items.Clear()
        sel = None
        for r in refs:
            if flt and flt not in r["name"].lower():
                continue
            it = self._param_row(r, col)
            lst.Items.Add(it)
            if current is not None and ru.ref_key(current) == ru.ref_key(r):
                sel = it
        if sel is not None:
            lst.SelectedItem = sel
            lst.ScrollIntoView(sel)
        self._busy = False

    def _on_param(self, col):
        if self._busy:
            return
        it = self._w(col, "param_#_list").SelectedItem
        if col == "a":
            self.sel_a = it.Tag if it is not None else None
            self._fill_params("b")  # refresh compatibility badges
        else:
            self.sel_b = it.Tag if it is not None else None
        self._show_compat()

    def _show_compat(self):
        if self.sel_a is None or self.sel_b is None:
            self.compat_tb.Text = "Select a parameter in A and in B, then Add pair (or double-click)."
            self.compat_tb.SetResourceReference(TextBlock.ForegroundProperty, "Sub")
            self.add_b.IsEnabled = False
            return
        level, reason = self._classify(self.sel_a, self.sel_b)
        self.compat_tb.Text = u"{} → {}:  {}  —  {}".format(
            ru.ref_label(self.sel_a), ru.ref_label(self.sel_b), cv.LEVEL_LABEL[level], reason)
        self.compat_tb.SetResourceReference(TextBlock.ForegroundProperty, BADGE_BRUSH[level])
        fixable = level == cv.INCOMPATIBLE and self._rule_fixable(self.sel_a, self.sel_b)
        if fixable:
            self.compat_tb.Text += u"  —  you can still add it with a rule that converts the value."
        self.add_b.IsEnabled = level != cv.INCOMPATIBLE or fixable

    # ------------------------------------------------------------------ relation
    def _fill_keys(self):
        for col, refs in (("a", self.refs_a), ("b", self._params_for(self.cat_b[0])[0] if self.cat_b else [])):
            cb = self._w(col, "key_#_cb")
            prev = cb.SelectedItem.Tag if cb.SelectedItem is not None else None
            cb.Items.Clear()
            sel = None
            for r in refs:
                it = ui.cb_item(ru.ref_label(r), r)
                cb.Items.Add(it)
                if prev is not None and ru.ref_key(prev) == ru.ref_key(r):
                    sel = it
            if sel is not None:
                cb.SelectedItem = sel

    def _select_key(self, col, ref):
        cb = self._w(col, "key_#_cb")
        for it in cb.Items:
            if ru.ref_key(it.Tag) == ru.ref_key(ref):
                cb.SelectedItem = it
                return

    def _sync_relations(self, auto=False):
        """Grey out relations that don't fit the category pair; pick a sensible one."""
        ca = self.cat_a and self.cat_a[0]
        cb = self.cat_b and self.cat_b[0]
        valid = set(r.key for r in relations.available(ca, cb))
        for it in self.rel_cb.Items:
            it.IsEnabled = it.Tag in valid
        cur = self._rel()
        if auto and ca and cb and (cur is None or cur.key not in valid):
            want = relations.default_for(ca, cb)
            for it in self.rel_cb.Items:
                if it.Tag == want:
                    self.rel_cb.SelectedItem = it  # fires _on_relation
                    return
        self._on_relation()

    def _on_relation(self):
        rel = self._rel()
        if rel is None:
            return
        ca = self.cat_a and self.cat_a[0]
        cb = self.cat_b and self.cat_b[0]
        if ca and cb:
            self.mode_tb.Text = (u"SAME CATEGORY  \u00b7  copy between parameters on the same element or a related one"
                                 if ca == cb else
                                 u"DIFFERENT CATEGORIES  \u00b7  push to the same-name or a different parameter")
            self.mode_tb.Text += u"  \u00b7  HOW B ELEMENTS FIND THEIR A ELEMENT"
        if self.sel_a is not None:
            self._fill_params("b")  # self-pair badge depends on the relation
        self.key_panel.Visibility = Visibility.Visible if rel.needs_keys else Visibility.Collapsed
        err = rel.validate(self.cat_a and self.cat_a[0], self.cat_b and self.cat_b[0])
        if err and self.cat_a and self.cat_b:
            self.rel_help.Text = u"⚠ " + err
            self.rel_help.SetResourceReference(TextBlock.ForegroundProperty, "Warn")
        else:
            self.rel_help.Text = rel.help
            self.rel_help.SetResourceReference(TextBlock.ForegroundProperty, "Sub")
        self._show_compat()

    # ------------------------------------------------------------------ pairs
    def _classify(self, src, dst):
        rel = self._rel()
        if rel is not None and relations.is_self_pair(rel.key, src, dst):
            return cv.INCOMPATIBLE, "Same parameter on the same element - pick a different target parameter"
        return cv.classify(src, dst)

    def _rule_fixable(self, src, dst):
        rel = self._rel()
        if rel is not None and relations.is_self_pair(rel.key, src, dst):
            return False
        return cv.rule_can_fix(src, dst)

    def _add_pair(self):
        if self.sel_a is None or self.sel_b is None:
            return
        level, reason = self._classify(self.sel_a, self.sel_b)
        rule = u""
        if level == cv.INCOMPATIBLE:
            if not self._rule_fixable(self.sel_a, self.sel_b):
                self._status(u"Can't pair: " + reason, "Bad")
                return
            if ui.ask(u"{}\n\nThese types don't convert automatically. Add the pair with a rule "
                      u"that produces the target value?".format(reason), "Needs a rule",
                      ("Write rule\u2026", "Cancel")) != u"Write rule\u2026":
                return
            rule = edit_rule(self.doc, {"src": self.sel_a, "dst": self.sel_b, "rule": u""},
                             self._draft_mapping(), require_rule=True)
            if not rule:
                return
        dkey = ru.ref_key(self.sel_b)
        for p in self.pairs:
            if ru.ref_key(p["dst"]) == dkey:
                if ru.ref_key(p["src"]) == ru.ref_key(self.sel_a):
                    self._status("That pair is already in this mapping.", "Warn")
                    return
                res = ui.ask(u"'{}' is already fed by '{}'.\nReplace it with '{}'?".format(
                    ru.ref_label(p["dst"]), ru.ref_label(p["src"]), ru.ref_label(self.sel_a)),
                    "Target already used", ("Replace", "Cancel"))
                if res != "Replace":
                    return
                self.pairs.remove(p)
                break
        self.pairs.append({"src": dict(self.sel_a), "dst": dict(self.sel_b),
                           "level": level, "enabled": True, "rule": rule})
        self._refresh_pairs()
        self._status(u"Added {} → {}".format(ru.ref_label(self.sel_a), ru.ref_label(self.sel_b)), "Good")

    def _auto_pair(self):
        if not self.refs_a or not self.refs_b:
            self._status("Pick both categories first.", "Warn")
            return
        used = set(ru.ref_key(p["dst"]) for p in self.pairs)
        by_name = {}
        for r in self.refs_b:
            by_name.setdefault((r["name"].lower(), r.get("type")), []).append(r)
        added = skipped = 0
        for src in self.refs_a:
            # prefer the same scope (instance/type), then the other
            cands = by_name.get((src["name"].lower(), src.get("type")), []) + \
                by_name.get((src["name"].lower(), not src.get("type")), [])
            for dst in cands:
                if ru.ref_key(dst) in used:
                    continue
                level, _ = self._classify(src, dst)
                if level in (cv.INCOMPATIBLE, cv.LOSSY):
                    skipped += 1
                    continue
                self.pairs.append({"src": dict(src), "dst": dict(dst), "level": level, "enabled": True})
                used.add(ru.ref_key(dst))
                added += 1
                break
        self._refresh_pairs()
        if added:
            self._status(u"Auto-paired {} parameter(s) by name ({} lossy/incompatible skipped). "
                         u"Untick or remove any you don't want.".format(added, skipped), "Good")
        else:
            rel = self._rel()
            self._status("No compatible same-name parameters found."
                         + (" On 'Same element' a parameter can't be pushed onto itself - "
                            "pair it with a different parameter instead." if rel and rel.key == "same" else ""),
                         "Warn")

    def _draft_mapping(self):
        """Mapping dict from the current selections (for rule previews), or None."""
        rel = self._rel()
        if not self.cat_a or not self.cat_b or rel is None or rel.validate(self.cat_a[0], self.cat_b[0]):
            return None
        m = {"cat_a": self.cat_a[0], "cat_b": self.cat_b[0], "relation": rel.key, "relation_opts": {}}
        if rel.needs_keys:
            if self.key_a_cb.SelectedItem is None or self.key_b_cb.SelectedItem is None:
                return None
            m["relation_opts"] = {"key_a": self.key_a_cb.SelectedItem.Tag,
                                  "key_b": self.key_b_cb.SelectedItem.Tag}
        return m

    def _edit_rule(self, pair):
        level = cv.classify(pair["src"], pair["dst"])[0]
        code = edit_rule(self.doc, pair, self._draft_mapping(), require_rule=(level == cv.INCOMPATIBLE))
        if code is None:
            return
        pair["rule"] = code
        self._refresh_pairs()
        self._status(u"Rule {} for {}".format("saved" if code else "removed", ru.ref_label(pair["dst"])),
                     "Good")

    def _remove_pair(self, pair):
        if pair in self.pairs:
            self.pairs.remove(pair)
        self._refresh_pairs()

    def _refresh_pairs(self):
        self.pairs_list.Items.Clear()
        for p in self.pairs:
            level = p.get("level") or cv.classify(p["src"], p["dst"])[0]
            has_rule = bool((p.get("rule") or "").strip())

            def toggle(s, e, p=p):
                p["enabled"] = bool(s.IsChecked)

            chk = ui.checkbox(p.get("enabled", True), toggle, "Enable / disable this pair")
            fx = ui.small_button(u"\u0192", "Edit rule" if has_rule else "Add a rule that transforms the value",
                                 lambda s, e, p=p: self._edit_rule(p), accent=has_rule)
            rm = Button()
            rm.Content = u"✕"
            rm.MinWidth = 28
            rm.Padding = Thickness(4, 0, 4, 0)
            rm.Height = 24
            rm.ToolTip = "Remove pair"
            rm.Click += (lambda s, e, p=p: self._remove_pair(p))
            row = ui.columns([
                chk,
                ui.two_line(u"{}  →  {}".format(ru.ref_label(p["src"]), ru.ref_label(p["dst"])),
                            u"{} → {}".format(
                                ru.spec_label(p["src"].get("spec"), p["src"].get("storage")),
                                ru.spec_label(p["dst"].get("spec"), p["dst"].get("storage")))),
                ui.tb(cv.RULE_LABEL if has_rule else cv.LEVEL_LABEL[level],
                      "Accent" if has_rule else BADGE_BRUSH[level], size=11, margin=(8, 0, 8, 0)),
                fx, rm], [26, "*", "auto", "auto", "auto"])
            fx.Margin = Thickness(0, 0, 4, 0)
            self.pairs_list.Items.Add(ui.lb_item(row, p, (p.get("rule") or None)))
        self.pairs_caption.Text = u"PAIRS IN THIS MAPPING  ·  {}".format(len(self.pairs))
        self._update_status()

    # ------------------------------------------------------------------ apply / load
    def _update_status(self):
        n = len(self.cfg["mappings"])
        if self.editing:
            self._status(u"Editing '{}'.  {} mapping(s) in project.".format(self.editing["name"], n))
        else:
            self._status(u"{} mapping(s) stored in this project.".format(n))

    def _validate(self):
        if not self.cat_a or not self.cat_b:
            return "Pick a category in both columns."
        rel = self._rel()
        err = rel.validate(self.cat_a[0], self.cat_b[0])
        if err:
            return err
        if rel.needs_keys and (self.key_a_cb.SelectedItem is None or self.key_b_cb.SelectedItem is None):
            return "Choose Key A and Key B for a key match."
        if not self.pairs:
            return "Add at least one parameter pair."
        for p in self.pairs:
            code = (p.get("rule") or "").strip()
            if code:
                try:
                    rules.check(code)
                except rules.RuleError as ex:
                    return u"Rule on '{}': {}".format(ru.ref_label(p["dst"]), ex.args[0])
            elif cv.classify(p["src"], p["dst"])[0] == cv.INCOMPATIBLE:
                return u"'{}' \u2192 '{}' needs a rule (\u0192) to convert the value.".format(
                    ru.ref_label(p["src"]), ru.ref_label(p["dst"]))
        bad = [p for p in self.pairs if relations.is_self_pair(rel.key, p["src"], p["dst"])]
        if bad:
            return u"'{}' is paired with itself on the same element - remove it or change the relationship.".format(
                ru.ref_label(bad[0]["src"]))
        return ""

    def _build_mapping(self):
        rel = self._rel()
        m = copy.deepcopy(self.editing) if self.editing else {"id": storage.new_id(), "enabled": True}
        m.update({
            "cat_a": self.cat_a[0], "cat_a_name": self.cat_a[1],
            "cat_b": self.cat_b[0], "cat_b_name": self.cat_b[1],
            "relation": rel.key, "relation_opts": {},
            "pairs": [{"src": p["src"], "dst": p["dst"], "enabled": p.get("enabled", True),
                       "level": p.get("level"), "rule": p.get("rule") or u""} for p in self.pairs],
        })
        if rel.needs_keys:
            m["relation_opts"] = {"key_a": self.key_a_cb.SelectedItem.Tag,
                                  "key_b": self.key_b_cb.SelectedItem.Tag}
        m["name"] = self.name_tb.Text.strip() or storage.default_name(m)
        return m

    def _apply(self):
        err = self._validate()
        if err:
            self._status(err, "Bad")
            return
        m = self._build_mapping()
        storage.upsert_mapping(self.cfg, m)
        self.changed = True
        if self.persist:
            try:
                storage.save(self.doc, self.cfg)
            except Exception as ex:
                ui.alert("Could not save mappings to the project:\n{}".format(ex), "Save failed")
                return
        if not self.persist:
            self.Close()
            return
        self._reset(keep_cats=True)
        self._status(u"Saved '{}'. Pick new pairs or categories for another mapping.".format(m["name"]), "Good")

    def _reset(self, keep_cats=True):
        self.editing = None
        self.pairs = []
        self.name_tb.Text = ""
        self.sel_b = None
        self._fill_params("b")
        if not keep_cats:
            self.cat_a = self.cat_b = None
            self._fill_cats("a")
            self._fill_cats("b")
        self._refresh_pairs()

    def _load_mapping(self, m):
        cat_a = ru.category_from_key(self.doc, m.get("cat_a"))
        cat_b = ru.category_from_key(self.doc, m.get("cat_b"))
        if cat_a is None or cat_b is None:
            ui.alert("This mapping references a category that doesn't exist in this project.",
                     "Missing category")
        if cat_a is not None:
            self._on_cat("a", force=(m["cat_a"], cat_a.Name))
            self._fill_cats("a")
        if cat_b is not None:
            self._on_cat("b", force=(m["cat_b"], cat_b.Name))
            self._fill_cats("b")
        for it in self.rel_cb.Items:
            if it.Tag == m.get("relation"):
                self.rel_cb.SelectedItem = it
        opts = m.get("relation_opts") or {}
        if opts.get("key_a"):
            self._select_key("a", opts["key_a"])
        if opts.get("key_b"):
            self._select_key("b", opts["key_b"])
        self.pairs = copy.deepcopy(m.get("pairs", []))
        self.editing = m
        self.name_tb.Text = m.get("name", "")
        self.title_tb.Text = u"Edit mapping"

    # ------------------------------------------------------------------ manager
    def _manage(self):
        from pypipie.manager import ManagerWindow
        mw = ManagerWindow(self.doc, self.cfg, allow_new=False)
        mw.ShowDialog()
        self.cfg = mw.cfg
        self._update_status()


def run(doc):
    cfg = storage.load(doc)
    MapperWindow(doc, cfg, persist=True).ShowDialog()
