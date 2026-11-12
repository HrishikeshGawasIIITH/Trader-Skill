"""Repo rules: every skill has frontmatter and a secrets block; no AI or upstream author names;
the plugin manifests point at the root; every script parses on Python 3.8."""

import ast
import json
import os
import re
import unittest

from _load import ROOT

SKIP_DIRS = {".git", "__pycache__", "tests", "fixtures"}
# Functional names the agent runtime needs; they are paths and variables, not attributions.
ALLOWED = re.compile(r"\.claude-plugin|CLAUDE_SKILL_DIR|CLAUDE_PLUGIN_ROOT|[\\/~]\.claude\b|\.claude[\\/]"
                     r"|os\.path\.join\(os\.path\.expanduser\(\"~\"\), \"\.claude\"", re.I)
BANNED = re.compile(r"\b(claude|anthropic|chatgpt|openai|schincariol|opusjake|tradermonty)\b", re.I)


def skill_dirs():
    return sorted(d for d in os.listdir(ROOT) if os.path.isfile(os.path.join(ROOT, d, "SKILL.md")))


def text_files():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith((".md", ".py", ".json", ".txt")) and f != "THIRD_PARTY_NOTICES.md":
                yield os.path.join(base, f)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class Repo(unittest.TestCase):
    def test_skills_have_frontmatter(self):
        self.assertGreaterEqual(len(skill_dirs()), 9)
        for s in skill_dirs():
            text = read(os.path.join(ROOT, s, "SKILL.md"))
            m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
            self.assertTrue(m, s)
            self.assertTrue("name: %s" % s in m.group(1) and "description:" in m.group(1), s)

    def test_every_skill_forbids_reading_secrets(self):
        for s in skill_dirs():
            low = read(os.path.join(ROOT, s, "SKILL.md")).lower()
            self.assertTrue("angel.env" in low and re.search(r"never (open|read)", low), s)

    def test_order_path_says_not_advice_and_needs_yes(self):
        for s in ("trader-risk", "trader-broker"):
            low = " ".join(read(os.path.join(ROOT, s, "SKILL.md")).lower().split())
            self.assertIn("not financial advice", low, s)
            self.assertIn("yes", low, s)

    def test_no_ai_or_upstream_author_names(self):
        bad = []
        for p in text_files():
            for i, line in enumerate(read(p).splitlines(), 1):
                if BANNED.search(ALLOWED.sub("", line)):
                    bad.append("%s:%d: %s" % (os.path.relpath(p, ROOT), i, line.strip()[:90]))
        self.assertEqual(bad, [])

    def test_plugin_manifests(self):
        plugin = json.loads(read(os.path.join(ROOT, ".claude-plugin", "plugin.json")))
        market = json.loads(read(os.path.join(ROOT, ".claude-plugin", "marketplace.json")))
        self.assertEqual(plugin["skills"], "./")
        self.assertEqual(plugin["version"], read(os.path.join(ROOT, "VERSION")).strip())
        self.assertEqual(market["plugins"][0]["source"], "./")
        hooks = json.loads(read(os.path.join(ROOT, "hooks", "hooks.json")))
        self.assertIn("guard.py", json.dumps(hooks))

    def test_every_script_parses_on_python_3_8(self):
        for base, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
            for f in files:
                if f.endswith(".py"):
                    p = os.path.join(base, f)
                    ast.parse(read(p), p, feature_version=(3, 8))

    def test_secrets_are_ignored_by_git(self):
        gi = read(os.path.join(ROOT, ".gitignore"))
        for pat in ("trader/", ".env", "angel_session.json"):
            self.assertIn(pat, gi)


if __name__ == "__main__":
    unittest.main()
