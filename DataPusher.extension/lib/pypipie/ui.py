# -*- coding: utf-8 -*-
"""Theme-aware WPF plumbing for Data Pusher windows.

The palette follows Revit's UI theme (UIThemeManager.CurrentTheme, Revit 2024+);
older versions fall back to light. All controls used by Data Pusher are restyled so
dark mode doesn't leave white combo boxes, buttons or scrollbars behind.
"""
import io
import json
import os
import tempfile
from xml.sax.saxutils import escape

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System.Windows import Thickness, FontWeights, VerticalAlignment, TextWrapping, TextTrimming
from System.Windows.Controls import (
    Button, CheckBox, ColumnDefinition, Control, Grid, ListBoxItem, ComboBoxItem, StackPanel, TextBlock,
    ContextMenu, MenuItem, Separator
)
from System.Windows import TextDecorations
from System.Windows import GridLength, GridUnitType

from pyrevit import forms

from pypipie import APP_NAME, APP_SLUG

# --------------------------------------------------------------------------
# palettes
# --------------------------------------------------------------------------
LIGHT = {
    "Bg": "#F3F4F6", "Panel": "#FFFFFF", "Fg": "#1F2328", "Sub": "#5F6670",
    "Border": "#C8CDD3", "Accent": "#0696D7", "AccentFg": "#FFFFFF",
    "Hover": "#E7F3FB", "Sel": "#CDE8F7", "Scroll": "#B9BFC6",
    "Good": "#2E7D32", "Warn": "#A15C00", "Bad": "#C62828", "Header": "#E9ECEF",
}
DARK = {
    "Bg": "#24282E", "Panel": "#2E333A", "Fg": "#E6E8EB", "Sub": "#9CA3AB",
    "Border": "#474E57", "Accent": "#3DA2E6", "AccentFg": "#FFFFFF",
    "Hover": "#39404A", "Sel": "#1E4A66", "Scroll": "#5A626C",
    "Good": "#5CC46A", "Warn": "#E8A93C", "Bad": "#F06A6A", "Header": "#2A2F35",
}


def is_dark():
    try:
        from Autodesk.Revit.UI import UIThemeManager, UITheme
        return UIThemeManager.CurrentTheme == UITheme.Dark
    except Exception:
        return False


def palette():
    return DARK if is_dark() else LIGHT


def _brushes_xaml(pal):
    return "\n".join('<SolidColorBrush x:Key="{}" Color="{}"/>'.format(k, v)
                     for k, v in sorted(pal.items()))


# --------------------------------------------------------------------------
# styles
# --------------------------------------------------------------------------
STYLES = r'''
<Style x:Key="Caption" TargetType="TextBlock">
  <Setter Property="Foreground" Value="{DynamicResource Sub}"/>
  <Setter Property="FontSize" Value="11"/>
  <Setter Property="Margin" Value="0,6,0,3"/>
</Style>

<Style TargetType="Button">
  <Setter Property="Foreground" Value="{DynamicResource Fg}"/>
  <Setter Property="Background" Value="{DynamicResource Panel}"/>
  <Setter Property="BorderBrush" Value="{DynamicResource Border}"/>
  <Setter Property="Padding" Value="12,4"/>
  <Setter Property="Margin" Value="4,0,0,0"/>
  <Setter Property="MinWidth" Value="72"/>
  <Setter Property="Height" Value="28"/>
  <Setter Property="Cursor" Value="Hand"/>
  <Setter Property="Template"><Setter.Value>
    <ControlTemplate TargetType="Button">
      <Border x:Name="Bd" Background="{TemplateBinding Background}" BorderBrush="{TemplateBinding BorderBrush}"
              BorderThickness="1" CornerRadius="3" Padding="{TemplateBinding Padding}">
        <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
      </Border>
      <ControlTemplate.Triggers>
        <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="Bd" Property="BorderBrush" Value="{DynamicResource Accent}"/></Trigger>
        <Trigger Property="IsPressed" Value="True"><Setter TargetName="Bd" Property="Background" Value="{DynamicResource Sel}"/></Trigger>
        <Trigger Property="IsEnabled" Value="False"><Setter TargetName="Bd" Property="Opacity" Value="0.45"/></Trigger>
      </ControlTemplate.Triggers>
    </ControlTemplate>
  </Setter.Value></Setter>
</Style>

<Style x:Key="Primary" TargetType="Button" BasedOn="{StaticResource {x:Type Button}}">
  <Setter Property="Background" Value="{DynamicResource Accent}"/>
  <Setter Property="BorderBrush" Value="{DynamicResource Accent}"/>
  <Setter Property="Foreground" Value="{DynamicResource AccentFg}"/>
</Style>

<Style TargetType="TextBox">
  <Setter Property="Foreground" Value="{DynamicResource Fg}"/>
  <Setter Property="Background" Value="{DynamicResource Panel}"/>
  <Setter Property="BorderBrush" Value="{DynamicResource Border}"/>
  <Setter Property="CaretBrush" Value="{DynamicResource Fg}"/>
  <Setter Property="Padding" Value="4,3"/>
  <Setter Property="Template"><Setter.Value>
    <ControlTemplate TargetType="TextBox">
      <Border x:Name="Bd" Background="{TemplateBinding Background}" BorderBrush="{TemplateBinding BorderBrush}"
              BorderThickness="1" CornerRadius="3">
        <ScrollViewer x:Name="PART_ContentHost" Margin="{TemplateBinding Padding}"/>
      </Border>
      <ControlTemplate.Triggers>
        <Trigger Property="IsKeyboardFocused" Value="True"><Setter TargetName="Bd" Property="BorderBrush" Value="{DynamicResource Accent}"/></Trigger>
      </ControlTemplate.Triggers>
    </ControlTemplate>
  </Setter.Value></Setter>
</Style>

<Style TargetType="CheckBox">
  <Setter Property="Foreground" Value="{DynamicResource Fg}"/>
  <Setter Property="VerticalContentAlignment" Value="Center"/>
  <Setter Property="Cursor" Value="Hand"/>
  <Setter Property="Template"><Setter.Value>
    <ControlTemplate TargetType="CheckBox">
      <StackPanel Orientation="Horizontal" Background="Transparent">
        <Border x:Name="Box" Width="15" Height="15" CornerRadius="3" BorderThickness="1"
                BorderBrush="{DynamicResource Border}" Background="{DynamicResource Panel}" VerticalAlignment="Center">
          <Path x:Name="Tick" Data="M2,7 L6,11 L12,3" Stroke="{DynamicResource AccentFg}" StrokeThickness="2" Visibility="Collapsed"/>
        </Border>
        <ContentPresenter Margin="6,0,0,0" VerticalAlignment="Center"/>
      </StackPanel>
      <ControlTemplate.Triggers>
        <Trigger Property="IsChecked" Value="True">
          <Setter TargetName="Tick" Property="Visibility" Value="Visible"/>
          <Setter TargetName="Box" Property="Background" Value="{DynamicResource Accent}"/>
          <Setter TargetName="Box" Property="BorderBrush" Value="{DynamicResource Accent}"/>
        </Trigger>
        <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="Box" Property="BorderBrush" Value="{DynamicResource Accent}"/></Trigger>
      </ControlTemplate.Triggers>
    </ControlTemplate>
  </Setter.Value></Setter>
</Style>

<Style TargetType="ListBox">
  <Setter Property="Background" Value="{DynamicResource Panel}"/>
  <Setter Property="BorderBrush" Value="{DynamicResource Border}"/>
  <Setter Property="Foreground" Value="{DynamicResource Fg}"/>
  <Setter Property="ScrollViewer.HorizontalScrollBarVisibility" Value="Disabled"/>
  <Setter Property="Padding" Value="2"/>
</Style>

<Style TargetType="ListBoxItem">
  <Setter Property="Foreground" Value="{DynamicResource Fg}"/>
  <Setter Property="Padding" Value="6,3"/>
  <Setter Property="HorizontalContentAlignment" Value="Stretch"/>
  <Setter Property="Template"><Setter.Value>
    <ControlTemplate TargetType="ListBoxItem">
      <Border x:Name="Bd" Background="Transparent" Padding="{TemplateBinding Padding}" CornerRadius="2">
        <ContentPresenter HorizontalAlignment="{TemplateBinding HorizontalContentAlignment}"/>
      </Border>
      <ControlTemplate.Triggers>
        <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="Bd" Property="Background" Value="{DynamicResource Hover}"/></Trigger>
        <Trigger Property="IsSelected" Value="True"><Setter TargetName="Bd" Property="Background" Value="{DynamicResource Sel}"/></Trigger>
        <Trigger Property="IsEnabled" Value="False"><Setter Property="Opacity" Value="0.45"/></Trigger>
      </ControlTemplate.Triggers>
    </ControlTemplate>
  </Setter.Value></Setter>
</Style>

<Style TargetType="ComboBoxItem">
  <Setter Property="Foreground" Value="{DynamicResource Fg}"/>
  <Setter Property="Padding" Value="8,4"/>
  <Setter Property="Template"><Setter.Value>
    <ControlTemplate TargetType="ComboBoxItem">
      <Border x:Name="Bd" Background="Transparent" Padding="{TemplateBinding Padding}">
        <ContentPresenter/>
      </Border>
      <ControlTemplate.Triggers>
        <Trigger Property="IsHighlighted" Value="True"><Setter TargetName="Bd" Property="Background" Value="{DynamicResource Hover}"/></Trigger>
        <Trigger Property="IsEnabled" Value="False"><Setter Property="Opacity" Value="0.4"/></Trigger>
        <Trigger Property="IsSelected" Value="True"><Setter TargetName="Bd" Property="Background" Value="{DynamicResource Sel}"/></Trigger>
      </ControlTemplate.Triggers>
    </ControlTemplate>
  </Setter.Value></Setter>
</Style>

<Style TargetType="ComboBox">
  <Setter Property="Foreground" Value="{DynamicResource Fg}"/>
  <Setter Property="Height" Value="28"/>
  <Setter Property="MaxDropDownHeight" Value="320"/>
  <Setter Property="Template"><Setter.Value>
    <ControlTemplate TargetType="ComboBox">
      <Grid>
        <ToggleButton Focusable="False" ClickMode="Press"
            IsChecked="{Binding IsDropDownOpen, Mode=TwoWay, RelativeSource={RelativeSource TemplatedParent}}">
          <ToggleButton.Template>
            <ControlTemplate TargetType="ToggleButton">
              <Border x:Name="Bd" Background="{DynamicResource Panel}" BorderBrush="{DynamicResource Border}"
                      BorderThickness="1" CornerRadius="3">
                <Path HorizontalAlignment="Right" VerticalAlignment="Center" Margin="0,0,9,0"
                      Data="M0,0 L4,4 L8,0" Stroke="{DynamicResource Sub}" StrokeThickness="1.5"/>
              </Border>
              <ControlTemplate.Triggers>
                <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="Bd" Property="BorderBrush" Value="{DynamicResource Accent}"/></Trigger>
              </ControlTemplate.Triggers>
            </ControlTemplate>
          </ToggleButton.Template>
        </ToggleButton>
        <ContentPresenter IsHitTestVisible="False" Margin="8,0,26,0" VerticalAlignment="Center"
            TextElement.Foreground="{DynamicResource Fg}"
            Content="{TemplateBinding SelectionBoxItem}"
            ContentTemplate="{TemplateBinding SelectionBoxItemTemplate}"/>
        <Popup IsOpen="{TemplateBinding IsDropDownOpen}" Placement="Bottom" AllowsTransparency="True"
               Focusable="False" PopupAnimation="Fade">
          <Border Background="{DynamicResource Panel}" BorderBrush="{DynamicResource Border}" BorderThickness="1"
                  MinWidth="{Binding ActualWidth, RelativeSource={RelativeSource TemplatedParent}}"
                  MaxHeight="{TemplateBinding MaxDropDownHeight}">
            <ScrollViewer><ItemsPresenter/></ScrollViewer>
          </Border>
        </Popup>
      </Grid>
      <ControlTemplate.Triggers>
        <Trigger Property="IsEnabled" Value="False"><Setter Property="Opacity" Value="0.45"/></Trigger>
      </ControlTemplate.Triggers>
    </ControlTemplate>
  </Setter.Value></Setter>
</Style>

<Style x:Key="ThumbStyle" TargetType="Thumb">
  <Setter Property="Template"><Setter.Value>
    <ControlTemplate TargetType="Thumb">
      <Border Background="{DynamicResource Scroll}" CornerRadius="4" Margin="2"/>
    </ControlTemplate>
  </Setter.Value></Setter>
</Style>
<ControlTemplate x:Key="VScroll" TargetType="ScrollBar">
  <Track x:Name="PART_Track" IsDirectionReversed="True">
    <Track.Thumb><Thumb Style="{StaticResource ThumbStyle}"/></Track.Thumb>
  </Track>
</ControlTemplate>
<ControlTemplate x:Key="HScroll" TargetType="ScrollBar">
  <Track x:Name="PART_Track">
    <Track.Thumb><Thumb Style="{StaticResource ThumbStyle}"/></Track.Thumb>
  </Track>
</ControlTemplate>
<Style TargetType="ScrollBar">
  <Setter Property="Background" Value="Transparent"/>
  <Setter Property="Template" Value="{StaticResource VScroll}"/>
  <Setter Property="Width" Value="10"/>
  <Style.Triggers>
    <Trigger Property="Orientation" Value="Horizontal">
      <Setter Property="Template" Value="{StaticResource HScroll}"/>
      <Setter Property="Width" Value="Auto"/>
      <Setter Property="Height" Value="10"/>
    </Trigger>
  </Style.Triggers>
</Style>
<Style TargetType="ToolTip">
  <Setter Property="Background" Value="{DynamicResource Panel}"/>
  <Setter Property="Foreground" Value="{DynamicResource Fg}"/>
  <Setter Property="BorderBrush" Value="{DynamicResource Border}"/>
</Style>

<Style TargetType="ContextMenu">
  <Setter Property="Foreground" Value="{DynamicResource Fg}"/>
  <Setter Property="Template"><Setter.Value>
    <ControlTemplate TargetType="ContextMenu">
      <Border Background="{DynamicResource Panel}" BorderBrush="{DynamicResource Border}" BorderThickness="1"
              CornerRadius="4" Padding="3">
        <StackPanel IsItemsHost="True"/>
      </Border>
    </ControlTemplate>
  </Setter.Value></Setter>
</Style>

<Style TargetType="MenuItem">
  <Setter Property="Foreground" Value="{DynamicResource Fg}"/>
  <Setter Property="Template"><Setter.Value>
    <ControlTemplate TargetType="MenuItem">
      <Border x:Name="Bd" Background="Transparent" CornerRadius="3" Padding="6,5,14,5">
        <StackPanel Orientation="Horizontal">
          <TextBlock x:Name="Chk" Text="&#x2713;" Width="18" Foreground="{DynamicResource Accent}" Visibility="Hidden"/>
          <ContentPresenter ContentSource="Header" RecognizesAccessKey="True" VerticalAlignment="Center"/>
        </StackPanel>
      </Border>
      <ControlTemplate.Triggers>
        <Trigger Property="IsHighlighted" Value="True"><Setter TargetName="Bd" Property="Background" Value="{DynamicResource Hover}"/></Trigger>
        <Trigger Property="IsChecked" Value="True"><Setter TargetName="Chk" Property="Visibility" Value="Visible"/></Trigger>
        <Trigger Property="IsEnabled" Value="False"><Setter Property="Opacity" Value="0.45"/></Trigger>
      </ControlTemplate.Triggers>
    </ControlTemplate>
  </Setter.Value></Setter>
</Style>

<Style TargetType="Separator">
  <Setter Property="Template"><Setter.Value>
    <ControlTemplate TargetType="Separator">
      <Border Height="1" Margin="6,3" Background="{DynamicResource Border}"/>
    </ControlTemplate>
  </Setter.Value></Setter>
</Style>

<Style x:Key="Card" TargetType="Border">
  <Setter Property="Background" Value="{DynamicResource Panel}"/>
  <Setter Property="BorderBrush" Value="{DynamicResource Border}"/>
  <Setter Property="BorderThickness" Value="1"/>
  <Setter Property="CornerRadius" Value="5"/>
  <Setter Property="Padding" Value="8,6"/>
</Style>

'''

WINDOW_TMPL = u'''<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="__TITLE__" Width="__W__" Height="__H__" MinWidth="__MINW__" MinHeight="__MINH__"
        WindowStartupLocation="CenterOwner" ShowInTaskbar="False" ResizeMode="__RESIZE__"
        Background="{DynamicResource Bg}" Foreground="{DynamicResource Fg}"
        FontFamily="Segoe UI" FontSize="12" UseLayoutRounding="True" TextOptions.TextFormattingMode="Display">
  <Window.Resources>
__BRUSHES__
__STYLES__
  </Window.Resources>
  <Grid>
    <Grid Margin="14">
__BODY__
    </Grid>
    <Button x:Name="help_btn" Content="?" Width="26" Height="26" MinWidth="0" Padding="0" Margin="0,10,12,0"
            HorizontalAlignment="Right" VerticalAlignment="Top" FontWeight="SemiBold"
            ToolTip="Help for this window (F1)" Visibility="__HELPVIS__"/>
  </Grid>
</Window>'''


class ThemedWindow(forms.WPFWindow):
    """WPFWindow built from a body snippet wrapped in the themed template."""

    def __init__(self, body, title, width=900, height=700, min_w=500, min_h=300, resize=True,
                 help_topic=None):
        self.pal = palette()
        xaml = (WINDOW_TMPL
                .replace("__TITLE__", escape(u"{} · {}".format(APP_NAME, title), {'"': "&quot;"}))
                .replace("__W__", str(width)).replace("__H__", str(height))
                .replace("__MINW__", str(min_w)).replace("__MINH__", str(min_h))
                .replace("__RESIZE__", "CanResizeWithGrip" if resize else "NoResize")
                .replace("__BRUSHES__", _brushes_xaml(self.pal))
                .replace("__STYLES__", STYLES)
                .replace("__HELPVIS__", "Visible" if help_topic else "Collapsed")
                .replace("__BODY__", body))
        forms.WPFWindow.__init__(self, xaml, literal_string=True)
        self.help_topic = help_topic
        if help_topic:
            self.help_btn.Click += lambda s, e: open_help(self.help_topic)
            self.PreviewKeyDown += self._help_key

    def _help_key(self, sender, args):
        if str(args.Key) == "F1":
            args.Handled = True
            open_help(self.help_topic)


# --------------------------------------------------------------------------
# help
# --------------------------------------------------------------------------
HELP_FILE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          "..", "..", "help", "DataPusher_Help.html"))


def open_help(topic=None):
    """Open the HTML help at a section, in the Revit theme.

    Windows drops '#anchors' when opening file paths, so we open a tiny redirect page
    that jumps to the anchor and hands the theme over via window.name.
    """
    if not os.path.exists(HELP_FILE):
        alert(u"Help file not found:\n{}".format(HELP_FILE), "Help")
        return
    try:
        from urllib import quote  # py2 / IronPython
    except ImportError:
        from urllib.parse import quote
    url = u"file:///" + quote(HELP_FILE.replace("\\", "/").encode("utf-8"), safe="/:")
    if topic:
        url += u"#" + topic
    theme = u"datapusher-dark" if is_dark() else u"datapusher-light"
    try:
        folder = os.path.join(tempfile.gettempdir(), APP_SLUG)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        redirect = os.path.join(folder, "open_help.html")
        with io.open(redirect, "w", encoding="utf-8") as f:
            f.write(u'<!doctype html><meta charset="utf-8"><title>Data Pusher Help</title>'
                    u'<script>window.name={};location.replace({});</script>'
                    u'<a href={}>Open Data Pusher help</a>'.format(json.dumps(theme), json.dumps(url), json.dumps(url)))
        os.startfile(redirect)
    except Exception:
        try:
            os.startfile(HELP_FILE)
        except Exception as ex:
            alert(u"Could not open help:\n{}".format(ex), "Help")


# --------------------------------------------------------------------------
# small widget factories (code-built rows keep IronPython binding issues away)
# --------------------------------------------------------------------------
def tb(text, brush="Fg", size=None, bold=False, margin=None, wrap=False):
    t = TextBlock()
    t.Text = text
    t.SetResourceReference(TextBlock.ForegroundProperty, brush)
    if size:
        t.FontSize = size
    if bold:
        t.FontWeight = FontWeights.SemiBold
    if margin:
        t.Margin = Thickness(*margin)
    t.VerticalAlignment = VerticalAlignment.Center
    if wrap:
        t.TextWrapping = TextWrapping.Wrap
    else:
        t.TextTrimming = TextTrimming.CharacterEllipsis
    return t


def columns(cells, widths):
    """Grid row. widths: numbers (px) or '*' / '2*'."""
    g = Grid()
    for i, w in enumerate(widths):
        cd = ColumnDefinition()
        if isinstance(w, str) and w.endswith("*"):
            cd.Width = GridLength(float(w[:-1] or 1), GridUnitType.Star)
        elif w == "auto":
            cd.Width = GridLength.Auto
        else:
            cd.Width = GridLength(w)
        g.ColumnDefinitions.Add(cd)
    for i, c in enumerate(cells):
        if c is None:
            continue
        Grid.SetColumn(c, i)
        g.Children.Add(c)
    return g


def two_line(title, sub, sub_brush="Sub"):
    sp = StackPanel()
    sp.Children.Add(tb(title))
    if sub:
        sp.Children.Add(tb(sub, sub_brush, size=10.5))
    return sp


def lb_item(content, tag=None, tooltip=None):
    it = ListBoxItem()
    it.Content = content
    it.Tag = tag
    if tooltip:
        it.ToolTip = tooltip
    return it


def cb_item(text, tag=None):
    it = ComboBoxItem()
    it.Content = text
    it.Tag = tag
    return it


def checkbox(checked, on_change=None, tooltip=None):
    c = CheckBox()
    c.IsChecked = bool(checked)
    c.VerticalAlignment = VerticalAlignment.Center
    if tooltip:
        c.ToolTip = tooltip
    if on_change:
        c.Checked += on_change
        c.Unchecked += on_change
    return c


def small_button(text, tooltip, on_click, accent=False):
    b = Button()
    b.Content = text
    b.MinWidth = 28
    b.Height = 24
    b.Padding = Thickness(6, 0, 6, 0)
    b.ToolTip = tooltip
    if accent:
        b.SetResourceReference(Control.BorderBrushProperty, "Accent")
        b.SetResourceReference(Control.ForegroundProperty, "Accent")
        b.FontWeight = FontWeights.SemiBold
    b.Click += on_click
    return b


# --------------------------------------------------------------------------
# rule (ƒ) button - one look per state
# --------------------------------------------------------------------------
RULE_TIPS = {
    "none": u"No rule \u2013 the value is pushed with the standard conversion.\nClick to add a rule.",
    "on": u"Rule active.\nClick to edit \u00b7 right-click to switch off or remove.",
    "off": u"Rule switched off for this pair \u2013 standard conversion is used.\n"
           u"Click to edit \u00b7 right-click to switch on or remove.",
    "global_off": u"Rule present, but mapping rules are turned off for this project.\n"
                  u"Turn on \u2018Mapping rules\u2019 to run it.",
}


def rule_button(host, state, on_edit, on_toggle=None, on_remove=None):
    """The ƒ button.

    none        faint outline          - no rule; click to add
    on          filled accent          - rule present and running
    off         accent outline, struck - rule kept but switched off for this pair
    global_off  dim, struck            - rule kept, project-wide rules switch is off
    """
    b = Button()
    t = TextBlock()
    t.Text = u"\u0192"
    t.FontWeight = FontWeights.SemiBold
    b.Content = t
    b.MinWidth = 30
    b.Height = 24
    b.Padding = Thickness(6, 0, 6, 0)
    b.ToolTip = RULE_TIPS[state]
    if state == "on":
        b.SetResourceReference(Control.BackgroundProperty, "Accent")
        b.SetResourceReference(Control.BorderBrushProperty, "Accent")
        t.SetResourceReference(TextBlock.ForegroundProperty, "AccentFg")
    elif state in ("off", "global_off"):
        b.SetResourceReference(Control.BorderBrushProperty, "Accent" if state == "off" else "Border")
        t.SetResourceReference(TextBlock.ForegroundProperty, "Accent" if state == "off" else "Sub")
        t.TextDecorations = TextDecorations.Strikethrough
    else:
        t.SetResourceReference(TextBlock.ForegroundProperty, "Sub")
        b.Opacity = 0.75
    b.Click += lambda s, e: on_edit()

    if state != "none" and (on_toggle or on_remove):
        cm = ContextMenu()
        _theme_popup(host, cm)
        edit = MenuItem()
        edit.Header = u"Edit rule\u2026"
        edit.Click += lambda s, e: on_edit()
        cm.Items.Add(edit)
        if on_toggle:
            tog = MenuItem()
            tog.Header = u"Rule on for this pair"
            tog.IsCheckable = True
            tog.IsChecked = state != "off"
            tog.Click += lambda s, e: on_toggle()
            cm.Items.Add(tog)
        if on_remove:
            cm.Items.Add(Separator())
            rm = MenuItem()
            rm.Header = u"Remove rule"
            rm.Click += lambda s, e: on_remove()
            cm.Items.Add(rm)
        for item in cm.Items:
            _theme_popup(host, item)
        b.ContextMenu = cm
    return b


def _theme_popup(host, el):
    """Context menus live in their own popup tree; hand them the window's brushes and styles."""
    try:
        import clr
        if isinstance(el, ContextMenu):
            el.Resources.MergedDictionaries.Add(host.Resources)
        st = host.TryFindResource(clr.GetClrType(type(el)))
        if st is not None:
            el.Style = st
    except Exception:
        pass


def rule_toggle(state, on_change):
    """Visible on/off switch for a pair's rule (only for pairs that have one)."""
    c = CheckBox()
    c.Content = u"Rule"
    c.IsChecked = state != "off"
    c.Margin = Thickness(8, 0, 8, 0)
    c.VerticalAlignment = VerticalAlignment.Center
    c.ToolTip = (u"Rules are turned off for this project ('Mapping rules' option) - this switch only "
                 u"takes effect once they're on." if state == "global_off" else
                 u"Run this pair's rule. Untick to keep the rule but push with the standard conversion.")
    if state == "global_off":
        c.Opacity = 0.6
    c.Checked += lambda s, e: on_change()
    c.Unchecked += lambda s, e: on_change()
    return c


def icon_button(text, tooltip, on_click, width=28):
    b = Button()
    b.Content = text
    b.MinWidth = width
    b.Height = 24
    b.Padding = Thickness(6, 0, 6, 0)
    b.Margin = Thickness(4, 0, 0, 0)
    b.ToolTip = tooltip
    b.Click += lambda s, e: on_click()
    return b


# --------------------------------------------------------------------------
# message box
# --------------------------------------------------------------------------
_MSG_BODY = u'''
<Grid>
  <Grid.RowDefinitions><RowDefinition Height="*"/><RowDefinition Height="Auto"/></Grid.RowDefinitions>
  <ScrollViewer VerticalScrollBarVisibility="Auto">
    <TextBlock x:Name="msg" TextWrapping="Wrap" FontSize="12.5" Margin="2,2,2,12"/>
  </ScrollViewer>
  <StackPanel x:Name="btns" Grid.Row="1" Orientation="Horizontal" HorizontalAlignment="Right"/>
</Grid>'''


class _MsgBox(ThemedWindow):
    def __init__(self, message, title, buttons):
        lines = message.count("\n") + 1
        ThemedWindow.__init__(self, _MSG_BODY, title, width=460,
                              height=min(520, 150 + lines * 18), min_w=320, min_h=150, resize=False)
        self.msg.Text = message
        self.result = None
        for i, label in enumerate(buttons):
            b = Button()
            b.Content = label
            b.Tag = label
            if i == 0:
                b.Style = self.FindResource("Primary")
                b.IsDefault = True
            b.Click += self._click
            self.btns.Children.Add(b)

    def _click(self, sender, args):
        self.result = sender.Tag
        self.Close()


def ask(message, title="Message", buttons=("OK",)):
    """Themed message box. Returns the clicked button label (None if closed)."""
    w = _MsgBox(message, title, list(buttons))
    w.ShowDialog()
    return w.result


def alert(message, title="Message"):
    ask(message, title, ("OK",))


# --------------------------------------------------------------------------
# push report window
# --------------------------------------------------------------------------
_REPORT_BODY = u'''
<Grid>
  <Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="*"/><RowDefinition Height="Auto"/></Grid.RowDefinitions>
  <StackPanel>
    <TextBlock x:Name="head" FontSize="15" FontWeight="SemiBold"/>
    <TextBlock x:Name="subhead" Style="{StaticResource Caption}" TextWrapping="Wrap"/>
  </StackPanel>
  <ListBox x:Name="rows" Grid.Row="1" Margin="0,6,0,10"/>
  <StackPanel Grid.Row="2" Orientation="Horizontal" HorizontalAlignment="Right">
    <Button x:Name="close_b" Content="Close" Style="{StaticResource Primary}" IsDefault="True" IsCancel="True"/>
  </StackPanel>
</Grid>'''


class PushReportWindow(ThemedWindow):
    def __init__(self, report):
        ThemedWindow.__init__(self, _REPORT_BODY, "Push results", width=900, height=520,
                              help_topic="push-report")
        self.close_b.Click += lambda s, e: self.Close()
        self.head.Text = u"{} value(s) updated".format(report.get("updated", 0))
        self.subhead.Text = u"Trigger: {} · {} · {}s".format(
            report.get("trigger"), report.get("doc"), report.get("seconds"))
        if report.get("error"):
            self.rows.Items.Add(lb_item(tb(report["error"].strip(), "Bad", wrap=True)))
        hdr = columns([tb("Mapping", "Sub", bold=True), tb("Linked", "Sub"), tb("Updated", "Sub"),
                       tb("Same", "Sub"), tb("Empty", "Sub"), tb("Failed", "Sub"),
                       tb("Blocked", "Sub"), tb("Conflict", "Sub")],
                      ["3*", 58, 62, 50, 52, 54, 60, 62])
        hi = lb_item(hdr)
        hi.IsHitTestVisible = False
        self.rows.Items.Add(hi)
        for st in report.get("mappings", []):
            bad = st["failed"] or st["errors"] or st.get("rule_errors")
            warn = st["blocked"] or st["conflicts"] or st["ambiguous"] or st["missing_dst"]
            notes = []
            if st.get("not_applicable"):
                notes.append(u"{} B element(s) can't take part (no parent / nothing nested)".format(
                    st["not_applicable"]))
            if st["unmatched"]:
                notes.append("{} target(s) had no related source".format(st["unmatched"]))
            if st["ambiguous"]:
                notes.append("{} ambiguous match(es) skipped".format(st["ambiguous"]))
            if st["blocked"]:
                notes.append("blocked = owned by another user or out of date")
            pair_rows = st.get("pairs") or []
            if not pair_rows:  # older report shape: keep the totals in the notes
                if st["missing_src"] or st["missing_dst"]:
                    notes.append("parameter missing on {} source / {} target".format(
                        st["missing_src"], st["missing_dst"]))
                if st["readonly"]:
                    notes.append("{} read-only target(s)".format(st["readonly"]))
            notes.extend(e for e in st["errors"] if not e.startswith(u"Skipped '"))
            row = columns([
                two_line(st["name"], u" · ".join(notes), "Bad" if bad else ("Warn" if warn else "Sub")),
                tb(str(st["targets"])), tb(str(st["updated"]), "Good" if st["updated"] else "Fg", bold=True),
                tb(str(st["unchanged"])), tb(str(st["empty"])),
                tb(str(st["failed"]), "Bad" if st["failed"] else "Fg"),
                tb(str(st["blocked"]), "Warn" if st["blocked"] else "Fg"),
                tb(str(st["conflicts"]), "Warn" if st["conflicts"] else "Fg")],
                ["3*", 58, 62, 50, 52, 54, 60, 62])
            self.rows.Items.Add(lb_item(row))
            for ps in pair_rows:
                self.rows.Items.Add(lb_item(_pair_report_row(ps)))


def _pair_report_row(ps):
    """Indented per-pair line under a mapping in the push results."""
    why = []
    if ps.get("note"):
        why.append((ps["note"], "Bad"))
    if ps["missing_dst"]:
        why.append((u"{} target(s) don't have this parameter".format(ps["missing_dst"]), "Warn"))
    if ps["missing_src"]:
        why.append((u"{} source(s) don't have this parameter".format(ps["missing_src"]), "Warn"))
    if ps["readonly"]:
        why.append((u"{} read-only on the target (often driven by a family association)".format(ps["readonly"]),
                    "Warn"))
    if ps["conflicts"]:
        why.append((u"{} conflicting: several sources write one shared target "
                    u"(e.g. one nested type)".format(ps["conflicts"]), "Warn"))
    if ps["rule_skipped"]:
        why.append((u"{} skipped by rule".format(ps["rule_skipped"]), "Sub"))
    if ps["rule_errors"]:
        why.append((u"{} rule error(s)".format(ps["rule_errors"]), "Bad"))
    brush = "Sub"
    for _t, b in why:
        if b == "Bad":
            brush = "Bad"
            break
        if b == "Warn":
            brush = "Warn"
    label = two_line(u"\u2514 " + ps["label"], u" \u00b7 ".join(t for t, _b in why), brush)
    label.Margin = Thickness(14, 0, 0, 0)
    row = columns([
        label, tb(u""),
        tb(str(ps["updated"]), "Good" if ps["updated"] else "Sub"),
        tb(str(ps["unchanged"]), "Sub"), tb(str(ps["empty"]), "Sub"),
        tb(str(ps["failed"]), "Bad" if ps["failed"] else "Sub"),
        tb(str(ps["blocked"]), "Warn" if ps["blocked"] else "Sub"),
        tb(str(ps["conflicts"]), "Warn" if ps["conflicts"] else "Sub")],
        ["3*", 58, 62, 50, 52, 54, 60, 62])
    return row


def show_push_report(report):
    PushReportWindow(report).ShowDialog()
