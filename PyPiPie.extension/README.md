# PyPiPie – Parameter Pusher

Push parameter values from elements of category **A** to related elements of category **B**.
Mappings are stored in the project (Extensible Storage) and run automatically on
**save, sync with central, before print and before export**, or on demand.

## Install
Copy `PyPiPie.extension` into a folder registered under pyRevit → Settings → Custom
Extension Directories, then Reload. Requires Revit 2022+ (ForgeTypeId API) and the
default IronPython engine. Theme following needs Revit 2024+ (older versions use light).

## Buttons (PyPiPie tab → Param Pusher)
| Button | What it does |
|---|---|
| **Map Parameters** | Pick category A and B, choose how B finds its A element, pair parameters, **Apply**. The window stays open for the next mapping. Double-click a parameter to add the pair. |
| **Mappings** | Report of every mapping and pair: enable/disable, edit, delete, import/export JSON, push selected/all, automatic-run settings. |
| **Push Now** | Runs all enabled mappings and shows the results (Shift+Click = silent). |
| **Help** | Opens `help/PyPiPie_Help.html`. Every dialog also has a **?** button and answers **F1**, opening the matching section in the current Revit theme. |

## Two ways to push
* **Same category → same category** (e.g. Doors → Doors): push one parameter into a *different*
  parameter. With **Same element** the value is copied within each element (instance ↔ type
  works too); a parameter can't be pushed onto itself there. Other same-category relationships
  (matching key, parent family → nested, parent view → dependent views) push between related
  elements, so the same parameter name is allowed.
* **Category A → different category B** (e.g. Rooms → Doors): push into the same-name parameter
  or a different one. **Auto-pair same names** pairs every compatible same-name parameter in one click.

The relationship list greys out options that don't fit the chosen categories and picks a sensible
default (Same element for same category, Room/Space/Level/Sheet/… when A is that category,
otherwise Matching key value).

## Relationships (how a B element finds its A element)
Same element · Matching key value (A.key = B.key; never matches itself) · Host → hosted ·
Room → elements in room · Space → elements in space · Level → elements on level ·
Sheet → placed views · Parent view → dependent views · Parent family → nested ·
Assembly → members · Group → members

**Read-only targets** are filtered out of column B: a parameter is hidden if it is read-only on
any sampled element or type (computed values, formula-driven parameters, Family/Category/ID/Host
and similar). Elements that are read-only only because they sit in a group or are locked to a global
parameter don't hide the parameter; at push time every target is re-checked and anything not
writable is skipped and counted as *read-only target*.

Type parameters are read from / written to the element's type. If several instances
of one type would write different values to the same type parameter, the first wins
and the rest are counted as conflicts.

## Mapping rules (ƒ)
Every pair can carry a small Python rule that transforms the incoming value before it is written.
Click **ƒ** on a pair (in Map Parameters or Mappings). A pair whose types don't convert on their
own (e.g. Length → Yes/No) can still be added — with a rule that produces the target value.

```python
# one expression
value * 1.10 + 2
when(value < 100, "Small", value < 500, "Medium", "Large")
"RM-{}".format(pad(to_int(value), 3))

# or a short script that sets / returns value
value = switch(value, {"A": "Alpha", "B": "Bravo"}, default=value)
if target not in (None, ""):
    return SKIP          # leave existing values alone
```

| In a rule | |
|---|---|
| `value` | incoming value: text, number in **display units**, True/False for Yes/No, element name, or None |
| `text` | source as displayed in Revit |
| `target` | current target value |
| `a("Param")`, `b("Param")` | read any other parameter of the A / B element by name |
| `a_info`, `b_info` | `{'id', 'name', 'category'}` |
| result | set/return `value`; `SKIP` = don't touch the target; `None`/`""` = empty |

Helpers: `switch`, `when`, `iff`, `between`, `num`, `to_int`, `as_bool`, `fmt`, `round_to`,
`floor_to`, `ceil_to`, `clamp`, `pad`, `join`, `contains`, `re_find`, `re_test`, `re_sub`,
`text_of`, plus `floor ceil sqrt pi sin cos tan radians degrees log log10 hypot` and the usual
`abs min max round len sum sorted str int float`. The editor has templates, a **Test** box and a
**Preview on model** dry-run (first linked elements, nothing written).

**Sandbox.** Rules run automatically on save/sync and can arrive in imported files, so they are
restricted: no `import`, `while`, `def`/`class`, `try`, `open`/`eval`/`getattr`; no `_private`
or .NET (`Capitalised`) attributes; only plain values go in; `range()` is capped at 10,000.
A rule that throws is counted per element in the push report and never stops the save.

**Pathological rules.** Three layers keep a rule from stalling Revit:
1. *Static check while you type* – blocks things that can never finish (`10**10**10`, `2**100000`,
   `'x' * 10**9`, `range(10**8)`, huge format widths, self-calling lambdas) and warns about risky
   patterns (data-driven exponents or repetition, nested loops, regexes like `(a+)+`).
2. *Runtime guards compiled into every rule* – each element gets ≤ 0.5 s, ≤ 100,000 loop
   iterations, text/lists ≤ 1,000,000 items, integers ≤ 4,096 bits, 20 M items built in total;
   regex calls time out after 0.25 s (.NET Regex timeout); a rule is stopped after 15 s total per push.
   A tripped guard is reported as a rule error for that element; the save/sync continues.
3. *Sandbox test* – runs the rule on ~28 probe values (empty, 0, ±1, ±1e6, Yes/No, long text,
   with and without an existing target value) on a background thread with a 3 s limit.
   **Test & save** always runs it: a rule that doesn't finish can't be saved; guard trips or
   warnings need an explicit *Save anyway*.

## Data-type rules
| Level | Meaning |
|---|---|
| ✓ exact | Same storage and data type – internal value copied |
| ↻ converts | Number → text (formatted with project units), Number spec ↔ measurable spec via display units, Element → its name |
| ⚠ lossy | Text parsed into numbers/lengths (`10' 6"`, `3.5 m²`), Yes/No coercion, rounding to integer, text → element by name |
| ✕ incompatible | Blocked (e.g. Length → Area, Element → Number, read-only targets) |

## Behaviour during events
* Hooks never show UI. Results/errors go to `%APPDATA%\pyRevit\PyPiPie\push.log`.
* Unchanged values are not rewritten, so elements aren't borrowed needlessly.
* Workshared: elements owned by someone else or updated in central are skipped (counted as *blocked*).
* Warnings raised while pushing are suppressed; a run that changes nothing leaves no undo entry.
* If Revit refuses modifications during an event (possible for some print/export paths), the run is skipped and logged.

## Import / export
Export writes JSON. Categories are stored as `BuiltInCategory` names and parameters
by BuiltInParameter name, shared-parameter GUID, or name, so mappings carry to other projects.
On import choose **Merge** (same mapping id replaces) or **Replace all**.

## Files
```
lib/pypipie/   revitutil, convert (type rules + conversions), relations, storage,
               engine, hookrunner, rules (sandbox + helpers), rule_editor, ui (theme), mapper, manager
hooks/         doc-saving, doc-saving-as, doc-syncing, doc-printing, doc-exporting
help/          PyPiPie_Help.html (full user guide)
```
