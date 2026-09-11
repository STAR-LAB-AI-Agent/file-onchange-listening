import os
import sys
from pathlib import Path

out = Path(os.environ.get("FILEWATCH_AGENT_OUT", "agent-out.txt"))
text = sys.stdin.read()
if not text:
    text = os.environ.get("FILEWATCH_PROMPT", "")
out.write_text(text, encoding="utf-8")
print(f"wrote {out}")
