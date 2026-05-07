"""Apply Phase I (BCC-HIL n8n integration) edits to EL.json.

Adds three nodes:
  * "Read BCC Posteriors"      (Postgres, sibling of "Every 24 Hours")
  * "BCC Calibrate Selection"  (Code,     between Phase 4 Selection and HIL insert)
  * "Update BCC Posterior"     (Postgres, sibling of "Answer HIL Callback")

Idempotent: re-running detects existing nodes by name and skips them.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EL_PATH = REPO / "EL.json"

PG_CRED = {"id": "Tx3i0fewZ8MM6LFt", "name": "Supabase yatralounge (Dropship Memory)"}

READ_NODE = {
    "parameters": {
        "operation": "executeQuery",
        "query": "SELECT category, alpha::float8 AS alpha, beta::float8 AS beta FROM private.bcc_posteriors;",
        "options": {},
    },
    "type": "n8n-nodes-base.postgres",
    "typeVersion": 2.5,
    "position": [-1344, -160],
    "id": "bcc-read-0001",
    "name": "Read BCC Posteriors",
    "credentials": {"postgres": PG_CRED},
    "onError": "continueErrorOutput",
}

CAL_JS = r"""
// BCC-HIL: blend Phase 4 raw score with per-category Beta posterior.
//   cal = w * mu + (1 - w) * (raw/100)   where  w = n / (n + N0),  n = a + b - 2.
// Cold-start (a = b = 1) gives n = 0 -> w = 0 -> cal = raw/100 (identity).
// Reorders selected items by calibrated score and re-stamps queue_rank.
const N0 = 5.0;

const post = {};
for (const it of $('Read BCC Posteriors').all()) {
  const r = (it && it.json) || {};
  if (r.category) post[String(r.category).toLowerCase()] = { a: Number(r.alpha), b: Number(r.beta) };
}

function pickCategory(row, rp) {
  const cands = [
    rp && rp.suggested_categories && rp.suggested_categories[0],
    rp && rp.category,
    rp && rp.phase1_category,
    row.category,
  ];
  for (const c of cands) {
    if (c) return String(c).toLowerCase();
  }
  return 'uncategorized';
}

const items = $input.all();
const out = [];
for (const item of items) {
  const row = (item && item.json) || {};
  let rp = row.raw_payload;
  if (typeof rp === 'string') {
    try { rp = JSON.parse(rp); } catch (e) { rp = {}; }
  }
  rp = rp || {};
  const sel = rp.phase4_selection || {};
  const raw = Number(sel.confidence_score || 0);
  const cat = pickCategory(row, rp);
  const p = post[cat] || { a: 1.0, b: 1.0 };
  const a = p.a, b = p.b;
  const n = Math.max(0, a + b - 2);
  const w = n / (n + N0);
  const mu = a / (a + b);
  const norm = Math.max(0, Math.min(1, raw / 100));
  const cal = w * mu + (1 - w) * norm;
  rp.phase4_selection = Object.assign({}, sel, {
    bcc_category: cat,
    bcc_raw_score: raw,
    bcc_calibrated_score: cal,
    bcc_posterior: { alpha: a, beta: b, mu: mu, w: w, n0: N0 },
  });
  out.push({
    json: Object.assign({}, row, { raw_payload: JSON.stringify(rp), bcc_calibrated_score: cal }),
  });
}

out.sort(function (x, y) {
  return (y.json.bcc_calibrated_score || 0) - (x.json.bcc_calibrated_score || 0);
});

for (let i = 0; i < out.length; i++) {
  let rp = out[i].json.raw_payload;
  try { rp = JSON.parse(rp); } catch (e) { rp = {}; }
  rp.phase4_selection = Object.assign({}, rp.phase4_selection || {}, { queue_rank: i + 1 });
  out[i].json.raw_payload = JSON.stringify(rp);
}

return out;
""".strip()

CAL_NODE = {
    "parameters": {"jsCode": CAL_JS},
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": [2640, 1216],
    "id": "bcc-cal-0001",
    "name": "BCC Calibrate Selection",
    "onError": "continueErrorOutput",
}

UPD_QUERY = """
WITH cat AS (
  SELECT lower(coalesce(raw_payload->>'category','')) AS category,
         approval_status
  FROM private.hil_reviews
  WHERE id = $1::bigint
)
INSERT INTO private.bcc_posteriors (category, alpha, beta, updated_at)
SELECT category,
       1.0 + CASE WHEN approval_status='approved' THEN 1.0 ELSE 0.0 END,
       1.0 + CASE WHEN approval_status='rejected' THEN 1.0 ELSE 0.0 END,
       now()
FROM cat
WHERE category <> '' AND approval_status IN ('approved','rejected')
ON CONFLICT (category) DO UPDATE
SET alpha = bcc_posteriors.alpha + CASE WHEN EXCLUDED.alpha > 1.0 THEN 1.0 ELSE 0.0 END,
    beta  = bcc_posteriors.beta  + CASE WHEN EXCLUDED.beta  > 1.0 THEN 1.0 ELSE 0.0 END,
    updated_at = now()
RETURNING category, alpha::float8 AS alpha, beta::float8 AS beta;
""".strip()

UPD_NODE = {
    "parameters": {
        "operation": "executeQuery",
        "query": UPD_QUERY,
        "options": {
            "queryBatching": "independently",
            "queryReplacement": "={{ $('Apply HIL Callback').item.json.review_id }}",
        },
    },
    "type": "n8n-nodes-base.postgres",
    "typeVersion": 2.5,
    "position": [3696, 1856],
    "id": "bcc-upd-0001",
    "name": "Update BCC Posterior",
    "credentials": {"postgres": PG_CRED},
    "onError": "continueErrorOutput",
}


def add_node_if_missing(nodes: list, node: dict) -> bool:
    if any(n.get("name") == node["name"] for n in nodes):
        print(f"  skip (exists): {node['name']}")
        return False
    nodes.append(node)
    print(f"  added: {node['name']}")
    return True


def ensure_target(conn_list: list, target_name: str) -> None:
    """Ensure a 'main' output list contains a connection to target_name."""
    if any(c.get("node") == target_name for c in conn_list):
        return
    conn_list.append({"node": target_name, "type": "main", "index": 0})


def main() -> None:
    raw = EL_PATH.read_text(encoding="utf-8")
    wf = json.loads(raw)
    print(f"loaded {EL_PATH.name}: {len(wf['nodes'])} nodes")

    nodes = wf["nodes"]
    connections = wf["connections"]

    print("Adding nodes:")
    add_node_if_missing(nodes, READ_NODE)
    add_node_if_missing(nodes, CAL_NODE)
    add_node_if_missing(nodes, UPD_NODE)

    print("Wiring connections:")

    # 1. Every 24 Hours -> Read BCC Posteriors (parallel sibling of YouTube Trending IN)
    every24 = connections.setdefault("Every 24 Hours", {"main": [[]]})
    while len(every24["main"]) < 1:
        every24["main"].append([])
    ensure_target(every24["main"][0], "Read BCC Posteriors")
    print("  Every 24 Hours -> Read BCC Posteriors")

    # 2. Phase 4 Candidate Selection -> BCC Calibrate Selection -> Supabase Insert (HIL Reviews)
    p4 = connections.setdefault("Phase 4 Candidate Selection", {"main": [[]]})
    # Replace any prior "Supabase Insert (HIL Reviews)" target with BCC Calibrate Selection
    p4_main0 = p4["main"][0]
    p4["main"][0] = [c for c in p4_main0 if c.get("node") != "Supabase Insert (HIL Reviews)"]
    ensure_target(p4["main"][0], "BCC Calibrate Selection")
    print("  Phase 4 Candidate Selection -> BCC Calibrate Selection")

    cal_conn = connections.setdefault("BCC Calibrate Selection", {"main": [[]]})
    ensure_target(cal_conn["main"][0], "Supabase Insert (HIL Reviews)")
    print("  BCC Calibrate Selection -> Supabase Insert (HIL Reviews)")

    # 3. Apply HIL Callback -> Update BCC Posterior (sibling of Answer HIL Callback)
    apply_conn = connections.setdefault("Apply HIL Callback", {"main": [[]]})
    ensure_target(apply_conn["main"][0], "Update BCC Posterior")
    print("  Apply HIL Callback -> Update BCC Posterior")

    print(f"writing {EL_PATH.name}: {len(nodes)} nodes")
    EL_PATH.write_text(json.dumps(wf, indent=2), encoding="utf-8")

    # Re-parse to confirm the file is valid JSON.
    json.loads(EL_PATH.read_text(encoding="utf-8"))
    print("OK: EL.json is valid JSON.")


if __name__ == "__main__":
    main()
