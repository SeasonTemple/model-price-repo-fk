#!/usr/bin/env python3
"""Auto-resolve config.json conflicts during an upstream merge.

Runs after `git merge upstream/main`. If config.json is in a conflicted
(unmerged) state, performs a semantic 3-way deep merge of the JSON instead
of git's line-based merge:

  - dict keys are unioned recursively
  - upstream-added keys (absent in merge base) are pulled in
  - keys deleted on our side (present in base, gone in ours) stay deleted
  - on a genuine value conflict (both sides changed the same leaf), OUR
    value wins -- the fork's customizations are authoritative

If config.json merged cleanly (or isn't conflicted), this is a no-op.

Usage:
    python3 scripts/merge_config.py [--path config.json]

Exit codes:
    0  resolved (or nothing to do)
    1  could not parse one of the stages -> leave conflict for a human
"""

import argparse
import json
import subprocess
import sys


def git_show_stage(stage, path):
    """Return parsed JSON for an index stage (1=base, 2=ours, 3=theirs).

    Returns None if the stage does not exist (e.g. file added on one side).
    """
    res = subprocess.run(
        ["git", "show", f":{stage}:{path}"],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        return None
    return json.loads(res.stdout)


def is_unmerged(path):
    res = subprocess.run(
        ["git", "ls-files", "-u", "--", path],
        capture_output=True, text=True,
    )
    return bool(res.stdout.strip())


_MISSING = object()


def deep_merge(base, ours, theirs):
    """3-way deep merge preferring ours on true conflict."""
    # Both dicts -> recurse key by key.
    if isinstance(ours, dict) and isinstance(theirs, dict):
        base = base if isinstance(base, dict) else {}
        result = {}
        for key in list(ours.keys()) + [k for k in theirs.keys() if k not in ours]:
            o = ours.get(key, _MISSING)
            t = theirs.get(key, _MISSING)
            b = base.get(key, _MISSING)
            if o is not _MISSING and t is not _MISSING:
                result[key] = deep_merge(
                    None if b is _MISSING else b, o, t
                )
            elif o is not _MISSING:
                # Not on theirs: keep ours (theirs deleted or never had it).
                result[key] = o
            else:
                # Only on theirs: upstream addition (include) unless we deleted
                # it (present in base, absent in ours).
                if b is _MISSING:
                    result[key] = t
                # else: deleted on our side -> honour deletion (skip)
        return result

    # Leaf (or type mismatch): ours-changed wins, else theirs-changed, else ours.
    if ours != base:
        return ours
    if theirs != base:
        return theirs
    return ours


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default="config.json")
    args = ap.parse_args()
    path = args.path

    if not is_unmerged(path):
        print(f"{path}: no conflict, nothing to resolve")
        return 0

    try:
        base = git_show_stage(1, path)    # merge base
        ours = git_show_stage(2, path)    # HEAD / fork
        theirs = git_show_stage(3, path)  # upstream
    except json.JSONDecodeError as exc:
        print(f"ERROR: could not parse a conflict stage: {exc}", file=sys.stderr)
        return 1

    if ours is None or theirs is None:
        print("ERROR: missing ours/theirs stage; leaving conflict", file=sys.stderr)
        return 1

    merged = deep_merge(base or {}, ours, theirs)

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    subprocess.run(["git", "add", "--", path], check=True)
    print(f"{path}: semantically merged (upstream additions in, fork values kept)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
