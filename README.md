# Data Pusher · Parameter Pusher for Revit

**Push parameter values between Revit elements — automatically on save, sync, print and export.**

Data Pusher is a [pyRevit](https://github.com/pyrevitlabs/pyRevit) extension. You map parameters from one category to
another (Rooms → Doors, Sheets → Views, Walls → Windows …) or between parameters of the same element. You can add
small, sandboxed Python rules that transform values along the way. Mappings are stored inside the project, so they
travel with the model and run for everyone on the team.

![Revit 2022+](https://img.shields.io/badge/Revit-2022%2B-0696d7)
![pyRevit](https://img.shields.io/badge/pyRevit-extension-3da2e6)
![IronPython 2.7](https://img.shields.io/badge/IronPython-2.7-5f6670)
![Theme](https://img.shields.io/badge/UI-light%20%2F%20dark-2e7d32)

```
 A element                Relationship              ƒ Rule (optional)          B element
 Room 204          ──▶   door is in room    ──▶    value.upper()       ──▶   Door 204A
 Department=Imaging                                                           Dept=IMAGING
```

---

## Contents
- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick start](#quick-start)
- [How it works](#how-it-works)
- [Mapping rules](#mapping-rules)
- [Rule safety](#rule-safety)
- [Automatic runs](#automatic-runs)
- [Import / export](#import--export)
- [Project layout](#project-layout)
- [Development](#development)
- [FAQ](#faq)
- [License](#license)

---

## Features

| | |
|---|---|
| 🔗 **Category → category** | Push between any two categories through 11 relationships: room, space, level, host, sheet, dependent view, nested family, assembly, group, matching key, or same element. |
| 🔁 **Same category** | Copy one parameter into another on the same element, including instance ↔ type. |
| ✅ **Type-safe pairing** | Every pair is graded as *exact*, *converts*, *lossy* or *incompatible*, with unit-aware conversion based on Project Units. |
| 🔒 **Read-only filtering** | Targets that Revit won't let you write are hidden. Each element is re-checked at push time. |
| ƒ **Mapping rules (optional)** | Python snippets for switch/case, math, if/then, regex, combining parameters. Off unless the project uses them; switch rules on or off per project and per pair. Comes with templates, a Test box, a model preview and a sandbox test. |
| 🛡️ **Pathological-rule protection** | A static check, runtime guards and a timed sandbox test keep a rule from ever stalling Revit. |
| ⚙️ **Hands-off** | Runs silently on save, save-as, sync, print and export. Unchanged values are never rewritten. Workshared models are handled for you. |
| 📦 **Portable** | Settings are stored in Extensible Storage. Mappings import and export as JSON between projects. |
| 🌗 **Theme-aware UI** | Every dialog follows Revit's light/dark theme. There's a **?** / F1 help button on every dialog. |

![Help page](docs/images/help-overview.png)

---

## Requirements

| | |
|---|---|
| Revit | **2022 or later** (uses the ForgeTypeId units API). Light/dark theming needs **2024+**. |
| pyRevit | Recent 4.8+ / 5.x release with the default **IronPython 2.7** engine. |
| OS | Windows (Revit). |

---

## Installation

### Option A — pyRevit CLI
```bash
pyrevit extend ui DataPusher https://github.com/<your-account>/DataPusher.git --branch=main
```

### Option B — manual
1. Download or clone this repository into a folder, keeping the folder name **`DataPusher.extension`**.
2. In Revit: **pyRevit → Settings → Custom Extension Directories → Add** the *parent* folder.
3. Click **Reload**. A **Parameter Pusher** tab appears with the **Parameter Pusher** panel.

| Button | Does |
|---|---|
| **Map Parameters** | Build mappings: pick categories, pair parameters, apply. |
| **Mappings** | One scrolling tree: each category pairing with its parameter pairs. Filter, enable/disable, edit, push, delete, rules, merge duplicates, import/export, automatic-run options. |
| **Push Now** | Run all enabled mappings and show the results (<kbd>Shift</kbd>+click runs silently). |
| **Help** | Opens the full HTML guide (`help/DataPusher_Help.html`). |

---

## Quick start

Copy each room's **Department** onto the doors in that room:

1. **Map Parameters** → column **A**: *Rooms*, column **B**: *Doors*.
   The relationship switches to *Room → elements in room* automatically.
2. Select **Department** in A. Every B parameter now shows a compatibility badge.
3. Select the target in B → **Add pair A → B** (or double-click).
4. **Apply mapping**. It's saved in the project, and the dialog stays open for the next one.
5. **Push Now**, or simply save or sync.

---

## How it works

A **mapping** is one *category pairing* (category A + category B + relationship) holding any number of parameter
pairs. Each pair can carry an optional rule. There is only ever one mapping per pairing:

- Picking categories and a relationship that already have a mapping adds your pairs to it. Column B marks the targets
  it already feeds, and a target fed by a different source asks you to **Replace** or **Keep existing**.
- Imports fold into matching pairings too.
- **Merge duplicates** in the Mappings window combines pairings that are split over several mappings, without changing what gets pushed.
- Elements are collected and related once per pairing rather than once per pair, which makes pushes faster.

### Relationships

| Relationship | A | B | Link |
|---|---|---|---|
| Same element | same category | | the element itself (instance ↔ type allowed) |
| Matching key value | any | any | `A.key == B.key` (trimmed, case-insensitive; an element never matches itself) |
| Host → hosted | any | other | `B.Host` |
| Room → elements in room | Rooms | other | To/From room for doors and windows, otherwise location point in the element's phase |
| Space → elements in space | MEP Spaces | other | as above, for spaces |
| Level → elements on level | Levels | other | `LevelId`, level parameters, or the view's level |
| Sheet → placed views | Sheets | Views | views placed on the sheet |
| Parent view → dependent views | Views | Views | primary view |
| Parent family → nested | any | any | shared nested instance → parent |
| Assembly → members | Assemblies | other | `AssemblyInstanceId` |
| Group → members | Model/Detail Groups | other | `GroupId` |

### Data types

| Badge | Meaning | Examples |
|---|---|---|
| ✓ exact | same storage & data type | Length → Length, Text → Text |
| ↻ converts | safe | number → text (project units), Number ↔ Length via display units, element → name |
| ⚠ lossy | may fail for some values | text → length (`10' 6"`), text → Yes/No, number → integer |
| ✕ incompatible | blocked without a rule | Length → Area, Element → Number |

Type-parameter targets are written to the element's type. If instances of one type disagree, the first value wins
and the rest are reported as *conflicts*.

---

## Mapping rules

Rules are optional. Most pairs push with the standard conversion and need no Python.

- **Project switch:** *Mapping rules (ƒ)* in the Mappings window. It's off in projects without rules. When off, rules are kept but never run, ƒ buttons are hidden on pairs without a rule, and the rule engine isn't loaded during save or sync.
- **Per pair:** right-click **ƒ** → *Rule on for this pair*, or use the checkbox in the rule editor.
- **The ƒ button shows the state:** faint means no rule, filled means the rule is active, struck through means the rule is kept but switched off (accent outline) or rules are off for the project (dim).

Click **ƒ** on any pair. A rule is either one expression or a short script that sets or returns `value`:

```python
# expression
when(value < 100, "Small", value < 500, "Medium", "Large")

# script
value = switch(value, {"PT-1": "Paint, eggshell", "VCT": "Vinyl composition tile"}, default=value)
if target not in (None, ""):
    return SKIP            # don't overwrite existing values
```

| Input | |
|---|---|
| `value` | incoming value: text, number in **display units**, `True`/`False` for Yes/No, element name, or `None` |
| `text` | the source as Revit displays it |
| `target` | the target's current value |
| `a("Param")` / `b("Param")` | read another parameter of the A / B element |
| `a_info` / `b_info` | `{'id', 'name', 'category'}` |

Return a value to write, `SKIP` to leave the target alone, or `None`/`""` for empty.
The helpers are `switch when iff between num to_int as_bool fmt round_to floor_to ceil_to clamp pad join contains
re_find re_test re_sub text_of` plus common math functions and builtins.

The rule editor has 12 templates, live validation, a **Test** box, a **Preview on model** dry run (nothing is written)
and a **Sandbox test**.

---

## Rule safety

Rules run unattended and can arrive in files from other people, so they are sandboxed and guarded:

1. **Sandbox.** No `import`, `while`, `def`, `class`, `try`, `open`, `eval` or `getattr`. No `_private` or .NET
   (`Capitalised`) attributes. Only plain values go in, so a rule can't reach the Revit API or the file system.
2. **Static check** while you type. It **blocks** code that can never finish (`10**10**10`, `'x' * 10**9`,
   `range(10**8)`, huge format widths, self-calling lambdas) and **warns** about risky patterns (data-driven
   exponents or repetition, nested loops, regexes like `(a+)+`).
3. **Runtime guards** compiled into every rule (via an AST transform):

   | Limit | Value |
   |---|---|
   | time per element | 0.5 s |
   | time per rule per push | 15 s |
   | loop iterations per element | 100,000 |
   | text / list length | 1,000,000 |
   | total built per element | 20,000,000 items |
   | integer size | 4,096 bits |
   | regex call | 0.25 s (.NET `Regex` timeout) |

   A tripped guard is reported as a rule error for that element. The save carries on.
4. **Sandbox test.** Runs the rule on type-matched probe values on a background thread with a 3 s limit.
   **Test & save** always runs it. A rule that doesn't finish can't be saved.

---

## Automatic runs

- Hooks: `doc-saving`, `doc-saving-as`, `doc-syncing`, `doc-printing`, `file-exporting`. Each can be toggled in **Mappings**.
- Runs are silent. A summary goes to `%APPDATA%\pyRevit\DataPusher\push.log`.
- Unchanged values are skipped, so elements aren't borrowed needlessly.
- Workshared: elements owned by others, or updated in central, are skipped and reported as *blocked*.
- Warnings are suppressed. A run that changes nothing leaves no undo entry.
- If Revit refuses changes during a print or export event, the run is skipped and logged.

---

## Import / export

Mappings, rules and settings export to JSON. Categories are identified by `BuiltInCategory` name, and parameters by
`BuiltInParameter` name, shared-parameter GUID or name, so files work across projects. Import can **Merge** (a
mapping with the same id is replaced) or **Replace all**, and it warns when the file contains rules.

Storage: one JSON entity on a `DataStorage` element `PyPiPie_ParamPusher`, schema `PyPiPieParamPusher`,
GUID `6b1f6a42-2f6e-4c0e-9a9e-5d3f3f7f1b21`. These identifiers come from the extension's
original name (PyPiPie) and are deliberately unchanged, so projects that already store mappings keep them.

---

## Project layout

```
DataPusher.extension/
├── Parameter Pusher.tab/                ribbon tab
│   └── Parameter Pusher.panel/
│       ├── Map Parameters.pushbutton/   mapping editor
│       ├── Mappings.pushbutton/         report / manager
│       ├── Push Now.pushbutton/         manual run
│       └── Help.pushbutton/             opens the HTML guide
├── hooks/                               doc-saving, doc-saving-as, doc-syncing, doc-printing, file-exporting
├── lib/pypipie/                          Python package (original name kept)
│   ├── revitutil.py     ids, categories, parameter refs, writability
│   ├── convert.py       compatibility grading + value conversion
│   ├── relations.py     how B elements find their A element
│   ├── storage.py       Extensible Storage + JSON import/export
│   ├── engine.py        the push (transactions, worksharing, reporting)
│   ├── rules.py         rule sandbox, helpers, value adapters, preview
│   ├── guard.py         static analysis, AST runtime guards, sandbox test
│   ├── hookrunner.py    silent entry point for event hooks
│   ├── ui.py            theme-aware WPF base, message box, results window, help opener
│   ├── mapper.py        Map Parameters dialog
│   ├── manager.py       Mappings dialog
│   └── rule_editor.py   rule editor
├── help/DataPusher_Help.html  full user guide (opened by ? / F1)
├── tests/                   sandbox, guard and grouping tests (pure Python)
└── docs/images/
```

---

## Development

- Code targets **IronPython 2.7** (pyRevit's default engine) and avoids Python-3-only syntax.
- The dialogs are WPF, built from XAML strings. All controls are restyled from theme brushes, so dark mode is complete.
- `rules.py`, `guard.py` and `storage.py`'s grouping logic don't need Revit, so they're tested with plain CPython
  **and** with IronPython 2.7 (the engine Revit actually runs). IronPython's `ast` module differs from CPython's (for
  example it drops the second `for` of a comprehension), so run both before release:

```bash
cd lib
python -m pytest ../tests -q      # or: python ../tests/test_rules.py
ipy ../tests/test_rules.py        # IronPython 2.7 (mono ipy.exe on Linux/macOS)
ipy ../tests/test_storage.py
```

- Pull requests are welcome. Please keep the hooks silent (no UI) and run the tests before submitting.

---

## FAQ

**Nothing happens on save.** Check that **Mappings → Run automatically** is on, that the mapping and its pairs are
enabled, and look in `push.log`.

**A parameter is missing from the list.** Parameters are discovered from the first 60 elements of a category (and
their types). Column B hides read-only parameters.

**Lengths come out in the wrong unit.** Conversions use **Manage → Project Units**. In rules, `value` is already in
display units.

**Lots of "blocked".** Those elements are borrowed by someone else or out of date with central. Reload Latest and
push again.

More in the built-in help (**Help** button, or **?** / F1 in any dialog).

---

## License

_Add a license before publishing (for example MIT) and place it in `LICENSE`._
