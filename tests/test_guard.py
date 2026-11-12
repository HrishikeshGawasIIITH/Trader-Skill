"""The PreToolUse guard: secrets are denied, order commands ask the user."""

import unittest

from _load import load

guard = load("hooks", "guard")


def d(tool, **inp):
    return guard.decide({"tool_name": tool, "tool_input": inp})[0]


class Guard(unittest.TestCase):
    def test_secret_files_are_denied(self):
        for path in ("C:/Users/x/.trader/angel.env", "~/.trader/angel_session.json", "/home/x/proj/.env",
                     r"C:\Users\x\.trader\angel.env", ".env.local"):
            self.assertEqual(d("Read", file_path=path), "deny", path)
        self.assertEqual(d("Bash", command="cat ~/.trader/angel.env"), "deny")
        self.assertEqual(d("Bash", command="printenv"), "deny")
        self.assertEqual(d("Bash", command="echo $ANGEL_MPIN"), "deny")
        self.assertEqual(d("PowerShell", command="Get-ChildItem env:"), "deny")
        self.assertEqual(d("PowerShell", command="$env:ANGEL_API_KEY"), "deny")
        self.assertEqual(d("Grep", pattern="MPIN", path="C:/Users/x/.trader"), "deny")

    def test_order_commands_ask(self):
        for c in ("place --index 1", "protect --index 1", "kill --flatten", "modify --order-id 5",
                  "convert --symbol SBIN", "cancel --order-id 5"):
            self.assertEqual(d("Bash", command='python "trader-broker/angel.py" ' + c), "ask", c)
        self.assertEqual(d("Bash", command="python angel.py --now \"2026-11-11 10:00\" place --index 1"), "ask")

    def test_normal_work_is_allowed(self):
        self.assertIsNone(d("Bash", command="python trader-broker/angel.py doctor"))
        self.assertIsNone(d("Bash", command="python trader-risk/check.py"))
        self.assertIsNone(d("Read", file_path="trader/orders.json"))
        self.assertIsNone(d("Read", file_path="trader-broker/SKILL.md"))
        self.assertIsNone(d("Bash", command="python -m venv venv && pip list"))


if __name__ == "__main__":
    unittest.main()
