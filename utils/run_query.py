"""Run a SQL query from stdin or a file argument. Prints JSON to stdout."""

import sys
import json
from pathlib import Path

# Add repo root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils.db import query

sql = None
if len(sys.argv) > 1:
    # Read SQL from file argument
    sql = Path(sys.argv[1]).read_text().strip()
else:
    # Read SQL from stdin
    sql = sys.stdin.read().strip()

if not sql:
    print("Error: no SQL provided", file=sys.stderr)
    sys.exit(1)

try:
    rows = query(sql)
    print(json.dumps(rows, default=str))
except Exception as e:
    print(json.dumps({"error": str(e)}), file=sys.stderr)
    sys.exit(1)
