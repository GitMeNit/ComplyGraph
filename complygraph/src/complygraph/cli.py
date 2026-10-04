"""CLI:  python -m complygraph.cli {ask,scan,approvals,approve,audit,demo}"""
from __future__ import annotations

import argparse
import json
import sys

from .config import Settings
from .copilot import Copilot
from .scanner import engine
from .scanner.report import to_markdown, to_sarif


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="complygraph")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ask"); a.add_argument("request"); a.add_argument("--user", default="cli"); a.add_argument("--path")
    sc = sub.add_parser("scan"); sc.add_argument("path"); sc.add_argument("--format", choices=["md", "json", "sarif"], default="md")
    sc.add_argument("--fail-on", choices=["low", "medium", "high", "critical"], help="exit 1 if tier >= level (CI gate)")
    sc.add_argument("--regulation", action="append")
    sub.add_parser("approvals")
    ap2 = sub.add_parser("approve"); ap2.add_argument("id"); ap2.add_argument("--as", dest="who", required=True)
    ap2.add_argument("--reject", action="store_true"); ap2.add_argument("--comment", default="")
    sub.add_parser("audit")
    sub.add_parser("demo")
    args = ap.parse_args(argv)
    s = Settings.load()

    if args.cmd == "scan":
        res = engine.scan_path(args.path, s.rules_path, args.regulation)
        print({"md": lambda: to_markdown(res), "json": lambda: json.dumps(res.to_dict(), indent=2),
               "sarif": lambda: json.dumps(to_sarif(res), indent=2)}[args.format]())
        order = ["low", "medium", "high", "critical"]
        return 1 if args.fail_on and order.index(res.tier) >= order.index(args.fail_on) else 0

    c = Copilot(s)
    if args.cmd == "ask":
        r = c.ask(args.request, args.user, args.path)
        print(r["answer"]); print("\n--- trace ---", *r["trace"], sep="\n")
    elif args.cmd == "approvals":
        print(json.dumps([{k: x[k] for k in ("id", "requester", "tier", "reason")} for x in c.approvals.pending()], indent=2))
    elif args.cmd == "approve":
        print(json.dumps(c.resume(args.id, args.who, not args.reject, args.comment), indent=2)[:2000])
    elif args.cmd == "audit":
        print(json.dumps(c.audit.verify(), indent=2))
    elif args.cmd == "demo":
        for q, path in [("What are the incident reporting duties if our payments platform has an outage?", None),
                        ("Run a regulatory gap assessment of this service", "examples/credit_scoring_service")]:
            r = c.ask(q, "alice", path)
            print(f"\n=== {q}\nstatus={r['status']}  tier={r['risk']['tier'] if r['risk'] else '-'}")
            print(*r["trace"], sep="\n  ")
            if r["approval_id"]:
                print(f"\n>> held. Approve as a different user:  python -m complygraph.cli approve {r['approval_id']} --as bob")
        print("\naudit chain:", c.audit.verify())
    return 0


if __name__ == "__main__":
    sys.exit(main())
