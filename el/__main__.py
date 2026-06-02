"""Command-line entry point for the EL Python port."""
from __future__ import annotations

import argparse
import json
import sys

from el import pipeline
from el.error_handler import error_handler


def _prefer_utf8_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass


def _print_trends(top: int, as_json: bool) -> None:
    payload = pipeline.collect_and_rank()
    trends = payload.get("trends", [])[:top]
    if as_json:
        print(json.dumps({"metadata": payload.get("metadata", {}), "trends": trends},
                         indent=2, ensure_ascii=False))
        return

    meta = payload.get("metadata", {})
    ai = meta.get("ai_scored_count")
    mode = f"AI-scored ({ai} topics)" if ai else "keyword-scored (no Vertex creds / AI off)"
    print(f"\nFenix trends — {meta.get('total_topics', len(trends))} topics, {mode}")
    print(f"sources: {', '.join(meta.get('sources', [])) or 'none'}\n")
    print(f"{'#':>3}  {'intent':>6}  {'vel':>5}  {'src':>3}  category / topic")
    print("-" * 72)
    for t in trends:
        vel = t.get("velocity")
        vel_s = f"{vel:+.2f}" if isinstance(vel, (int, float)) else "  -  "
        cats = ",".join(t.get("suggested_categories", []))
        print(f"{t.get('rank', '?'):>3}  {t.get('product_intent_score', 0):>6.2f}  "
              f"{vel_s:>5}  {t.get('cross_source_count', 1):>3}  [{cats}] {t.get('topic', '')}")
    print()


def _print_forge(query: str | None, from_fenix: bool, top: int, as_json: bool) -> None:
    payload = pipeline.preview_forge(query=query, from_fenix=from_fenix, top=top)
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    matches = payload.get("supplier_matches", [])
    print(f"\nForge supplier matches - {len(matches)} trend(s)\n")
    for item in matches:
        print(f"{item.get('query', '')}")
        rows = item.get("matches", [])
        if not rows:
            print("  no supplier matches")
            continue
        for idx, match in enumerate(rows, start=1):
            landed = match.get("landed_cost")
            landed_s = f"{landed:.2f} {match.get('currency') or ''}" if isinstance(landed, (int, float)) else "n/a"
            print(
                f"  {idx}. [{match.get('source_id')}] {match.get('title')} "
                f"- landed {landed_s}, stock {match.get('stock')}, "
                f"ship {match.get('shipping_days_min') or '?'}-{match.get('shipping_days_max') or '?'}d"
            )
    print()


def main(argv: list[str] | None = None) -> int:
    _prefer_utf8_stdout()
    parser = argparse.ArgumentParser(prog="python -m el")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("run", help="run the EL workflow")

    trends_p = subparsers.add_parser(
        "trends", help="preview ranked trends only (no downstream credentials needed)",
    )
    trends_p.add_argument("--top", type=int, default=20, help="number of trends to show")
    trends_p.add_argument("--json", action="store_true", help="emit raw JSON payload")

    forge_p = subparsers.add_parser(
        "forge", help="preview supplier matches only (no downstream uploads)",
    )
    forge_group = forge_p.add_mutually_exclusive_group(required=True)
    forge_group.add_argument("--query", help="single product query to source")
    forge_group.add_argument(
        "--from-fenix",
        action="store_true",
        help="source top ranked trends from the Fenix preview",
    )
    forge_p.add_argument("--top", type=int, default=10, help="query match or Fenix trend limit")
    forge_p.add_argument("--json", action="store_true", help="emit raw JSON payload")

    args = parser.parse_args(argv)

    if args.command == "run":
        with error_handler():
            pipeline.run()
        return 0
    if args.command == "trends":
        _print_trends(args.top, args.json)
        return 0
    if args.command == "forge":
        _print_forge(args.query, args.from_fenix, args.top, args.json)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
