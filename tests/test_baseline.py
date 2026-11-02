import random
from pathlib import Path

from whippletree.baseline import baseline_findings, changed_lines
from whippletree.case import Case

DIFF = """diff --git a/x.py b/x.py
--- a/x.py
+++ b/x.py
@@ -1,3 +1,4 @@
 a
-b
+B
+C
 d
@@ -10,2 +11,1 @@
 j
-k
diff --git a/gone.py b/gone.py
--- a/gone.py
+++ /dev/null
@@ -1 +0,0 @@
-bye
"""


def test_changed_lines_use_head_line_numbers():
    # -b at head line 2 -> deletion point 1; +B -> 2; +C -> 3; -k after j(11) -> 11
    assert changed_lines(DIFF) == [("x.py", 1), ("x.py", 2), ("x.py", 3), ("x.py", 11)]


def _case():
    return Case(id="c", dataset="t", checkout_path=Path("."), diff=DIFF, ground_truth=())


def test_baseline_is_deterministic_for_a_seed():
    a = baseline_findings(_case(), 2, random.Random(0))
    b = baseline_findings(_case(), 2, random.Random(0))
    assert a == b and len(a) == 2
    assert all(f.claim == "baseline guess" for f in a)


def test_baseline_caps_at_available_lines():
    assert len(baseline_findings(_case(), 99, random.Random(0))) == 4
