# -*- coding: utf-8 -*-
"""The push engine: applies enabled mappings to the document."""
import time
import traceback

from Autodesk.Revit.DB import (
    CheckoutStatus, FailureProcessingResult, FailureSeverity,
    IFailuresPreprocessor, ModelUpdatesStatus, Transaction, WorksharingUtils
)

from pypipie import APP_NAME
from pypipie import revitutil as ru
from pypipie import convert as cv
from pypipie import relations
from pypipie import storage

# rules / guard are imported only when a pair actually runs a rule (see _rules()),
# so projects without rules never load the sandbox machinery.
_RULES = []


def _rules():
    if not _RULES:
        from pypipie import rules as _r
        from pypipie import guard as _g
        _RULES.extend([_r, _g])
    return _RULES


class _SwallowWarnings(IFailuresPreprocessor):
    """Keep save/sync/print/export silent: delete warnings, let errors roll back."""

    def PreprocessFailures(self, accessor):
        try:
            for f in accessor.GetFailureMessages():
                if f.GetSeverity() == FailureSeverity.Warning:
                    accessor.DeleteWarning(f)
        except Exception:
            pass
        return FailureProcessingResult.Continue


def _new_stats(mapping):
    return {
        "id": mapping.get("id"),
        "name": mapping.get("name", "?"),
        "targets": 0, "updated": 0, "unchanged": 0, "empty": 0,
        "failed": 0, "blocked": 0, "readonly": 0, "conflicts": 0,
        "missing_src": 0, "missing_dst": 0, "unmatched": 0, "ambiguous": 0,
        "rule_skipped": 0, "rule_errors": 0,
        "errors": [],
    }


class _Editability(object):
    """Worksharing guard: skip elements we can't (or shouldn't) edit."""

    def __init__(self, doc):
        self.doc = doc
        self.ws = doc.IsWorkshared
        self.cache = {}

    def ok(self, eid):
        if not self.ws:
            return True
        k = ru.eid_val(eid)
        if k not in self.cache:
            good = True
            try:
                if WorksharingUtils.GetCheckoutStatus(self.doc, eid) == CheckoutStatus.OwnedByOtherUser:
                    good = False
                elif WorksharingUtils.GetModelUpdatesStatus(self.doc, eid) == ModelUpdatesStatus.UpdatedInCentral:
                    good = False
            except Exception:
                pass
            self.cache[k] = good
        return self.cache[k]


def _run_mapping(doc, mapping, settings, units, editable, rule_cache=None):
    st = _new_stats(mapping)
    pairs_cfg = [p for p in mapping.get("pairs", []) if p.get("enabled", True)]
    if not pairs_cfg:
        st["errors"].append("No enabled parameter pairs.")
        return st

    if ru.category_from_key(doc, mapping.get("cat_a")) is None or \
       ru.category_from_key(doc, mapping.get("cat_b")) is None:
        st["errors"].append("Category not found in this project.")
        return st

    a_elems = ru.collect_instances(doc, mapping["cat_a"])
    b_elems = a_elems if mapping["cat_a"] == mapping["cat_b"] else \
        ru.collect_instances(doc, mapping["cat_b"])
    links = relations.build_pairs(doc, mapping, a_elems, b_elems, st)
    st["targets"] = len(links)

    push_empty = settings.get("push_empty", False)
    type_cache = {}
    if rule_cache is None:
        rule_cache = {}

    def host_of(el, is_type):
        if not is_type:
            return el
        k = ru.eid_val(el.Id)
        if k not in type_cache:
            type_cache[k] = ru.element_type(doc, el)
        return type_cache[k]

    for pi, pair in enumerate(pairs_cfg):
        src_ref, dst_ref = pair["src"], pair["dst"]
        if relations.is_self_pair(mapping.get("relation"), src_ref, dst_ref):
            st["errors"].append(u"Skipped '{}' -> itself on the same element.".format(ru.ref_label(src_ref)))
            continue
        fn = None
        if storage.rule_active(settings, pair):
            rules, rguard = _rules()
            if "cache" not in rule_cache:
                rule_cache["cache"] = rules.RuleCache()
            fn, rerr = rule_cache["cache"].get(pair["rule"].strip())
            if rerr is not None:
                st["errors"].append(u"Rule on '{}' not run: {}".format(ru.ref_label(dst_ref), rerr))
                continue
        elif cv.classify(src_ref, dst_ref)[0] == cv.INCOMPATIBLE:
            why = {storage.RULE_NONE: "needs a rule",
                   storage.RULE_OFF: "its rule is switched off",
                   storage.RULE_GLOBAL_OFF: "mapping rules are turned off for this project"}
            st["errors"].append(u"Skipped '{}' -> '{}': {}.".format(
                ru.ref_label(src_ref), ru.ref_label(dst_ref), why[storage.rule_state(settings, pair)]))
            continue
        first_rule_error = [None]
        written = {}  # target element id -> value written this run (conflict check)
        for a, b in links:
            src_host = host_of(a, src_ref.get("type"))
            dst_host = host_of(b, dst_ref.get("type"))
            if src_host is None or dst_host is None:
                st["missing_src" if src_host is None else "missing_dst"] += 1
                continue
            sp = ru.find_param(src_host, src_ref)
            if sp is None:
                st["missing_src"] += 1
                continue
            dp = ru.find_param(dst_host, dst_ref)
            if dp is None:
                st["missing_dst"] += 1
                continue
            if not ru.writable(dp, dst_host):
                st["readonly"] += 1
                continue

            if fn is not None and not pair.get("rule_empty") and cv.is_empty(sp):
                status, value = "empty", None  # like the standard conversion: empty stays empty
            elif fn is not None:
                if fn.budget.total > rguard.MAX_TOTAL_SECONDS:
                    st["errors"].append(u"Rule on '{}' stopped: it used more than {:.0f}s in this run.".format(
                        ru.ref_label(dst_ref), rguard.MAX_TOTAL_SECONDS))
                    break
                status, value, res = rules.evaluate(fn, units, a, b, sp, dp, dst_ref)
                if status == "error":
                    st["rule_errors"] += 1
                    if first_rule_error[0] is None:
                        first_rule_error[0] = res
                        st["errors"].append(u"Rule on '{}' failed for {} '{}': {}".format(
                            ru.ref_label(dst_ref), ru.eid_val(b.Id), ru.element_name(b), res))
                    continue
                if status == "skip":
                    st["rule_skipped"] += 1
                    continue
            else:
                try:
                    status, value = cv.convert(units, sp, src_ref, dp, dst_ref)
                except Exception:
                    status, value = "fail", None
            if status == "empty":
                if not push_empty:
                    st["empty"] += 1
                    continue
                value = cv.blank_for(dp)
                if value is None:
                    st["empty"] += 1
                    continue
            elif status != "ok":
                st["failed"] += 1
                continue

            tid = ru.eid_val(dst_host.Id)
            if tid in written:
                if not cv.values_equal(written[tid], value):
                    st["conflicts"] += 1  # e.g. two instances disagree on a type value
                continue
            written[tid] = value

            if cv.values_equal(cv.raw_value(dp), value):
                st["unchanged"] += 1
                continue
            if not editable.ok(dst_host.Id):
                st["blocked"] += 1
                continue
            try:
                if cv.set_value(dp, value):
                    st["updated"] += 1
                else:
                    st["failed"] += 1
            except Exception:
                st["failed"] += 1
    return st


def run(doc, cfg, trigger="manual", mapping_ids=None):
    """Push all enabled mappings (or just mapping_ids). Returns a report dict."""
    report = {"trigger": trigger, "doc": doc.Title, "mappings": [], "error": None,
              "seconds": 0.0, "updated": 0}
    t0 = time.time()
    if doc.IsReadOnly or doc.IsFamilyDocument:
        report["error"] = "Document is read-only or a family document."
        return report

    todo = []
    for m in cfg.get("mappings", []):
        if mapping_ids is not None:
            if m["id"] in mapping_ids:
                todo.append(m)
        elif m.get("enabled", True):
            todo.append(m)
    if not todo:
        report["error"] = "No enabled mappings."
        return report

    own = not doc.IsModifiable
    t = None
    if own:
        t = Transaction(doc, "{}: Push parameters ({})".format(APP_NAME, trigger))
        opts = t.GetFailureHandlingOptions()
        opts.SetFailuresPreprocessor(_SwallowWarnings())
        opts.SetClearAfterRollback(True)
        t.SetFailureHandlingOptions(opts)
        try:
            t.Start()
        except Exception as ex:
            report["error"] = "Document can't be modified during this event ({}).".format(ex)
            return report

    try:
        units = cv.Units(doc)
        editable = _Editability(doc)
        rule_cache = {}
        for m in todo:
            try:
                st = _run_mapping(doc, m, cfg.get("settings", {}), units, editable, rule_cache)
            except Exception:
                st = _new_stats(m)
                st["errors"].append(traceback.format_exc().strip().splitlines()[-1])
            report["mappings"].append(st)
            report["updated"] += st["updated"]
        if t is not None:
            if report["updated"]:
                t.Commit()
            else:
                t.RollBack()  # nothing changed - don't leave an empty undo step
    except Exception:
        report["error"] = traceback.format_exc()
        if t is not None and t.HasStarted() and not t.HasEnded():
            t.RollBack()
    report["seconds"] = round(time.time() - t0, 2)
    return report


def summarise(report):
    """Plain-text lines for logs."""
    lines = ["{} push [{}] on '{}' - {} updated in {}s".format(
        APP_NAME, report["trigger"], report["doc"], report["updated"], report["seconds"])]
    if report.get("error"):
        lines.append("  ERROR: " + report["error"].strip().splitlines()[-1])
    for st in report["mappings"]:
        lines.append("  {name}: {targets} linked, {updated} updated, {unchanged} unchanged, "
                     "{failed} failed, {blocked} blocked, {conflicts} conflicts, "
                     "{rule_skipped} skipped by rule, {rule_errors} rule errors".format(**st))
        for e in st["errors"]:
            lines.append("    ! " + e)
    return lines
