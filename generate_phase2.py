import urllib.request
import json
import os

prompt = """
You are an expert Python/Flask engineer. Implement Phase 2 of Chore Gremlin V2.0.0 in the current directory (~/dev-projects/chores-app).
Requirements:
1. Update/Create db.py to configure SQLAlchemy with SQLite, enabling WAL mode via engine events (PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;), and strict connection pooling for local use.
2. Ensure database path defaults safely to instance/choregremlin.db.
3. Create a smoke test or database initialization script to verify that WAL mode activates successfully on connection.

Provide the exact Python code or terminal commands needed. Output clean code.
"""

req_data = {
    "model": "qwen2.5-coder:3b",
    "prompt": prompt,
    "stream": False
}

req = urllib.request.Request(
    "http://127.0.0.1:11434/api/generate",
    data=json.dumps(req_data).encode('utf-8'),
    headers={'Content-Type': 'application/json'}
)

print("Asking local Ollama (qwen2.5-coder:3b) to generate Phase 2 files... Please wait a moment.")
try:
    with urllib.request.urlopen(req, timeout=600) as response:
        result = json.loads(response.read().decode('utf-8'))
        print("\n--- OLLAMA RESPONSE ---\n")
        print(result.get("response", ""))
except Exception as e:
    print(f"Error communicating with Ollama: {e}")
