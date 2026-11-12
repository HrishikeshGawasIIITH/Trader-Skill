#!/usr/bin/env python3
"""PreToolUse guard for Trader-Skill. Standard library only.

1. DENY any tool call that touches a secret: ~/.trader/angel.env, any .env file,
   the Angel One session file, or the ANGEL_* secret variables.
2. ASK the user for every order command: angel.py place, protect, modify,
   convert, cancel, kill. The user's own click is the last gate.

Input: the hook JSON on stdin. Output: a permission decision as JSON.
"""

import json
import re
import sys

SECRET = re.compile(
    r"(angel\.env|angel_session|[\\/]\.trader([\\/]|\b)|(^|[\s\"'=\\/(])\.env(\.[\w-]+)?($|[\s\"'\\/;|&)])"
    r"|ANGEL_(API_KEY|MPIN|TOTP_SECRET|CLIENT_CODE)|\bprintenv\b|^\s*env\s*$|\bGet-ChildItem\s+env:|\bgci\s+env:"
    r"|\bdir\s+env:|\$env:ANGEL|\bls\s+env:)",
    re.I)
# Over-matching is safe here: it only adds a prompt.
ORDER_CMD = re.compile(r"angel\.py\b.*?\b(place|protect|modify|convert|cancel|kill)\b", re.I | re.S)


def strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings(v)


def decide(event):
    tool = event.get("tool_name", "")
    data = event.get("tool_input") or {}
    for s in strings(data):
        if SECRET.search(s):
            return "deny", ("Blocked by Trader-Skill: this %s call touches a secret (Angel One keys, a .env "
                            "file or the session file). Agents never read secrets. The user edits "
                            "~/.trader/angel.env by hand. Use `python angel.py doctor` to check setup." % tool)
    if tool in ("Bash", "PowerShell"):
        m = ORDER_CMD.search(str(data.get("command", "")))
        if m:
            return "ask", ("Trader-Skill order command `angel.py %s`. Check the ticket above, then approve "
                           "only if you said yes to this exact order." % m.group(1).lower())
    return None, None


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    decision, reason = decide(event)
    if decision:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "permissionDecision": decision,
                                                 "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
