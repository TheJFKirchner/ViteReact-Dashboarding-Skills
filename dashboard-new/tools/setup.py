"""Make a new dashboard project from this skill's starter.

    python <skill>/tools/setup.py <new project folder> --title "Claims dashboard"
        [--keep-examples]   keep the two example cards and their sample data (handy for a first look)
        [--no-install]      skip npm install

What it does, and nothing else:
  - copies starter/ and themes/ (as Themes/) into the folder, which must be new or empty
    (dot-folders like .git or .claude are fine)
  - removes the example cards, their numbers, sample-data script and report (unless --keep-examples)
  - sets the title, picks a free port for the data server, and records where the design agent lives
    (the dashboard-work skill next to this one, or the standard install)
  - runs npm install, checks the Python packages, and runs npm run check

It never writes outside the new folder and never overwrites a file. Safe to re-run on a failed attempt only
after emptying the folder.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
STARTER = SKILL / "starter"
THEMES = SKILL / "themes"
# the design agent lives in the dashboard-work skill, normally installed next to this one
STANDARD_HOME = Path.home() / ".claude" / "skills" / "dashboard-work"
WORK_CANDIDATES = [SKILL.parent / "dashboard-work", STANDARD_HOME]
EXAMPLES = [
    "Src/Sections/s1_summary.jsx",
    "Src/Sections/s2_revenue_trend.jsx",
    "Analysis/example.py",
    "Pipeline/example_sales_monthly.py",
    "Reports/example.json",
]
EMPTY_INDEX = """// The cards in the order they appear, and the pages (tabs) if there are any.
// npm run new-card -- <name> adds to these lists; editing by hand is fine too.
// One page: leave `tabs` empty and give cards no meta.tab. Pages: list them here and give each card a meta.tab.

export const tabs = [];

export default [];
"""
PY_PACKAGES = ["fastapi", "uvicorn", "duckdb", "pyarrow", "pandas"]
IGNORE = shutil.ignore_patterns("node_modules", "__pycache__", "*.pyc", ".vite*", ".export", ".dashboard-agent")


def say(msg: str = "") -> None:
    print(msg, flush=True)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "dashboard"


def free_port(start: int = 8765, tries: int = 200) -> int:
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start


def run(cmd: list[str], cwd: Path, quiet: bool = False) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, shell=(os.name == "nt"))
    except FileNotFoundError:
        return 127, f"{cmd[0]} not found"
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser(description="Make a new dashboard project from the starter.")
    ap.add_argument("folder", help="the new project folder (created if missing; must be empty)")
    ap.add_argument("--title", default=None, help="dashboard title (default: the folder name)")
    ap.add_argument("--keep-examples", action="store_true", help="keep the example cards and sample data")
    ap.add_argument("--no-install", action="store_true", help="skip npm install and the check")
    a = ap.parse_args()

    dest = Path(a.folder).expanduser().resolve()
    title = a.title or dest.name.replace("-", " ").replace("_", " ").strip().title()

    # ---- the folder must be new or empty (dot-folders allowed)
    if dest.exists() and not dest.is_dir():
        say(f"setup: {dest} is a file, not a folder. Pick a folder name.")
        return 1
    if dest.exists():
        contents = [p for p in dest.iterdir() if not p.name.startswith(".")]
        if contents:
            names = ", ".join(sorted(p.name for p in contents)[:8])
            say(f"setup: {dest} isn't empty ({names}{', ...' if len(contents) > 8 else ''}).")
            say("  Nothing was changed. Use a new folder, e.g. a 'dashboard' subfolder inside it.")
            return 1
    try:
        if dest.is_relative_to(SKILL):
            say("setup: the project can't go inside the skill folder. Pick another place.")
            return 1
    except AttributeError:
        pass
    if "onedrive" in str(dest).lower():
        say("note: this folder is in OneDrive. It works, but the installed packages (node_modules) sync slowly;")
        say("      a folder outside OneDrive is better if you have the choice.")

    # ---- copy
    say(f"Setting up '{title}' in {dest}")
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(STARTER, dest, ignore=IGNORE, dirs_exist_ok=True)
    shutil.copytree(THEMES, dest / "Themes", ignore=IGNORE, dirs_exist_ok=True)
    (dest / "Data" / "Current").mkdir(parents=True, exist_ok=True)
    say("  copied the starter and themes")

    if not a.keep_examples:
        for rel in EXAMPLES:
            (dest / rel).unlink(missing_ok=True)
        (dest / "Src" / "Sections" / "index.js").write_text(EMPTY_INDEX, encoding="utf-8")
        say("  removed the example cards (add your own with: npm run new-card -- <name>)")

    # ---- config
    cfg_path = dest / "dashboard.config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["project"] = slug(dest.name)
    cfg["title"] = title
    if not a.keep_examples:
        cfg["dataSource"] = ""
        # the example's "region" filter belongs to the sample data; real filters are added once the data is known
        cfg["filters"] = {"_note": "Filters readers can use, e.g. \"region\": {\"label\": \"Region\", \"column\": \"region\"}. "
                                   "They apply to every table with that column. See the dashboard-work skill, references/data.md."}
    port = free_port(8765)
    cfg.setdefault("server", {})["port"] = port
    agent = cfg.setdefault("agent", {})
    # record the dashboard-work skill unless it IS the standard install: a machine-wide DASHBOARD_AGENT_HOME may
    # point at another version, and the project's own setting wins over it
    work = next((c.resolve() for c in WORK_CANDIDATES if (c / "agent" / "vite-plugin.js").exists()), None)
    if work is None:
        say("  design agent: the dashboard-work skill wasn't found next to this one or in ~/.claude/skills.")
        say("    The dashboard works without it; to add it later set \"agent\": {\"home\": \"<dashboard-work folder>\"}")
        say("    in dashboard.config.json.")
    elif not (STANDARD_HOME.exists() and STANDARD_HOME.resolve() == work):
        agent["home"] = str(work)
        say(f"  design agent: {work} (recorded in dashboard.config.json)")
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    say(f"  title set; data server port {port}")

    # ---- install and check
    problems = []
    if not a.no_install:
        say("  npm install (a minute or two)...")
        code, text = run(["npm", "install", "--no-audit", "--no-fund"], dest)
        if code != 0:
            problems.append("npm install failed: " + text.strip().splitlines()[-1] if text.strip() else "npm install failed")
    missing = []
    for pkg in PY_PACKAGES:
        code, _ = run([sys.executable, "-c", f"import {pkg}"], dest)
        if code != 0:
            missing.append(pkg)
    if missing:
        problems.append(f"Python packages missing: {' '.join(missing)}  ->  pip install {' '.join(missing)}")
    if a.keep_examples and not missing:
        code, text = run([sys.executable, "Pipeline/run_all.py"], dest)
        say("  made the sample data" if code == 0 else "  sample data failed: " + text.strip().splitlines()[-1])
    if not a.no_install and not problems:
        code, text = run(["npm", "run", "check", "--silent"], dest)
        last = [l for l in text.strip().splitlines() if l.strip()]
        say(f"  check: {last[-1] if last else 'no output'}")

    say()
    for p in problems:
        say(f"TO DO: {p}")
    say("Next:")
    say("  - data: put .parquet/.csv files in Data/Current, or write Pipeline scripts (dashboard-work: references/data.md)")
    say("  - cards: npm run new-card -- <name> --page <page> --chart echarts|table|kpi")
    say("  - look:  npm run dev   (or npm run dev:agent for the design agent)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:  # say what went wrong in plain words instead of a traceback
        print(f"setup: stopped: {type(e).__name__}: {e}")
        sys.exit(1)
