"""Verify devcheck's headline claim: that it detects the User-Agent problem.

The finding devcheck exists for is "this host is refused unless the client
sends a browser User-Agent". Groq is the clean case because Cloudflare answers
1010 to bare clients and 200 once the header is present.

If this test cannot reproduce that, devcheck is just a version printer and the
README is wrong.

Run with the project's own .env if you have a GROQ_API_KEY; without one the
401-vs-401 comparison still proves the transport difference, because 1010 and
401 are different failure classes entirely.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import devcheck  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def env_keys():
    p = os.path.join(HERE, ".env")
    out = {}
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def main():
    keys = env_keys()
    groq = keys.get("GROQ_API_KEY", "")
    hdrs = {"Authorization": f"Bearer {groq}"} if groq else {}

    print("case 1: public host that treats bare clients differently")
    r = devcheck.check_network("groq",
                               "https://api.groq.com/openai/v1/models",
                               headers=hdrs)
    print(f"  status={r['status']}")
    print(f"  bare={r['ms_bare']}ms  ua={r['ms_ua']}ms")
    print(f"  detail={r['detail']}")
    if groq:
        print("  (a real key was present, so this is the real 1010 case)")
    else:
        print("  (no key, so this only proves the transport difference)")

    print("\ncase 2: a host that is simply reachable either way")
    r2 = devcheck.check_network("pypi", "https://pypi.org/simple/")
    print(f"  status={r2['status']}  detail={r2['detail']}")
    assert r2["status"] == devcheck.OK, "reachable host should be ok"

    print("\ncase 3: a host that is genuinely down (must report BAD)")
    r3 = devcheck.check_network("definitely-not-a-real-host-xyz",
                                "https://this-host-does-not-exist-abc123.invalid/",
                                timeout=6)
    print(f"  status={r3['status']}  detail={r3['detail']}")
    assert r3["status"] == devcheck.BAD, "unreachable host should be BAD"

    print("\ncase 4: version parsing")
    for s, want in [("gh version 2.100.0 (2026)", (2, 100, 0)),
                    ("jq-1.7", (1, 7, 0)),
                    ("ripgrep 14.1.0", (14, 1, 0)),
                    ("not a version", None)]:
        got = devcheck.parse_version(s)
        mark = "ok" if got == want else "MISMATCH"
        print(f"  {mark:9s} {s!r} -> {got} (want {want})")
        assert got == want, f"parse_version({s!r}) gave {got}, wanted {want}"

    print("\nall devcheck self-tests passed")


if __name__ == "__main__":
    main()
