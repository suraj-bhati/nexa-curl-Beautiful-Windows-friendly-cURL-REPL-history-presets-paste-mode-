import os, re, sys, json, subprocess
from datetime import datetime
from typing import Dict, Any, List, Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.syntax import Syntax
from rich.text import Text

console = Console()

def _app_dir() -> str:
    if os.name == "nt":
        base = os.getenv("APPDATA") or os.path.expanduser("~")
        d = os.path.join(base, "CurlRunner")
    else:
        d = os.path.join(os.path.expanduser("~"), ".config", "curl_runner")
    os.makedirs(d, exist_ok=True)
    return d

CFG_PATH = os.path.join(_app_dir(), "config.json")
HIST_PATH = os.path.join(_app_dir(), "history.json")
PRESETS_PATH = os.path.join(_app_dir(), "presets.json")

MASK_KEYS = ["authorization", "x-api-key", "api-key", "apikey", "token", "bearer"]

DEFAULT_CFG = {
    "defaults": {
        "authorization": "",
        "accept": "application/json",
        "content_type": "",
    },
    "vars": {}
}

def load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

CONFIG = load_json(CFG_PATH, DEFAULT_CFG)
HISTORY: List[Dict[str, Any]] = load_json(HIST_PATH, [])
PRESETS: Dict[str, str] = load_json(PRESETS_PATH, {})

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def mask_sensitive(s: str) -> str:
    def mask_value(v: str) -> str:
        v = v.strip()
        if len(v) <= 8: return "*" * len(v)
        return v[:4] + "*" * (len(v)-8) + v[-4:]
    for k in MASK_KEYS:
        s = re.sub(
            rf"({k}\s*:\s*)([^\r\n;]+)",
            lambda m: m.group(1) + mask_value(m.group(2)),
            s, flags=re.IGNORECASE)
        s = re.sub(
            rf"({k}\s*=\s*)([^&\s]+)",
            lambda m: m.group(1) + mask_value(m.group(2)),
            s, flags=re.IGNORECASE)
        s = re.sub(
            rf"(-H|--header)\s+(['\"])({k})\s*:\s*([^'\"]+)\2",
            lambda m: f"{m.group(1)} {m.group(2)}{m.group(3)}: {mask_value(m.group(4))}{m.group(2)}",
            s, flags=re.IGNORECASE)
    return s

def read_multiline():
    console.print(Panel("Paste your full curl (multi-line OK).\nEnd with a single dot `.` on its own line.", title="Paste Mode", style="cyan"))
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == ".":
            break
        lines.append(line)
    text = "\n".join(lines)
    text = re.sub(r"\\\r?\n", " ", text)
    text = re.sub(r"`\r?\n", " ", text)
    text = re.sub(r"\^\r?\n", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def ensure_curl_prefix(cmd: str) -> str:
    return cmd if cmd.lstrip().lower().startswith("curl") else "curl " + cmd

def _single_to_double_state_machine(s: str) -> str:
    out = []
    i = 0
    n = len(s)
    in_single = False
    in_double = False
    while i < n:
        ch = s[i]
        if in_single:
            if ch == "'":
                out.append('"'); in_single = False
            else:
                out.append('\\"' if ch == '"' else ch)
            i += 1; continue
        if in_double:
            out.append(ch)
            if ch == '"' and (i == 0 or s[i-1] != '\\'):
                in_double = False
            i += 1; continue
        if ch == "'":
            out.append('"'); in_single = True; i += 1; continue
        if ch == '"':
            in_double = True; out.append(ch); i += 1; continue
        out.append(ch); i += 1
    if in_single: out.append('"')
    return "".join(out)

def normalize_for_windows(cmd: str) -> str:
    return _single_to_double_state_machine(cmd) if os.name == "nt" else cmd

def inject_writeout(cmd: str) -> str:
    if re.search(r"(^|\s)(-w|--write-out)\b", cmd):
        return cmd
    return cmd + r' -sS -i -w "\n__CURL_CODE__:%{http_code}\n__CURL_TIME__:%{time_total}\n__CURL_IP__:%{remote_ip}\n"'

def apply_vars(text: str, vars_dict: Dict[str, str]) -> str:
    def repl(m):
        key = m.group(1)
        return str(vars_dict.get(key, m.group(0)))
    return re.sub(r"\{\{(\w+)\}\}", repl, text)

def add_default_headers(cmd: str) -> str:
    if CONFIG["defaults"].get("authorization") and not re.search(r"(?i)(^|\s)(-H|--header)\s+(['\"])authorization:", cmd):
        auth = CONFIG["defaults"]["authorization"]
        cmd += f' -H "Authorization: {auth}"'
    if CONFIG["defaults"].get("accept") and not re.search(r"(?i)(^|\s)(-H|--header)\s+(['\"])accept:", cmd):
        cmd += f' -H "Accept: {CONFIG["defaults"]["accept"]}"'
    if re.search(r"(?i)\s-X\s+(POST|PUT|PATCH)\b", cmd) or re.search(r"(?i)\s(--data|-d|--data-raw|--data-binary)\b", cmd):
        if not re.search(r"(?i)(^|\s)(-H|--header)\s+(['\"])content-type:", cmd):
            ctype = CONFIG["defaults"].get("content_type") or "application/json"
            cmd += f' -H "Content-Type: {ctype}"'
    return cmd

def run_curl(command: str):
    return subprocess.run(command, shell=True, capture_output=True, text=True)

def split_headers_body_and_markers(stdout: str):
    code = time_total = remote_ip = None
    m = re.search(r"\n__CURL_CODE__:(\d+)\n__CURL_TIME__:(\d+(?:\.\d+)?)\n__CURL_IP__:(.*?)\n?$", stdout, re.DOTALL)
    if m:
        code = int(m.group(1)); time_total = float(m.group(2)); remote_ip = (m.group(3) or "").strip() or None
        stdout = stdout[: m.start()]
    parts = re.split(r"\r?\n\r?\n", stdout, maxsplit=1)
    headers_text, body_text = (parts + [""])[:2] if len(parts) == 2 else ("", stdout)
    return headers_text.strip(), body_text, code, time_total, remote_ip

def render(command_shown: str, result, headers_text, body_text, code, time_total, remote_ip):
    console.rule("[bold green]nexa-curl[/bold green]")
    console.print(Panel(mask_sensitive(command_shown), title=f"Command @ {now_str()}", style="bold"))
    status = Table(box=None); status.add_column("Field", style="bold cyan"); status.add_column("Value")
    status.add_row("Exit Code", str(result.returncode))
    status.add_row("HTTP Status", str(code) if code is not None else "—")
    if time_total is not None: status.add_row("Total Time (s)", f"{time_total:.3f}")
    if remote_ip: status.add_row("Remote IP", remote_ip)
    console.print(Panel(status, title="Status", style="green" if result.returncode == 0 else "red"))
    if headers_text:
        ht = Table(show_header=True, header_style="bold magenta"); ht.add_column("Header"); ht.add_column("Value")
        for line in headers_text.splitlines():
            if not line.strip(): continue
            if ":" in line:
                k, v = line.split(":", 1); ht.add_row(k.strip(), mask_sensitive(v.strip()))
            else:
                ht.add_row("(status)", line.strip())
        console.print(Panel(ht, title="Response Headers", style="cyan"))
    if body_text:
        bt = body_text.strip()
        try:
            parsed = json.loads(bt)
            pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
            console.print(Panel(Syntax(pretty, "json", line_numbers=True), title="Response Body (JSON)", style="green"))
        except Exception:
            console.print(Panel(Syntax(bt, "text", line_numbers=True), title="Response Body (Raw)", style="yellow"))
    if result.stderr:
        console.print(Panel(Text(result.stderr.strip(), style="red"), title="stderr", style="red"))

def exec_curl(user_input: str, remember: bool = True):
    cmd_vars = apply_vars(user_input, CONFIG.get("vars", {}))
    cmd = ensure_curl_prefix(cmd_vars)
    cmd = normalize_for_windows(cmd)
    cmd = add_default_headers(cmd)
    cmd_to_run = inject_writeout(cmd)
    result = run_curl(cmd_to_run)
    headers_text, body_text, code, time_total, remote_ip = split_headers_body_and_markers(result.stdout)
    render(cmd, result, headers_text, body_text, code, time_total, remote_ip)
    if remember:
        HISTORY.append({
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cmd": user_input,
            "expanded_cmd": cmd,
            "status": code,
        })
        save_json(HIST_PATH, HISTORY)

HELP = """
Commands:
  (empty line)     Re-run the last request
  !N               Re-run history item N (shown by :history)
  :history         Show recent history
  :save NAME       Save last command as preset NAME
  :load NAME       Load preset NAME (type 'e' to execute)
  :presets         List presets
  :token VALUE     Set default Authorization header (e.g. 'token abc:xyz' or 'Bearer X')
  :accept VALUE    Set default Accept (e.g. application/json)
  :ctype VALUE     Set default Content-Type (blank = auto for JSON)
  :headers         Show current defaults
  :set KEY VALUE   Define a variable (use as {{KEY}} in curl/JSON)
  :vars            Show variables
  :paste           Enter multi-line paste mode (end with a single .)
  :help            Show this help
  :quit / :q       Exit
"""

def show_history():
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("ID"); table.add_column("Time"); table.add_column("HTTP"); table.add_column("Command (masked)")
    start = max(0, len(HISTORY) - 20)
    for idx in range(start, len(HISTORY)):
        h = HISTORY[idx]
        table.add_row(str(idx+1), h.get("ts",""), str(h.get("status","—")), mask_sensitive(h.get("expanded_cmd") or h.get("cmd")))
    console.print(Panel(table, title="History (last 20)"))

def show_headers_defaults():
    d = CONFIG["defaults"]
    t = Table(show_header=False)
    t.add_column("Key", style="bold cyan"); t.add_column("Value")
    t.add_row("Authorization", mask_sensitive(d.get("authorization","") or "(none)"))
    t.add_row("Accept", d.get("accept","") or "(none)"))
    t.add_row("Content-Type", d.get("content_type","") or "(auto: JSON for -d)")
    console.print(Panel(t, title="Default Headers"))

def show_vars():
    if not CONFIG.get("vars"):
        console.print(Panel("No variables set. Use `:set KEY value` and reference as {{KEY}}.", title="Vars", style="cyan"))
        return
    t = Table(show_header=True, header_style="bold magenta"); t.add_column("Key"); t.add_column("Value")
    for k, v in CONFIG["vars"].items():
        t.add_row(k, v)
    console.print(Panel(t, title="Vars"))

def read_multiline_wrapper():
    buf = read_multiline()
    if buf:
        exec_curl(buf)
        return buf
    else:
        console.print("[yellow]Nothing pasted.[/yellow]")
        return None

def repl():
    console.print("[bold cyan]nexa-curl (REPL) — no restart needed[/bold cyan]. Type :help for commands.")
    last_cmd: Optional[str] = None
    loaded_buffer: Optional[str] = None

    while True:
        try:
            line = input("curl> ").rstrip()
        except (EOFError, KeyboardInterrupt):
            line = ":quit"

        if not line:
            if last_cmd:
                exec_curl(last_cmd)
            else:
                console.print("[yellow]No last command.[/yellow]")
            continue

        if line.startswith(":"):
            cmd = line.strip()
            if cmd in (":quit", ":q"):
                save_json(CFG_PATH, CONFIG); console.print("Bye!"); break
            if cmd == ":help":
                console.print(Panel(HELP, title="Help")); continue
            if cmd == ":history":
                show_history(); continue
            if cmd == ":presets":
                if not PRESETS: console.print("[yellow]No presets saved.[/yellow]"); continue
                table = Table(show_header=True, header_style="bold magenta"); table.add_column("Name"); table.add_column("Command (masked)")
                for name, val in PRESETS.items():
                    table.add_row(name, mask_sensitive(val))
                console.print(Panel(table, title="Presets")); continue
            if cmd == ":headers":
                show_headers_defaults(); continue
            if cmd == ":vars":
                show_vars(); continue
            if cmd == ":paste":
                buf = read_multiline_wrapper()
                if buf: last_cmd = buf
                continue
            if cmd.startswith(":save "):
                name = cmd.split(" ",1)[1].strip()
                if not last_cmd: console.print("[yellow]Nothing to save (no last command).[/yellow]"); continue
                PRESETS[name] = last_cmd; save_json(PRESETS_PATH, PRESETS)
                console.print(f"[green]Saved preset[/green] {name}."); continue
            if cmd.startswith(":load "):
                name = cmd.split(" ",1)[1].strip()
                if name not in PRESETS: console.print(f"[red]Preset '{name}' not found.[/red]"); continue
                loaded_buffer = PRESETS[name]
                console.print(Panel(mask_sensitive(loaded_buffer), title=f"Loaded preset: {name}", style="cyan"))
                continue
            if cmd.startswith(":token "):
                CONFIG["defaults"]["authorization"] = cmd.split(" ",1)[1].strip()
                save_json(CFG_PATH, CONFIG); console.print("[green]Authorization updated.[/green]"); continue
            if cmd.startswith(":accept "):
                CONFIG["defaults"]["accept"] = cmd.split(" ",1)[1].strip()
                save_json(CFG_PATH, CONFIG); console.print("[green]Accept updated.[/green]"); continue
            if cmd.startswith(":ctype "):
                CONFIG["defaults"]["content_type"] = cmd.split(" ",1)[1].strip()
                save_json(CFG_PATH, CONFIG); console.print("[green]Content-Type default updated.[/green]"); continue
            if cmd.startswith(":set "):
                try:
                    _, key, value = cmd.split(" ", 2)
                    CONFIG["vars"][key] = value; save_json(CFG_PATH, CONFIG)
                    console.print(f"[green]Set[/green] {key} = {value}")
                except ValueError:
                    console.print("[red]Usage:[/red] :set KEY VALUE")
                continue

            console.print("[yellow]Unknown command. Try :help[/yellow]")
            continue

        if line.startswith("!"):
            try:
                n = int(line[1:])
                if 1 <= n <= len(HISTORY):
                    selected = HISTORY[n-1]["cmd"]
                    exec_curl(selected); last_cmd = selected
                else:
                    console.print("[red]Invalid history ID.[/red]")
            except Exception:
                console.print("[red]Usage: !N (number from :history)[/red]")
            continue

        if loaded_buffer and line.strip().lower() == "e":
            exec_curl(loaded_buffer); last_cmd = loaded_buffer; loaded_buffer = None; continue

        if re.match(r"^https?://", line.strip(), re.I):
            line = f'curl -s "{line.strip()}"'

        exec_curl(line); last_cmd = line; loaded_buffer = None

def main():
    repl()

if __name__ == "__main__":
    main()
