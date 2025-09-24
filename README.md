# nexa-curl — Beautiful Windows‑friendly cURL REPL (history, presets, paste mode)

A tiny **cURL runner** for Windows/macOS/Linux that feels great to use:
- ✅ **REPL**: run multiple requests without restarting
- ✅ **Paste mode** for multi‑line `curl` (end with a single `.`)
- ✅ **Windows‑smart quotes**: converts `'single quotes'` → `"` automatically
- ✅ **History** (`:history`, `!N`) and **presets** (`:save`, `:load`)
- ✅ **Default headers**: set once (`:token`, `:accept`, `:ctype`)
- ✅ **Variables**: `:set KEY value` then use `{{KEY}}` anywhere
- ✅ Pretty output with [Rich](https://github.com/Textualize/rich): status, headers table, JSON/Raw body

> Perfect for running cURL copied from Postman or browser dev tools — especially on **Windows PowerShell** where single quotes break.

---

## Quick start

```bash
# 1) Create a venv (optional but recommended)
python -m venv .venv && . .venv/Scripts/activate  # Windows
# or: source .venv/bin/activate                    # macOS/Linux

# 2) Install
pip install -r requirements.txt

# 3) Run
python nexa_curl.py
```

**First use** (set defaults once):
```
:token token YOUR_TOKEN_HERE
:accept application/json
```

## Usage (REPL commands)

```
(empty line)    Re-run the last request
!N              Re-run history item N (see :history)
:history        Show recent history
:save NAME      Save last command as preset NAME
:load NAME      Load preset NAME (type `e` to execute)
:presets        List presets
:token VALUE    Set default Authorization header
:accept VALUE   Set default Accept header
:ctype VALUE    Set default Content-Type (blank = auto JSON for -d)
:headers        Show current defaults
:set K V        Define a variable (use as {{K}})
:vars           Show variables
:paste          Multi-line paste mode (end with `.`)
:help           Show help
:quit           Exit
```

**Examples**

```text
# Single-line GET
curl -s https://httpbin.org/get

# Multi-line POST (paste mode → end with .)
curl -s -X POST 'https://httpbin.org/post'   -H 'Accept: application/json'   -d '{"hello": "world"}'
.
```

## Install as a CLI (optional)

```bash
pip install .
# now you can run:
nexa-curl
```

## Why “nexa-curl”?
*Nexa* = “link/connection; next-gen” — a friendly helper to bridge Bash‑style curl into Windows and give you a fast inner loop.

## SEO keywords
curl runner, windows curl quotes, powershell curl single quotes, json pretty print curl, rich python cli, curl repl, paste mode curl, http debug cli

## License
MIT — see [LICENSE](LICENSE).
