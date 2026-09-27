# devcheck

Find out whether your dev machine is actually healthy — or just whether the
tools are installed.

```bash
git clone https://github.com/ARYX/devcheck
cd devcheck
python3 devcheck.py
```

```
host     Linux 6.6.153+  python 3.12.3  x86_64

tools
   skip  rg          not installed
    ok   jq          jq-1.7
    ok   gh          gh version 2.100.0 (2026-09-03)
         (11 not installed: rg, fzf, zoxide, eza, bat, delta, lazygit, btop, ...)

environment
   warn  cpu cores    2 core(s)  (long jobs will be slow)
    ok   memory       3188 MB available
    ok   disk         81% used, 0.7 GB free on /home/user
    ok   shell        bash

network
    ok   pypi         HTTP 200 in 13ms
    ok   github       HTTP 200 in 20ms

summary  11 skip, 7 ok, 1 warn
```

No dependencies, no install, read-only. Python 3 standard library.

## Why not just a list of install commands

Those already exist, and they are worse than useless when something is
actually broken. `curl ... | bash` assumes the package manager works, and it
tells you nothing about the four failure modes below. This checks instead of
installs, because the interesting problems are the ones where a tool exists
and lies to you.

## What it catches

**1. Installed, but refused by the network path**

The one that costs hours. Cloudflare answers Groq's API with
`error code: 1010` to any client that does not send a browser `User-Agent` —
which includes `urllib`, `curl`'s default, and most bare scripts. The tool is
installed. The key is valid. The call still fails, and the error says nothing
about keys, so it reads as "my credentials are wrong."

devcheck sends the same request twice, once bare and once with a browser
User-Agent, and reports the difference as a property of the network path
rather than of your account:

```
   warn  groq         reachable only with a browser User-Agent; bare clients get Cloudflare 1010
```

This is reproducible on any network where Cloudflare fronts the API, and it
is invisible to `command -v`.

**2. Too old for the job**

`git`, `python3`, `node`, `docker`, `rg`, and `gh` have version floors that
actually break workflows. Version drift elsewhere is cosmetic, so this does
not warn about it.

**3. Disk and memory, before they explain something else**

"Disk full" accounts for a surprising share of strange failures at once:
impossible pip installs, git refusing to write objects, tests failing on
writes. devcheck reports real free space, not a percentage.

**4. CPU count**

Two cores is a scheduling fact, not a bug, and it is the difference between a
6-minute backtest and a 40-minute one.

## Usage

```bash
python3 devcheck.py                    # full report, exit 1 if unhealthy
python3 devcheck.py --json             # machine readable
python3 devcheck.py --only git,python3 # specific tools
python3 devcheck.py --no-net           # skip network checks
python3 test_devcheck.py               # self-tests
```

Exit codes: `0` clean, `1` something is warn or bad. Safe to put in CI.

## Extending it

`check_tool` and `check_network` are the two functions worth reusing.
`MIN_VERSIONS` and `OPTIONAL` are plain dicts at the top of the file. A new
probe is a function returning a dict with `check`/`status`/`detail`.

Status values: `ok`, `warn`, `bad`, `skip`. A missing optional tool is `skip`,
never `bad` — a missing core tool is `bad`.

## Notes

Read-only. It never installs, updates, or writes to anything outside your own
home. The network probes hit two public endpoints (`pypi.org`, `api.github.com`)
and nothing else.
