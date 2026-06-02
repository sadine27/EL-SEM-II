"""Command-line entry point for the EL Python port."""
from __future__ import annotations

import argparse
import json

from el import pipeline
from el.error_handler import error_handler


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m el")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("run", help="run the EL workflow")

    trends_p = subparsers.add_parser(
        "trends", help="preview ranked trends only (no downstream credentials needed)",
    )
    trends_p.add_argument("--top", type=int, default=20, help="number of trends to show")
    trends_p.add_argument("--json", action="store_true", help="emit raw JSON payload")

    args = parser.parse_args(argv)

    if args.command == "run":
        with error_handler():
            pipeline.run()
        return 0
    if args.command == "trends":
        _print_trends(args.top, args.json)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
