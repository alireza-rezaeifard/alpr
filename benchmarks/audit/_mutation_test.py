import json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "results"))
VERIFY = os.path.join(HERE, "phase2c_verify.py")

MUTATIONS = []


def mut(name):
    def deco(fn):
        MUTATIONS.append((name, fn))
        return fn
    return deco


@mut("C1: exact numerator > denominator")
def m1(raw, summ):
    summ["per_run_summary"]["run0"]["detector_a_current|overall"]["exact"]["numerator"] = 999


@mut("C1: ratio value inconsistent with num/den")
def m1b(raw, summ):
    summ["per_run_summary"]["run0"]["detector_b_iranplate|overall"]["exact"]["value"] = 1.0


@mut("C2: inflated exact numerator")
def m2(raw, summ):
    summ["per_run_summary"]["run0"]["detector_b_iranplate|overall"]["exact"]["numerator"] = 62
    summ["per_run_summary"]["run0"]["detector_b_iranplate|overall"]["exact"]["value"] = 1.0


@mut("C2: wrong frames_without_detection")
def m2b(raw, summ):
    summ["per_run_summary"]["run0"]["detector_a_current|overall"]["frames_without_detection"] = 50


@mut("C3: failed count != blank OCR text")
def m3(raw, summ):
    summ["per_run_summary"]["run0"]["detector_a_current|overall"]["failed_rate_all_crops"]["numerator"] = 0
    summ["per_run_summary"]["run0"]["detector_a_current|overall"]["failed_rate_all_crops"]["value"] = 0.0


@mut("C4: UNLABELED record given a fake exact=True")
def m4(raw, summ):
    for r in raw["records"]:
        if r["gt_status"] == "UNLABELED":
            r["exact"] = True
            r["char_accuracy"] = 1.0
            r["edit_distance"] = 0
            break


@mut("C5: detector B evaluated on a different frame set")
def m5(raw, summ):
    # interval=5, so sampled frames are 0,5,10,... Use frame 5.
    for r in raw["records"]:
        if r["detector"] == "detector_b_iranplate" and r["frame"] == 5:
            r["frame"] = 999999


@mut("C5: protocol block duplicated per detector")
def m5b(raw, summ):
    summ["protocol"]["detector_a_current"] = {"conf": 0.9}
    raw["protocol"]["detector_a_current"] = {"conf": 0.9}


@mut("C6: NO_DETECTION frames dropped from the denominator")
def m6(raw, summ):
    raw["frame_rows"] = [f for f in raw["frame_rows"] if f["detected"]]
    summ["per_run_summary"]["run0"]["detector_a_current|overall"]["frames_total"] = 101
    summ["per_run_summary"]["run0"]["detector_a_current|overall"]["frames_without_detection"] = 0


@mut("C7: McNemar discordant count falsified")
def m7(raw, summ):
    summ["paired_statistics"]["all"]["discordant_pairs"] = 0
    summ["paired_statistics"]["all"]["mcnemar_exact_p"] = None


@mut("C7: McNemar table cell swapped")
def m7b(raw, summ):
    summ["paired_statistics"]["all"]["table"]["both_correct"] = 0
    summ["paired_statistics"]["cam1"]["table"]["a_correct_b_wrong"] = 0


@mut("C7: p-value outside [0,1]")
def m7c(raw, summ):
    summ["paired_statistics"]["all"]["mcnemar_exact_p"] = 1.7


@mut("C8: crop reassigned to the wrong width bucket")
def m8(raw, summ):
    b = summ["buckets"]["detector_a_current"]
    b["lt80"]["N"], b["ge200"]["N"] = b["ge200"]["N"], b["lt80"]["N"]


@mut("C8: bucket N no longer sums to detected crops")
def m8b(raw, summ):
    summ["buckets"]["detector_b_iranplate"]["100-149"]["N"] = 3


@mut("C9: fake 'identical' repeatability claim with divergent runs")
def m9(raw, summ):
    summ["repeatability"] = {"runs": 2, "identical": True,
                             "detector_a_current": [{}, {}],
                             "detector_b_iranplate": [{}, {}]}
    import copy
    extra = copy.deepcopy([r for r in raw["records"]
                           if r["run"] == "run0"
                           and r["detector"] == "detector_a_current"
                           and r["detection_status"] == "DETECTED"
                           and r["convention"] == "trunc"][:5])
    for r in extra:
        r["exact"] = False
        r["char_accuracy"] = 0.1
    by = {}
    for r in extra:
        by.setdefault((r["camera"], r["frame"]), []).append(r)
    for r in raw["records"]:
        if r["run"] == "run0" and r["detector"] == "detector_a_current" \
                and r["convention"] == "trunc" \
                and (r["camera"], r["frame"]) in by:
            r["exact"] = False
            r["char_accuracy"] = 0.1
    for r in raw["records"]:
        if r["run"] == "run0":
            r["run"] = "run1"
    for r in extra:
        r["run"] = "run1"
        raw["records"].append(r)
    for blk in summ["per_run_summary"]["run0"].values():
        pass
    summ["per_run_summary"]["run1"] = copy.deepcopy(summ["per_run_summary"]["run0"])


@mut("C11: canonical convention not one of the 5 allowed")
def m11(raw, summ):
    summ["canonical_convention"] = "banana"


def run_case(name, mutate):
    tmp = tempfile.mkdtemp(prefix="p2cv_")
    res = os.path.join(tmp, "results")
    shutil.copytree(SRC, res)
    rp = os.path.join(res, "phase2c_raw_results.json")
    sp = os.path.join(res, "phase2c_summary.json")
    raw = json.load(open(rp, encoding="utf-8"))
    summ = json.load(open(sp, encoding="utf-8"))
    mutate(raw, summ)
    json.dump(raw, open(rp, "w", encoding="utf-8"))
    json.dump(summ, open(sp, "w", encoding="utf-8"))
    env = dict(os.environ)
    env["P2C_RESULTS_DIR"] = res
    env["P2C_REPORT_PATH"] = os.path.join(tmp, "absent_report.md")
    p = subprocess.run([sys.executable, VERIFY], env=env, capture_output=True,
                       text=True)
    caught = p.returncode != 0
    shutil.rmtree(tmp, ignore_errors=True)
    return caught, p.returncode


ok = True


def run_case2(name, mutate, report_text=None):
    """Like run_case but optionally plants a report to exercise C10."""
    tmp = tempfile.mkdtemp(prefix="p2cv_")
    res = os.path.join(tmp, "results")
    shutil.copytree(SRC, res)
    rp = os.path.join(res, "phase2c_raw_results.json")
    sp = os.path.join(res, "phase2c_summary.json")
    raw = json.load(open(rp, encoding="utf-8"))
    summ = json.load(open(sp, encoding="utf-8"))
    if mutate:
        mutate(raw, summ)
    json.dump(raw, open(rp, "w", encoding="utf-8"))
    json.dump(summ, open(sp, "w", encoding="utf-8"))
    rp_path = os.path.join(tmp, "report.md")
    if report_text is not None:
        open(rp_path, "w", encoding="utf-8").write(report_text)
    env = dict(os.environ)
    env["P2C_RESULTS_DIR"] = res
    env["P2C_REPORT_PATH"] = rp_path
    p = subprocess.run([sys.executable, VERIFY], env=env, capture_output=True,
                       text=True)
    shutil.rmtree(tmp, ignore_errors=True)
    return p.returncode != 0, p.returncode, p.stdout


good_report = """
# Detector A/B benchmark
Detector A exact accuracy on labeled crops: 62/62 (100.0%).
Detector B exact accuracy: 56/62 (90.3%).
labeled crops = 62.
"""
bad_report = """
# Detector A/B benchmark
Detector A exact accuracy: 62/62.
Detector B exact accuracy: 60/62 (96.8%).
Detector A invalid rate: 34/101 = 33.7%.
"""

for label, text, want_fail in (("C10 consistent report", good_report, False),
                               ("C10 contradicting report", bad_report, True)):
    caught, rc, outp = run_case2(label, None, text)
    verdict = "CAUGHT " if caught else "MISSED!"
    if caught != want_fail:
        ok = False
        verdict += "  <-- UNEXPECTED"
    print("%s  rc=%-3s  %s" % (verdict, rc, label))

for name, fn in MUTATIONS:
    caught, rc = run_case(name, fn)
    status = "CAUGHT " if caught else "MISSED!"
    if not caught:
        ok = False
    print("%s  rc=%-3s  %s" % (status, rc, name))
print()
print("mutation testing: %s" % ("ALL MUTATIONS CAUGHT" if ok
                                else "SOME MUTATIONS MISSED"))
sys.exit(0 if ok else 1)