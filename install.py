#!/usr/bin/env python3
"""Install or update Trader-Skill. Standard library only.

    python install.py                      # copy every skill to ~/.claude/skills (default)
    python install.py --dest DIR           # copy to another skills folder
    python install.py --update             # git pull, then copy again
    python install.py --hooks              # also add the secret guard hook to ~/.claude/settings.json
    python install.py --dest PROJECT/.claude/skills --hooks --settings PROJECT/.claude/settings.json
                                           # install for one project folder only
    python install.py --check              # show what is installed; change nothing

It never touches your trading state (the trader/ folder where you work) or
your secrets (~/.trader/angel.env). It replaces only the skill folders it
installed before (listed in DEST/.trader-skill.json).
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DEST = os.path.join(os.path.expanduser("~"), ".claude", "skills")
SETTINGS = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
MANIFEST = ".trader-skill.json"
SKIP = {"tests", "__pycache__", ".git"}


def skills():
    return sorted(d for d in os.listdir(ROOT)
                  if os.path.isfile(os.path.join(ROOT, d, "SKILL.md")) and d not in SKIP)


def version():
    with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as fh:
        return fh.read().strip()


def git_pull():
    if not os.path.isdir(os.path.join(ROOT, ".git")):
        print("Not a git checkout: download the repo again to update.")
        return False
    r = subprocess.run(["git", "-C", ROOT, "pull", "--ff-only"], capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())
    return r.returncode == 0


def copy(dest):
    os.makedirs(dest, exist_ok=True)
    man_path = os.path.join(dest, MANIFEST)
    old = {}
    if os.path.exists(man_path):
        with open(man_path, encoding="utf-8") as fh:
            old = json.load(fh)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "tests", ".env", "*.env")
    names = skills()
    for name in set(old.get("skills", [])) - set(names):       # skills removed upstream
        shutil.rmtree(os.path.join(dest, name), ignore_errors=True)
    for name in names:
        target = os.path.join(dest, name)
        if os.path.exists(target) and name not in old.get("skills", []):
            print("SKIP %s: a folder with that name exists and this installer did not create it." % name)
            continue
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(os.path.join(ROOT, name), target, ignore=ignore)
    hooks = os.path.join(dest, "trader-skill-hooks")
    shutil.rmtree(hooks, ignore_errors=True)
    shutil.copytree(os.path.join(ROOT, "hooks"), hooks, ignore=ignore)
    with open(man_path, "w", encoding="utf-8") as fh:
        json.dump({"version": version(), "source": ROOT, "skills": names}, fh, indent=2)
    print("Installed Trader-Skill %s: %d skills in %s." % (version(), len(names), dest))
    return hooks


def add_hook(hooks_dir, settings=SETTINGS):
    guard = os.path.join(hooks_dir, "guard.py").replace("\\", "/")
    py = "python" if os.name == "nt" else "python3"
    entry = {"matcher": "Read|Write|Edit|MultiEdit|NotebookEdit|Grep|Glob|Bash|PowerShell",
             "hooks": [{"type": "command", "command": '%s "%s"' % (py, guard), "timeout": 10}]}
    cfg = {}
    if os.path.exists(settings):
        with open(settings, encoding="utf-8") as fh:
            cfg = json.load(fh)
        shutil.copy(settings, settings + ".bak")
    pre = cfg.setdefault("hooks", {}).setdefault("PreToolUse", [])
    pre[:] = [e for e in pre if "guard.py" not in json.dumps(e) or "trader-skill" not in json.dumps(e)]
    pre.append(entry)
    os.makedirs(os.path.dirname(settings), exist_ok=True)
    with open(settings, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    print("Added the secret guard hook to %s (backup: settings.json.bak)." % settings)


def check(dest):
    man_path = os.path.join(dest, MANIFEST)
    if not os.path.exists(man_path):
        print("Trader-Skill is not installed in %s." % dest)
        return
    with open(man_path, encoding="utf-8") as fh:
        man = json.load(fh)
    print("Installed: %s (%d skills). This checkout: %s." % (man["version"], len(man["skills"]), version()))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Install or update Trader-Skill.")
    ap.add_argument("--dest", default=DEFAULT_DEST)
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--hooks", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--settings", default=SETTINGS, help="settings.json that gets the hook (with --hooks)")
    a = ap.parse_args(argv)
    if a.check:
        check(a.dest)
        return 0
    if a.update and not git_pull():
        return 1
    hooks = copy(a.dest)
    if a.hooks:
        add_hook(hooks, a.settings)
    else:
        print("Secret guard: install as a plugin (it loads hooks/hooks.json), or run again with --hooks.")
    print("Next: create ~/.trader/angel.env yourself (see trader-broker/SKILL.md). Never paste keys in a chat.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
