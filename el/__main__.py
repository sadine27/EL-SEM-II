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


def _color(code: int, text: str) -> str:
    """Wrap *text* in ANSI escape code *code*; no-op when stdout is not a tty."""
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def _green(text: str) -> str:   return _color(32, text)
def _yellow(text: str) -> str:  return _color(33, text)
def _cyan(text: str) -> str:    return _color(36, text)
def _bold(text: str) -> str:    return _color(1, text)


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
    title = _bold(f"Fenix trends — {meta.get('total_topics', len(trends))} topics")
    print(f"\n{title}, {_cyan(mode)}")
    srcs = meta.get("sources", [])
    print(f"{_yellow('sources')}: {', '.join(srcs) or 'none'}\n")
    table_header = f"{'#':>3}  {'intent':>6}  {'vel':>5}  {'src':>3}  category / topic"
    print(_green(table_header))
    print(_green("-" * 72))
    for t in trends:
        vel = t.get("velocity")
        vel_s = f"{vel:+.2f}" if isinstance(vel, (int, float)) else "  -  "
        cats = ",".join(t.get("suggested_categories", []))
        score = t.get("product_intent_score", 0)
        # Colour-code intent score: high → green, mid → yellow, low → red
        score_col = _green(f"{score:>6.2f}") if score >= 0.6 else (
            _yellow(f"{score:>6.2f}") if score >= 0.3 else _color(31, f"{score:>6.2f}")
        )
        print(f"{t.get('rank', '?'):>3}  {score_col}  "
              f"{vel_s:>5}  {t.get('cross_source_count', 1):>3}  [{_cyan(cats)}] {t.get('topic', '')}")
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


def _print_sentinel(query: str | None, from_fenix: bool, top: int, as_json: bool) -> None:
    payload = pipeline.preview_sentinel(query=query, from_fenix=from_fenix, top=top)
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    groups = payload.get("sentinel_matches", [])
    print(f"\nSentinel vetted matches - {len(groups)} trend(s)\n")
    for item in groups:
        summary = item.get("summary", {})
        print(
            f"{item.get('query', '')}  "
            f"({summary.get('passed', 0)} pass / {summary.get('rejected', 0)} reject "
            f"of {summary.get('evaluated', 0)})"
        )
        rows = item.get("matches", [])
        if not rows:
            print("  no passing supplier matches")
        for idx, match in enumerate(rows, start=1):
            score = match.get("sentinel_score")
            score_s = f"{score:.2f}" if isinstance(score, (int, float)) else "n/a"
            margin = match.get("projected_margin_pct")
            margin_s = f"{margin * 100:.0f}%" if isinstance(margin, (int, float)) else "n/a"
            sell = match.get("projected_sell_price")
            sell_s = f"{sell:.2f} {match.get('currency') or ''}".strip() if isinstance(sell, (int, float)) else "n/a"
            warn = match.get("sentinel_warnings") or []
            warn_s = f"  ⚠ {', '.join(warn)}" if warn else ""
            print(
                f"  {idx}. [{match.get('source_id')}] {match.get('title')} "
                f"- score {score_s}, margin {margin_s}, sell {sell_s}{warn_s}"
            )
        for match in item.get("rejected", []):
            reasons = ", ".join(match.get("sentinel_rejection_reasons") or [])
            print(f"  ✗ [{match.get('source_id')}] {match.get('title')} - {reasons}")
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

    sentinel_p = subparsers.add_parser(
        "sentinel", help="preview Forge matches passed through the Sentinel vetting gate",
    )
    sentinel_group = sentinel_p.add_mutually_exclusive_group(required=True)
    sentinel_group.add_argument("--query", help="single product query to source and vet")
    sentinel_group.add_argument(
        "--from-fenix",
        action="store_true",
        help="vet supplier matches for the top ranked Fenix trends",
    )
    sentinel_p.add_argument("--top", type=int, default=10, help="query match or Fenix trend limit")
    sentinel_p.add_argument("--json", action="store_true", help="emit raw JSON payload")

    args = parser.parse_args(argv)

    if args.command == "run":
        with error_handler():
            pipeline.run({})
        return 0
    if args.command == "trends":
        _print_trends(args.top, args.json)
        return 0
    if args.command == "forge":
        _print_forge(args.query, args.from_fenix, args.top, args.json)
        return 0
    if args.command == "sentinel":
        _print_sentinel(args.query, args.from_fenix, args.top, args.json)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
