#!/usr/bin/env python3
"""Pass Odds snapshot: read one MyFundedPerps account's risk snapshot through the
API and print it as JSON for Pass Odds ("From where you stand").

It only makes two GET requests:
  GET /v1/accounts             list your challenge accounts
  GET /v1/accounts/{id}        one account, with its fresh risk snapshot

Usage
  export MFP_API_KEY=fp_test_...     # sandbox key, or fp_live_... (read scope is enough)
  python3 snapshot.py                # lists your accounts, uses the first active one
  python3 snapshot.py --account ID   # a specific account
  python3 snapshot.py --out my.json  # where to write the snapshot (default snapshot.json)

Your key is read from the environment (or from Colab Secrets as MFP_API_KEY).
It is sent only to the MyFundedPerps host that matches its prefix, and it is never
printed or written to disk. The snapshot holds numbers only: no key, no account id.
Standard library only, Python 3.8+.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HOSTS = {
    "fp_test_": "https://sandbox.myfundedperpetuals.com",
    "fp_live_": "https://developers.myfundedperpetuals.com",
}
ACCOUNT_FIELDS = ("display_name", "stage", "status", "starting_balance", "balance")
RISK_FIELDS = ("equity", "daily_loss_floor", "max_drawdown_floor", "daily_loss_room",
               "max_drawdown_room", "remaining_profit_equity")
REQ_FIELDS = ("daily_loss_pct", "max_drawdown_pct", "profit_target_pct",
              "consistency_pct", "minimum_trading_days")


def fail(msg):
    sys.stderr.write(msg.rstrip() + "\n")
    sys.exit(1)


def get_key():
    key = os.environ.get("MFP_API_KEY", "").strip()
    if not key:
        try:
            from google.colab import userdata  # type: ignore
            key = (userdata.get("MFP_API_KEY") or "").strip()
        except Exception:
            pass
    if not key:
        fail("No key found. Set MFP_API_KEY in your environment, or add it to Colab Secrets.\n"
             "Never paste a key into code, a chat or a URL.")
    return key


def host_for(key):
    base = os.environ.get("MFP_API_BASE", "").strip()
    if base:  # only for local tests: never send a real key to another host
        host = urllib.parse.urlparse(base).hostname or ""
        if host not in ("localhost", "127.0.0.1"):
            fail("MFP_API_BASE may only point to localhost (it exists for tests).")
        return base.rstrip("/")
    for prefix, host in HOSTS.items():
        if key.startswith(prefix):
            return host
    fail("The key should start with fp_test_ (sandbox) or fp_live_ (live).")


def call(base, key, path, tries=3):
    req = urllib.request.Request(base + path, headers={
        "Authorization": "Bearer " + key,
        "Accept": "application/json",
        "User-Agent": "pass-odds-snapshot/1.0",
    })
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < tries - 1:
                wait = e.headers.get("Retry-After")
                time.sleep(min(float(wait) if wait and wait.isdigit() else 2.0 * (attempt + 1), 30))
                continue
            body = e.read().decode("utf-8", "replace")[:300].replace(key, "[key]")
            hint = {
                401: "The key was refused. Check it, and remember: fp_test_ keys only work on the sandbox.",
                403: "This key is not allowed to read accounts (an affiliate key, perhaps).",
                404: "Account not found for this key (wrong id, archived, or another environment).",
            }.get(e.code, "")
            fail(f"HTTP {e.code} on {path}. {hint}\n{body}")
        except urllib.error.URLError as e:
            if attempt < tries - 1:
                time.sleep(2)
                continue
            fail(f"Network error: {e.reason}")
    fail("Too many retries.")


def pick(accounts, wanted):
    if wanted:
        return wanted
    active = [a for a in accounts if a.get("status") == "active"]
    if not active:
        fail("No active account found. Pass one with --account ID.")
    evals = [a for a in active if a.get("stage") == "evaluation"]
    return (evals or active)[0]["id"]


def build(acc):
    risk = acc.get("risk") or {}
    req = risk.get("requirements") or {}
    if risk.get("marks_complete") is False:
        sys.stderr.write("Note: some marks were stale, so equity may be missing. Try again in a few seconds.\n")
    snap = {
        "source": "pass-odds snapshot v1",
        "observed_at": risk.get("observed_at"),
        "account": {k: acc.get(k) for k in ACCOUNT_FIELDS},
        "risk": {k: risk.get(k) for k in RISK_FIELDS},
    }
    snap["risk"]["requirements"] = {k: req.get(k) for k in REQ_FIELDS}
    return snap


def main(argv=None):
    ap = argparse.ArgumentParser(description="Print a MyFundedPerps risk snapshot for Pass Odds.")
    ap.add_argument("--account", help="account id (default: first active evaluation)")
    ap.add_argument("--out", default="snapshot.json", help="file to write (default snapshot.json)")
    args = ap.parse_args(argv)

    key = get_key()
    base = host_for(key)
    listing = call(base, key, "/v1/accounts").get("data") or []
    if not listing:
        fail("This key sees no accounts.")
    sys.stderr.write("Your accounts:\n")
    for a in listing:
        sys.stderr.write(f"  {a.get('id')}  {a.get('display_name') or a.get('name')}  "
                         f"{a.get('stage')}/{a.get('status')}  start ${a.get('starting_balance')}\n")
    acc_id = pick(listing, args.account)
    acc = call(base, key, "/v1/accounts/" + urllib.parse.quote(str(acc_id), safe="")).get("data") or {}
    snap = build(acc)
    if snap["risk"].get("equity") is None:
        fail("The snapshot has no equity yet (marks incomplete). Run it again in a few seconds.")
    text = json.dumps(snap, indent=2)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)
    sys.stderr.write(f"\nSaved to {args.out}. Paste it into Pass Odds, under \"From where you stand\".\n")


if __name__ == "__main__":
    main()
