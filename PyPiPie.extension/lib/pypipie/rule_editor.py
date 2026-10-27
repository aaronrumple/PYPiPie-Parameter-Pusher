# -*- coding: utf-8 -*-
"""Rule editor: write, test and preview the transform script for one parameter pair."""
from System.Windows import Visibility
from System.Windows.Controls import TextBlock

from pypipie import revitutil as ru
from pypipie import rules
from pypipie import ui

PLACEHOLDER = u"# Transform the incoming value, e.g.\n# value = value.upper()\nvalue\n"

_BODY = u'''
<Grid>
  <Grid.RowDefinitions>
    <RowDefinition Height="Auto"/>
    <RowDefinition Height="Auto"/>
    <RowDefinition Height="*"/>
    <RowDefinition Height="Auto"/>
    <RowDefinition Height="Auto"/>
    <RowDefinition Height="Auto"/>
    <RowDefinition Height="Auto"/>
  </Grid.RowDefinitions>

  <StackPanel Margin="0,0,0,6">
    <TextBlock x:Name="pair_tb" FontSize="16" FontWeight="SemiBold"/>
    <TextBlock x:Name="types_tb" Style="{StaticResource Caption}" TextWrapping="Wrap"/>
  </StackPanel>

  <Grid Grid.Row="1" Margin="0,0,0,6">
    <Grid.ColumnDefinitions><ColumnDefinition Width="Auto"/><ColumnDefinition Width="Auto"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
    <ComboBox x:Name="tmpl_cb" Width="230"/>
    <Button x:Name="insert_b" Grid.Column="1" Content="Insert template" ToolTip="Replace the code with the chosen template"/>
    <TextBlock Grid.Column="2" Style="{StaticResource Caption}" Margin="12,0,0,0" VerticalAlignment="Center" TextWrapping="Wrap"
               Text="A single expression, or a short script that sets / returns value."/>
  </Grid>

  <Grid Grid.Row="2">
    <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="12"/><ColumnDefinition Width="300"/></Grid.ColumnDefinitions>
    <TextBox x:Name="code_tb" FontFamily="Consolas" FontSize="13" AcceptsReturn="True" AcceptsTab="True"
             TextWrapping="NoWrap" VerticalScrollBarVisibility="Auto" HorizontalScrollBarVisibility="Auto"
             VerticalContentAlignment="Top" Padding="8,6"/>
    <Border Grid.Column="2" Background="{DynamicResource Header}" BorderBrush="{DynamicResource Border}"
            BorderThickness="1" CornerRadius="3">
      <ScrollViewer VerticalScrollBarVisibility="Auto" HorizontalScrollBarVisibility="Auto">
        <TextBlock x:Name="ref_tb" FontFamily="Consolas" FontSize="11" Margin="10,8"
                   Foreground="{DynamicResource Sub}"/>
      </ScrollViewer>
    </Border>
  </Grid>

  <StackPanel Grid.Row="3" Margin="0,6,0,0">
    <TextBlock x:Name="compile_tb" TextWrapping="Wrap"/>
    <TextBlock x:Name="lint_tb" TextWrapping="Wrap" Foreground="{DynamicResource Warn}" Margin="0,2,0,0"/>
  </StackPanel>

  <StackPanel Grid.Row="4" Margin="0,8,0,0">
    <TextBlock Style="{StaticResource Caption}" Text="TRY IT"/>
    <WrapPanel>
      <TextBlock Text="Incoming value" VerticalAlignment="Center" Margin="0,0,6,4"/>
      <TextBox x:Name="test_in" Width="180" Margin="0,0,12,4"/>
      <TextBlock Text="Current target" VerticalAlignment="Center" Margin="0,0,6,4"/>
      <TextBox x:Name="test_target" Width="140" Margin="0,0,8,4"/>
      <Button x:Name="test_b" Content="Test" Margin="0,0,8,4"/>
      <Button x:Name="sandbox_b" Content="Sandbox test" Margin="0,0,8,4"
              ToolTip="Stress-run the rule on many probe values (empty, 0, negatives, huge numbers, long text) in an isolated thread with a time limit"/>
      <Button x:Name="preview_b" Content="Preview on model" Margin="0,0,8,4"
              ToolTip="Dry-run the rule on the first linked elements - nothing is written"/>
    </WrapPanel>
    <TextBlock x:Name="test_out" TextWrapping="Wrap" Margin="0,2,0,0"/>
  </StackPanel>

  <ListBox x:Name="preview_list" Grid.Row="5" Height="150" Margin="0,6,0,0" Visibility="Collapsed"/>

  <Grid Grid.Row="6" Margin="0,12,0,0">
    <Grid.ColumnDefinitions><ColumnDefinition Width="Auto"/><ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/></Grid.ColumnDefinitions>
    <Button x:Name="remove_b" Content="Remove rule" Margin="0" ToolTip="Push the value with the standard type conversion"/>
    <StackPanel Grid.Column="2" Orientation="Horizontal">
      <Button x:Name="cancel_b" Content="Cancel" IsCancel="True"/>
      <Button x:Name="save_b" Content="Test &amp; save" Style="{StaticResource Primary}" MinWidth="110"
              ToolTip="Runs the sandbox test first; a rule that hangs or trips the guards can't be saved silently"/>
    </StackPanel>
  </Grid>
</Grid>'''


class RuleEditor(ui.ThemedWindow):
    def __init__(self, doc, pair, mapping=None, require_rule=False):
        ui.ThemedWindow.__init__(self, _BODY, "Mapping rule", width=980, height=780, min_w=760, min_h=560,
                                 help_topic="rule-editor")
        self.doc = doc
        self.pair = pair
        self.mapping = mapping
        self.require_rule = require_rule
        self.result = None      # new code ('' = no rule); None = cancelled
        src, dst = pair["src"], pair["dst"]
        self.pair_tb.Text = u"{}  →  {}".format(ru.ref_label(src), ru.ref_label(dst))
        self.types_tb.Text = u"{} ({})  →  {} ({}).  The rule's result is converted to the target type; " \
                             u"numbers are in project display units.".format(
                                 ru.spec_label(src.get("spec"), src.get("storage")), src.get("storage"),
                                 ru.spec_label(dst.get("spec"), dst.get("storage")), dst.get("storage"))
        self.ref_tb.Text = rules.REFERENCE
        for name, _code in rules.TEMPLATES:
            self.tmpl_cb.Items.Add(ui.cb_item(name, _code))
        self.tmpl_cb.SelectedIndex = 0
        self.code_tb.Text = pair.get("rule") or u""
        if not self.code_tb.Text:
            self.code_tb.Text = PLACEHOLDER
        if mapping is None:
            self.preview_b.Visibility = Visibility.Collapsed
        if require_rule:
            self.remove_b.Visibility = Visibility.Collapsed

        self.code_tb.TextChanged += lambda s, e: self._check()
        self.insert_b.Click += lambda s, e: self._insert()
        self.test_b.Click += lambda s, e: self._test()
        self.sandbox_b.Click += lambda s, e: self._sandbox(show=True)
        self._sandboxed = None   # (code, report) of the last sandbox run
        self.test_in.KeyDown += self._enter_tests
        self.preview_b.Click += lambda s, e: self._preview()
        self.remove_b.Click += lambda s, e: self._finish(u"")
        self.save_b.Click += lambda s, e: self._save()
        self.cancel_b.Click += lambda s, e: self.Close()
        self._check()

    # ---------------------------------------------------------------- helpers
    def _say(self, widget, text, brush):
        widget.Text = text
        widget.SetResourceReference(TextBlock.ForegroundProperty, brush)

    def _check(self):
        code = self.code_tb.Text
        try:
            warnings = rules.check(code)
            self._say(self.compile_tb, u"✓ Rule is valid", "Good")
            self.lint_tb.Text = u"\n".join(u"⚠ Line {}: {}".format(l, m) for l, m in warnings)
            return True
        except rules.RuleError as ex:
            self._say(self.compile_tb, u"✕ " + ex.args[0], "Bad")
            self.lint_tb.Text = u""
            return False

    def _insert(self):
        it = self.tmpl_cb.SelectedItem
        if it is None:
            return
        cur = self.code_tb.Text.strip()
        if cur and not cur.startswith(u"# Transform the incoming value") and cur != it.Tag.strip():
            if ui.ask("Replace the current code with this template?", "Insert template",
                      ("Replace", "Cancel")) != "Replace":
                return
        self.code_tb.Text = it.Tag
        self.code_tb.Focus()

    def _typed(self, text):
        """Interpret a typed test value like the source parameter would deliver it."""
        if text == u"":
            return None
        src = self.pair["src"]
        st = src.get("storage")
        if st == "Double":
            return rules.num(text, text)
        if st == "Integer":
            if ru.is_yesno(src.get("spec")):
                return rules.as_bool(text)
            return rules.to_int(text, text)
        return text

    def _enter_tests(self, sender, args):
        if str(args.Key) == "Return":
            self._test()

    def _test(self):
        if not self._check():
            return
        value = self._typed(self.test_in.Text)
        target = self._typed(self.test_target.Text) if self.test_target.Text else None
        res, err = rules.test_value(self.code_tb.Text, value, target)
        if err:
            self._say(self.test_out, u"✕ " + err, "Bad")
        else:
            self._say(self.test_out, u"{}  →  {}".format(rules.describe(value), rules.describe(res)),
                      "Warn" if res is rules.SKIP else "Fg")

    def _preview(self):
        if not self._check():
            return
        try:
            rows, total = rules.preview(self.doc, self.mapping, self.pair, self.code_tb.Text)
        except rules.RuleError as ex:
            self._say(self.test_out, u"✕ " + ex.args[0], "Bad")
            return
        except Exception as ex:
            self._say(self.test_out, u"✕ Preview failed: {}".format(ex), "Bad")
            return
        self.preview_list.Items.Clear()
        self.preview_list.Visibility = Visibility.Visible
        hdr = ui.columns([ui.tb("A element", "Sub"), ui.tb("B element", "Sub"),
                          ui.tb("Incoming", "Sub"), ui.tb("Result", "Sub")], ["*", "*", "*", "2*"])
        hi = ui.lb_item(hdr)
        hi.IsHitTestVisible = False
        self.preview_list.Items.Add(hi)
        brush = {"ok": "Fg", "empty": "Sub", "skip": "Warn", "fail": "Bad", "error": "Bad"}
        for r in rows:
            out = r["out"] if r["status"] == "error" else rules.describe(r["out"])
            if r["status"] == "fail":
                out += u"  · can't convert to target type"
            self.preview_list.Items.Add(ui.lb_item(ui.columns([
                ui.tb(r["a"]), ui.tb(r["b"]), ui.tb(rules.describe(r["in"]), "Sub"),
                ui.tb(out, brush.get(r["status"], "Fg"))], ["*", "*", "*", "2*"])))
        self._say(self.test_out, u"Previewed {} of {} linked element(s). Nothing was written.".format(
            len(rows), total), "Sub")

    # ---------------------------------------------------------------- sandbox
    def _sandbox(self, show=True):
        """Stress-run the rule. Returns the report dict, or None if it doesn't compile."""
        if not self._check():
            return None
        code = self.code_tb.Text
        if self._sandboxed and self._sandboxed[0] == code:
            rep = self._sandboxed[1]
        else:
            samples = []
            if self.test_in.Text:
                samples.append(self._typed(self.test_in.Text))
            try:
                src = self.pair["src"]
                kind = rules.guard.probe_kind(src.get("storage"), ru.is_yesno(src.get("spec")))
                rep = rules.sandbox(code, samples, kind)
            except rules.RuleError as ex:
                self._say(self.compile_tb, u"✕ " + ex.args[0], "Bad")
                return None
            self._sandboxed = (code, rep)
        if show:
            self._show_sandbox(rep)
        return rep

    def _show_sandbox(self, rep):
        self.preview_list.Items.Clear()
        self.preview_list.Visibility = Visibility.Visible
        hdr = ui.columns([ui.tb("Probe value", "Sub"), ui.tb("Target", "Sub"), ui.tb("Result", "Sub"),
                          ui.tb("ms", "Sub")], ["*", 90, "2*", 56])
        hi = ui.lb_item(hdr)
        hi.IsHitTestVisible = False
        self.preview_list.Items.Add(hi)
        order = {"guard": 0, "error": 1, "ok": 2}
        for p, target, status, res, ms in sorted(rep["rows"], key=lambda r: (order[r[2]], -r[4])):
            shown = res if status != "ok" else rules.describe(res)
            label = {"guard": u"⛔ ", "error": u"✕ "}.get(status, u"")
            probe = rules.describe(p)
            if len(probe) > 40:
                probe = probe[:37] + u"…"
            self.preview_list.Items.Add(ui.lb_item(ui.columns([
                ui.tb(probe, "Sub"), ui.tb(u"(empty)" if target is None else u"has value", "Sub"),
                ui.tb(label + shown, {"guard": "Bad", "error": "Warn"}.get(status, "Fg")),
                ui.tb(u"{:.1f}".format(ms), "Warn" if ms > 50 else "Sub")], ["*", 90, "2*", 56])))
        self._say(self.test_out, self._verdict(rep)[1], self._verdict(rep)[0])

    def _verdict(self, rep):
        """(brush, sentence) summarising a sandbox report."""
        n = len(rep["rows"])
        if not rep["finished"]:
            return "Bad", (u"⛔ The rule did not finish {} probe runs within {:.0f}s - it would stall Revit "
                           u"on save. Simplify it before saving.".format(n, rules.guard.SANDBOX_TIMEOUT))
        if rep["guard_hits"]:
            return "Bad", (u"⛔ {} of {} probe runs tripped a safety guard ({}). On real data these elements "
                           u"would be skipped as rule errors.".format(
                               len(rep["guard_hits"]), n, rep["guard_hits"][0][3]))
        if rep["errors"]:
            return "Warn", (u"⚠ Finished in {:.2f}s. {} of {} probe values raised an error (e.g. {}) - fine if "
                            u"your data never looks like that; otherwise guard with an if.".format(
                                rep["elapsed"], len(rep["errors"]), n, rep["errors"][0][3]))
        return "Good", u"✓ Sandbox passed: {} probe runs in {:.2f}s, slowest {:.1f} ms.".format(
            n, rep["elapsed"], rep["slowest_ms"])

    def _save(self):
        if not self._check():
            return
        code = self.code_tb.Text.strip()
        if code == PLACEHOLDER.strip():
            code = u""
        if not code and self.require_rule:
            self._say(self.compile_tb, u"This pair needs a rule to convert the value.", "Bad")
            return
        if code:
            rep = self._sandbox(show=True)
            if rep is None:
                return
            if not rep["finished"]:
                return  # never save a rule that stalls
            warnings = rules.lint(code)
            if rep["guard_hits"] or warnings:
                msg = self._verdict(rep)[1] if rep["guard_hits"] else u""
                if warnings:
                    msg += (u"\n\n" if msg else u"") + u"\n".join(
                        u"⚠ Line {}: {}".format(l, m) for l, m in warnings)
                msg += u"\n\nRuntime guards stay active, so this can't hang Revit - affected elements are " \
                       u"reported as rule errors. Save anyway?"
                if ui.ask(msg, "Rule safety warning", ("Back to editor", "Save anyway")) != "Save anyway":
                    return
        self._finish(code)

    def _finish(self, code):
        self.result = code
        self.Close()


def edit_rule(doc, pair, mapping=None, require_rule=False):
    """Open the editor. Returns the new rule text ('' = removed) or None if cancelled."""
    w = RuleEditor(doc, pair, mapping, require_rule)
    w.ShowDialog()
    return w.result
