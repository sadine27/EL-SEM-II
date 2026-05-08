"""Convert multi-line GOOGLE_SERVICE_ACCOUNT_JSON in .env.example to one-line escaped form."""
import json
import re
from pathlib import Path

path = Path(".env.example")
text = path.read_text(encoding="utf-8")

m = re.search(r'^GOOGLE_SERVICE_ACCOUNT_JSON="(\{[\s\S]*?\n\})"', text, re.MULTILINE)
if not m:
    raise SystemExit("GOOGLE_SERVICE_ACCOUNT_JSON block not found")

data = json.loads(m.group(1))
one_line = json.dumps(data, separators=(",", ":"))
# Backslashes first, then quotes
escaped = one_line.replace("\\", "\\\\").replace('"', '\\"')

new_line = f'GOOGLE_SERVICE_ACCOUNT_JSON="{escaped}"'
new_text = text[:m.start()] + new_line + text[m.end():]
path.write_text(new_text, encoding="utf-8")
print(f"OK — rewrote SA JSON ({len(escaped)} chars escaped)")
