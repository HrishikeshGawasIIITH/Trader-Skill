# Instructions for agents

Read this file before you install, update or use Trader-Skill.

## Rule 1: never touch secrets

- Never open, print, copy, search or edit `~/.trader/angel.env`.
- Never open `~/.trader/angel_session.json` or any `.env` file.
- Never print environment variables (`env`, `printenv`, `Get-ChildItem env:`, `echo $ANGEL_...`).
- Never ask the user to paste a key, MPIN or TOTP secret into the chat.
- To check the Angel One setup, run `python trader-broker/angel.py doctor`. It shows only "present" or "missing".
- If a task seems to need a secret, stop. Ask the user to do that step.

## Rule 2: never place an order on your own

- An order needs a trader-risk PASS, the user's typed yes, and the user's approval of the command prompt.
- Never approve a prompt for the user. Never retry a failed order. Never change `paper`, `broker` or `ANGEL_LIVE`.
- Never delete `trader/STOP`. Only the user deletes it.

## Install

Option A, plugin (this also loads the secret guard hook):

```
/plugin marketplace add https://github.com/HrishikeshGawasIIITH/Trader-Skill
/plugin install trader-skill@trader-skill
```

Option B, copy the skills:

```
git clone https://github.com/HrishikeshGawasIIITH/Trader-Skill
cd Trader-Skill
python install.py            # copies the skills to ~/.claude/skills
python install.py --hooks    # optional: adds the secret guard hook to ~/.claude/settings.json
```

Use `python install.py --dest <folder>` for an agent that reads skills from another folder.
Python 3.8 or newer is the only requirement. The scripts use the standard library only.

## Update

- Plugin: `/plugin marketplace update trader-skill`, then reinstall the plugin.
- Copied skills: `cd Trader-Skill && python install.py --update`. It runs `git pull` and copies the skills again.
- `python install.py --check` shows the installed version and the version of this checkout.
- An update never changes the user's `trader/` folder or `~/.trader/angel.env`.

## After install

1. Ask the user to follow the setup steps in `trader-broker/SKILL.md`. The user creates `~/.trader/angel.env` by hand.
2. Copy `trader-budget/config.example.json` to `trader/config.json` in the user's working folder.
3. Run `python trader-broker/angel.py doctor`.
4. Optional: add the free NSE data servers to the agent's MCP config:
   `https://mcp.nseindia.in/bhavcopy/cm/mcp` and `https://mcp.nseindia.in/cmmkt/mcp`.
   NSE provides this data for information. Do not use it as the price for an order.

## Tests

```
cd tests && python -m unittest discover -s .
```

Each analysis skill has its own tests in `<skill>/scripts/tests`.
The market health and analysis skills run with `python -m unittest discover -s <skill>/scripts/tests`.
The screener, earnings, planning, position-sizer and backtest skills need pytest: `cd <skill>/scripts && python -m pytest tests -q`.
The tests use fixtures only. They never connect to Angel One.
