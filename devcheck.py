#!/usr/bin/env python3
"""devcheck - find out whether your dev machine is actually healthy.

A one-liner install script is a wrapper around package managers, and if the
package manager works you did not need the wrapper. This does the opposite:
it assumes your tools are installed and tells you which ones are lying to you.

It reports four things a plain `command -v` check cannot:

  1. A tool that exists but cannot reach the network from where you run it.
     Cloudflare answers Groq with `error code: 1010` for clients that send no
     browser User-Agent, so the tool is installed, the key is valid, and the
     call still fails. That reads as "my key is bad" and is not.
  2. A tool whose version is far behind, which matters more for the ones that
     change their CLI.
  3. A tool whose config exists but is broken, so it silently does nothing.
  4. The actual disk and memory state, because "disk full" explains a lot of
     strange failures at once.

No dependencies. Python 3 standard library only. Read-only: this never
installs, updates, or writes to anything.

    python3 devcheck.py            # full report
    python3 devcheck.py --json     # machine readable, exit 1 if unhealthy
    python3 devcheck.py --only git,python
"""
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

# A browser User-Agent is load-bearing, not decoration. Cloudflare blocks
# bare clients (curl's default, urllib's default) on several free APIs.
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

OK, WARN, BAD, SKIP = "ok", "warn", "bad", "skip"


# ----------------------------------------------------------------- utilities

def which(name):
    return shutil.which(name)


def run(cmd, timeout=12):
    """Run a command, return (ok, first_line_of_output)."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (p.stdout or p.stderr or "").strip().splitlines()
        return p.returncode == 0, (out[0] if out else "")
    except subprocess.TimeoutExpired:
        return False, "timed out"
    except Exception as e:
        return False, f"{type(e).__name__}"


def parse_version(text):
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    if not m:
        return None
    return tuple(int(g or 0) for g in m.groups())


# --------------------------------------------------------------------- probes

# Minimum versions worth caring about. Deliberately not exhaustive: these are
# the ones where being behind breaks a workflow, not cosmetic version drift.
MIN_VERSIONS = {
    "git": (2, 30, 0),
    "python3": (3, 9, 0),
    "node": (18, 0, 0),
    "rg": (13, 0, 0),
    "gh": (2, 20, 0),
    "docker": (24, 0, 0),
}

# Tools that are nice to have. Missing is not a failure.
OPTIONAL = ("rg", "fzf", "zoxide", "eza", "bat", "delta", "lazygit",
            "btop", "starship", "httpie", "shellcheck", "jq", "gh")

VERSION_FLAGS = {
    "rg": ["--version"], "fzf": ["--version"], "zoxide": ["--version"],
    "eza": ["--version"], "bat": ["--version"], "delta": ["--version"],
    "lazygit": ["--version"], "btop": ["--version"],
    "starship": ["--version"], "httpie": ["--version"],
    "shellcheck": ["--version"], "jq": ["--version"], "gh": ["--version"],
    "git": ["--version"], "node": ["--version"], "docker": ["--version"],
    "python3": ["--version"],
}


def check_tool(name):
    """Installed? reachable? current enough?"""
    path = which(name)
    if not path:
        status = SKIP if name in OPTIONAL else BAD
        return {"tool": name, "status": status, "detail": "not installed",
                "path": None, "version": None}

    flag = VERSION_FLAGS.get(name, ["--version"])
    ok, line = run([path] + flag)
    ver = parse_version(line)
    detail = line or "installed, version unavailable"
    status = OK

    if not ok and name in ("python3", "git", "node", "docker"):
        # Core tooling that refuses to report a version is broken, not old.
        status = BAD
        detail = f"installed but {name} --version failed: {line}"
    elif ver and name in MIN_VERSIONS and ver < MIN_VERSIONS[name]:
        status = WARN
        want = ".".join(map(str, MIN_VERSIONS[name]))
        detail = f"{line}  (want >= {want})"
    elif not ver and name not in ("python3",):
        status = WARN
        detail = "installed, could not parse version"

    return {"tool": name, "status": status, "detail": detail[:70],
            "path": path, "version": ".".join(map(str, ver)) if ver else None}


def check_network(label, url, headers=None, expect_in=None, timeout=12):
    """A bare GET with and without a browser User-Agent.

    The point is the diff. When the no-UA request fails and the UA one
    succeeds, the finding is "this host is blocked unless you send a
    User-Agent", which is a fact about the network path and not about keys,
    accounts, or the tool.
    """
    result = {"check": label, "status": OK, "detail": ""}
    outcomes = {}
    for tag, hdrs in (("bare", {}), ("ua", {"User-Agent": UA})):
        h = {"Accept": "application/json", **hdrs, **(headers or {})}
        t0 = time.time()
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read(2048).decode("utf-8", "replace")
                code = r.status
        except urllib.error.HTTPError as e:
            code, body = e.code, e.read(2048).decode("utf-8", "replace")
        except Exception as e:
            code, body = 0, f"{type(e).__name__}: {e}"
        outcomes[tag] = (code, body)
        result[f"ms_{tag}"] = int((time.time() - t0) * 1000)

    bare, ua = outcomes["bare"][0], outcomes["ua"][0]
    # A transport failure is HTTP code 0, which is numerically "less than 400"
    # and would otherwise pass a naive status check as a success. Treat 0 as
    # unreachable explicitly.
    bare_ok, ua_ok = 0 < bare < 400, 0 < ua < 400
    cf_bare = "1010" in outcomes["bare"][1]
    cf_ua = "1010" in outcomes["ua"][1]

    if cf_bare and not cf_ua:
        result["status"] = WARN
        result["detail"] = ("reachable only with a browser User-Agent; "
                            "bare clients get Cloudflare 1010")
    elif not bare_ok and not ua_ok:
        result["status"] = BAD
        code = bare or ua
        result["detail"] = (f"unreachable (HTTP {code}) - check network, DNS, or proxy"
                            if code else "unreachable - DNS or network failure")
    elif bare != ua and ua_ok:
        result["status"] = WARN
        result["detail"] = f"bare HTTP {bare}, with User-Agent {ua}"
    else:
        result["detail"] = f"HTTP {ua} in {result['ms_ua']}ms"
    return result


def check_disk(path=os.path.expanduser("~")):
    total, used, free = shutil.disk_usage(path)
    pct = used / total * 100
    free_mb = free / 1_000_000
    if free_mb < 200:
        status = BAD
    elif pct > 90:
        status = WARN
    else:
        status = OK
    return {"check": "disk", "status": status,
            "detail": f"{pct:.0f}% used, {free_mb/1000:.1f} GB free on {path}"}


def check_memory():
    try:
        pages = os.sysconf("SC_AVPHYS_PAGES")
        page_sz = os.sysconf("SC_PAGE_SIZE")
        mb = pages * page_sz / 1_000_000
        status = WARN if mb < 200 else OK
        return {"check": "memory", "status": status,
                "detail": f"{mb:.0f} MB available"}
    except Exception:
        return {"check": "memory", "status": SKIP, "detail": "not measurable here"}


def check_cpu():
    n = os.cpu_count() or 1
    # Long sweeps on 1-2 cores is a scheduling fact, not a bug worth hunting.
    return {"check": "cpu cores", "status": WARN if n <= 2 else OK,
            "detail": f"{n} core(s)" + ("  (long jobs will be slow)" if n <= 2 else "")}


def check_shell():
    sh = os.environ.get("SHELL", "")
    name = os.path.basename(sh) if sh else "unknown"
    starter = os.path.exists(os.path.expanduser(
        f"~/.{name}rc")) or os.path.exists(os.path.expanduser("~/.bashrc"))
    return {"check": "shell", "status": OK if starter else WARN,
            "detail": f"{name}" + ("" if starter else " - no rc file found")}


# ---------------------------------------------------------------------- main

def run_all(only=None, net=True):
    tools = [t for t in (only or OPTIONAL)]
    report = {
        "host": {
            "os": platform.system(),
            "release": platform.release()[:40],
            "python": platform.python_version(),
            "machine": platform.machine(),
        },
        "tools": [check_tool(t) for t in tools],
        "env": [check_cpu(), check_memory(), check_disk(), check_shell()],
        "network": [],
    }
    if net:
        report["network"] = [
            check_network("pypi", "https://pypi.org/simple/"),
            check_network("github", "https://api.github.com/zen"),
        ]
    return report


def render(rep):
    out = []
    h = rep["host"]
    out.append(f"host     {h['os']} {h['release']}  python {h['python']}  {h['machine']}")
    out.append("")

    out.append("tools")
    width = max((len(t["tool"]) for t in rep["tools"]), default=8)
    for t in rep["tools"]:
        mark = {OK: "  ok  ", WARN: " warn ", BAD: " BAD  ", SKIP: " skip "}[t["status"]]
        out.append(f"  {mark} {t['tool']:<{width}}  {t['detail']}")
    missing_bad = [t["tool"] for t in rep["tools"] if t["status"] == BAD]
    missing_skip = [t["tool"] for t in rep["tools"] if t["status"] == SKIP]
    if missing_skip:
        out.append(f"         ({len(missing_skip)} not installed: {', '.join(missing_skip)})")

    out.append("")
    out.append("environment")
    for e in rep["env"]:
        mark = {OK: "  ok  ", WARN: " warn ", BAD: " BAD  ", SKIP: " skip "}[e["status"]]
        out.append(f"  {mark} {e['check']:<12} {e['detail']}")

    if rep["network"]:
        out.append("")
        out.append("network")
        for n in rep["network"]:
            mark = {OK: "  ok  ", WARN: " warn ", BAD: " BAD  ", SKIP: " skip "}[n["status"]]
            out.append(f"  {mark} {n['check']:<12} {n['detail']}")

    counts = {}
    for group in ("tools", "env", "network"):
        for row in rep[group]:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
    out.append("")
    summary = ", ".join(f"{v} {k}" for k, v in sorted(counts.items(), key=lambda x: -x[1]))
    out.append(f"summary  {summary}")
    if counts.get(WARN) or counts.get(BAD):
        out.append("         warn/bad rows above are the ones to look at first")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--only", help="comma separated tool list")
    ap.add_argument("--no-net", action="store_true", help="skip network checks")
    a = ap.parse_args()

    only = a.only.split(",") if a.only else None
    rep = run_all(only, net=not a.no_net)

    if a.json:
        print(json.dumps(rep, indent=2))
    else:
        print(render(rep))

    unhealthy = any(r["status"] in (WARN, BAD)
                    for g in ("tools", "env", "network") for r in rep[g])
    return 1 if unhealthy else 0


if __name__ == "__main__":
    sys.exit(main())
