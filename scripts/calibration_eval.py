"""Bootstrap evaluation harness for BCC-HIL.

Loads the 30-product Supabase snapshot from the 2026-04-26 EL run, defines a
sigmoid synthetic-truth model over the LLM-agent's raw opportunity_score
(no real HIL feedback exists yet -- this is infrastructure validation,
not a benchmark; see paper section X.B for the explicit caveat), and runs
1000 trials of train/test splits.

For each trial: 15 records become the "training" set (synthetic y is
sampled from Bernoulli(p_approve) and fed to BCCHIL.update); the
remaining 15 are scored with both the raw normalized score and the
calibrated score. The two are compared against the underlying true
probability via Spearman rank correlation, and against the realized
binary outcome via the Brier score.

Outputs (all paths relative to the project root):
  data/eval_results.json
  data/category_posteriors.json     (representative trained posterior)
  paper/figures/calibration_data.tex   (pgfplots reliability-diagram snippet)
  paper/figures/posterior_table.tex    (LaTeX table of per-category counts)
"""

from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path
from statistics import mean, stdev
from typing import List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bayesian_calibration import BCCHIL


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SUPABASE_JSON = PROJECT_ROOT / "Supabase Insert (Scraped) output JSON.json"
DATA_DIR = PROJECT_ROOT / "data"
FIGURES_DIR = PROJECT_ROOT / "paper" / "figures"

NUM_TRIALS = 1000
TRAIN_SIZE = 15
N_BINS = 10
RNG_SEED = 20260426

# Per-category logit bias used by the synthetic-truth model. This represents
# the latent reviewer preference that the LLM-agent's opportunity_score does
# NOT observe -- e.g., the human reviewer dislikes Pumps regardless of how
# strong the trend signal is, and is enthusiastic about Rings. The whole
# point of BCC-HIL is to learn this gap from feedback.
CATEGORY_BIAS = {
    "Pumps": -1.5,
    "Rings": +1.5,
    "Blouses & Shirts": 0.0,
}


def synth_p_approve(raw_score: float, category: str) -> float:
    bias = CATEGORY_BIAS.get(category, 0.0)
    return 1.0 / (1.0 + math.exp(-(0.8 * (raw_score - 8.0) + bias)))


def load_records() -> List[Tuple[str, float]]:
    raw = json.loads(SUPABASE_JSON.read_text(encoding="utf-8"))
    out: List[Tuple[str, float]] = []
    for rec in raw:
        score_str = rec.get("opportunity_score")
        if score_str is None:
            continue
        try:
            score = float(score_str)
        except (TypeError, ValueError):
            continue
        if not (0.0 <= score <= 10.0):
            continue
        category = "uncategorized"
        offers = rec.get("offers") or []
        if offers and isinstance(offers, list) and offers[0].get("categoryName"):
            category = str(offers[0]["categoryName"])
        else:
            payload = rec.get("raw_payload") or {}
            if payload.get("categoryName"):
                category = str(payload["categoryName"])
        out.append((category, score))
    return out


def spearman_rho(xs: List[float], ys: List[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0

    def rank(vs: List[float]) -> List[float]:
        idx = sorted(range(len(vs)), key=lambda i: vs[i])
        ranks = [0.0] * len(vs)
        i = 0
        while i < len(idx):
            j = i
            while j + 1 < len(idx) and vs[idx[j + 1]] == vs[idx[i]]:
                j += 1
            avg_rank = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks[idx[k]] = avg_rank
            i = j + 1
        return ranks

    rx = rank(xs)
    ry = rank(ys)
    mx = mean(rx)
    my = mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def brier_score(preds: List[float], outcomes: List[int]) -> float:
    return mean((p - y) ** 2 for p, y in zip(preds, outcomes))


def reliability_bins(preds: List[float], outcomes: List[int], n_bins: int = N_BINS):
    bins = [{"pred_sum": 0.0, "outcome_sum": 0.0, "count": 0} for _ in range(n_bins)]
    for p, y in zip(preds, outcomes):
        idx = min(int(p * n_bins), n_bins - 1)
        bins[idx]["pred_sum"] += p
        bins[idx]["outcome_sum"] += y
        bins[idx]["count"] += 1
    out = []
    for b in bins:
        if b["count"] == 0:
            out.append({"pred_mean": None, "outcome_mean": None, "count": 0})
        else:
            out.append({
                "pred_mean": b["pred_sum"] / b["count"],
                "outcome_mean": b["outcome_sum"] / b["count"],
                "count": b["count"],
            })
    return out


def percentile(vs: List[float], q: float) -> float:
    if not vs:
        return 0.0
    s = sorted(vs)
    k = (len(s) - 1) * q
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return s[lo]
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def run_evaluation():
    rng = random.Random(RNG_SEED)
    records = load_records()
    if len(records) < TRAIN_SIZE * 2:
        raise RuntimeError(
            f"Need at least {TRAIN_SIZE * 2} records, found {len(records)}"
        )
    print(f"Loaded {len(records)} records "
          f"(categories: {sorted({c for c, _ in records})})")

    spearman_raw, spearman_cal = [], []
    brier_raw, brier_cal = [], []
    pooled_preds_raw, pooled_preds_cal, pooled_outcomes = [], [], []
    representative_posterior = None

    for trial in range(NUM_TRIALS):
        order = list(range(len(records)))
        rng.shuffle(order)
        train_idx = order[:TRAIN_SIZE]
        test_idx = order[TRAIN_SIZE:]

        bcc = BCCHIL()
        for i in train_idx:
            cat, raw = records[i]
            p = synth_p_approve(raw, cat)
            y = 1 if rng.random() < p else 0
            bcc.update(cat, bool(y))

        if trial == 0:
            representative_posterior = bcc

        true_probs = []
        outcomes = []
        preds_raw = []
        preds_cal = []
        for i in test_idx:
            cat, raw = records[i]
            p = synth_p_approve(raw, cat)
            y = 1 if rng.random() < p else 0
            true_probs.append(p)
            outcomes.append(y)
            preds_raw.append(raw / 10.0)
            preds_cal.append(bcc.score(cat, raw))

        spearman_raw.append(spearman_rho(preds_raw, true_probs))
        spearman_cal.append(spearman_rho(preds_cal, true_probs))
        brier_raw.append(brier_score(preds_raw, outcomes))
        brier_cal.append(brier_score(preds_cal, outcomes))
        pooled_preds_raw.extend(preds_raw)
        pooled_preds_cal.extend(preds_cal)
        pooled_outcomes.extend(outcomes)

    summary = {
        "num_trials": NUM_TRIALS,
        "train_size": TRAIN_SIZE,
        "test_size": len(records) - TRAIN_SIZE,
        "rng_seed": RNG_SEED,
        "metrics": {
            "spearman_raw":      _stats(spearman_raw),
            "spearman_calibrated": _stats(spearman_cal),
            "brier_raw":          _stats(brier_raw),
            "brier_calibrated":   _stats(brier_cal),
        },
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    (DATA_DIR / "eval_results.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    if representative_posterior is not None:
        representative_posterior.to_json(DATA_DIR / "category_posteriors.json")
        _write_posterior_table(representative_posterior, FIGURES_DIR / "posterior_table.tex")

    bins_raw = reliability_bins(pooled_preds_raw, pooled_outcomes)
    bins_cal = reliability_bins(pooled_preds_cal, pooled_outcomes)
    _write_calibration_figure(bins_raw, bins_cal, FIGURES_DIR / "calibration_data.tex")

    print()
    print(f"=== BCC-HIL evaluation ({NUM_TRIALS} trials, train={TRAIN_SIZE}, "
          f"test={len(records) - TRAIN_SIZE}) ===")
    print(f"{'metric':<22}{'raw mean':>12}{'cal mean':>12}{'cal CI95':>22}")
    for name in ("spearman", "brier"):
        rs = summary["metrics"][f"{name}_raw"]
        cs = summary["metrics"][f"{name}_calibrated"]
        ci = f"[{cs['ci95_lo']:+.4f}, {cs['ci95_hi']:+.4f}]"
        print(f"{name:<22}{rs['mean']:>+12.4f}{cs['mean']:>+12.4f}{ci:>22}")
    print()
    print("Outputs:")
    print(f"  {DATA_DIR / 'eval_results.json'}")
    print(f"  {DATA_DIR / 'category_posteriors.json'}")
    print(f"  {FIGURES_DIR / 'posterior_table.tex'}")
    print(f"  {FIGURES_DIR / 'calibration_data.tex'}")
    return summary


def _stats(vs: List[float]):
    return {
        "mean": mean(vs),
        "std": stdev(vs) if len(vs) > 1 else 0.0,
        "ci95_lo": percentile(vs, 0.025),
        "ci95_hi": percentile(vs, 0.975),
    }


def _write_posterior_table(bcc: BCCHIL, path: Path) -> None:
    lines = [
        "% Auto-generated by scripts/calibration_eval.py",
        "% Per-category posterior after one representative training fold (15 records).",
        "\\begin{tabular}{lrrrr}",
        "\\toprule",
        "Category & $\\alpha_c$ & $\\beta_c$ & $\\hat{\\mu}_c$ & $w_c$ \\\\",
        "\\midrule",
    ]
    for cat in sorted(bcc.categories()):
        a, b = bcc._get(cat)
        mu = bcc.posterior_mean(cat)
        w = bcc.shrinkage_weight(cat)
        safe_cat = cat.replace("&", "\\&")
        lines.append(f"{safe_cat} & {a:.1f} & {b:.1f} & {mu:.3f} & {w:.3f} \\\\")
    lines.extend(["\\bottomrule", "\\end{tabular}", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_calibration_figure(bins_raw, bins_cal, path: Path) -> None:
    def coords(bins):
        pts = []
        for b in bins:
            if b["count"] > 0:
                pts.append(f"({b['pred_mean']:.4f},{b['outcome_mean']:.4f})")
        return " ".join(pts)

    lines = [
        "% Auto-generated by scripts/calibration_eval.py",
        "% pgfplots reliability diagram. Pooled predictions across all bootstrap trials.",
        "\\begin{tikzpicture}",
        "\\begin{axis}[",
        "  width=0.95\\columnwidth, height=0.7\\columnwidth,",
        "  xlabel={Mean predicted approval probability},",
        "  ylabel={Empirical approval rate},",
        "  xmin=0, xmax=1, ymin=0, ymax=1,",
        "  legend pos=north west,",
        "  legend style={font=\\scriptsize},",
        "  grid=both, grid style={very thin,gray!25},",
        "  tick label style={font=\\scriptsize},",
        "  label style={font=\\scriptsize},",
        "]",
        "\\addplot[domain=0:1, samples=2, dashed, gray] {x};",
        "\\addlegendentry{Perfect calibration}",
        f"\\addplot[mark=*,  blue, thick]  coordinates {{ {coords(bins_raw)} }};",
        "\\addlegendentry{Raw $s/10$}",
        f"\\addplot[mark=square*, red, thick] coordinates {{ {coords(bins_cal)} }};",
        "\\addlegendentry{BCC-HIL calibrated}",
        "\\end{axis}",
        "\\end{tikzpicture}",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    run_evaluation()
