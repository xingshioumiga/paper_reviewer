"""使用 requests 直连 Ollama ``/api/chat`` 的冒烟脚本 / smoke test for Ollama ``/api/chat`` via requests."""

import requests
import json
import time

url = "http://localhost:11434/api/chat"

payload = {
    "model": "qwen3.5:9b",
    "messages": [{"role": "user", "content": "hi"}],
    "stream": False,
    "options": {
        "temperature": 0.5,
        "think": False
    }
}

print("Sending request to Ollama /api/chat...")
print(f"Payload: {json.dumps(payload, indent=2)}")
print()

start = time.time()

try:
    response = requests.post(url, json=payload, timeout=300)
    elapsed = time.time() - start

    print(f"Status: {response.status_code}")
    print(f"Time: {elapsed:.1f}s")
    print()

    if response.status_code == 200:
        data = response.json()
        content = data.get("message", {}).get("content", "")
        print(f"Response content: {content[:200]}")
    else:
        print(f"Error: {response.text}")

except Exception as e:
    elapsed = time.time() - start
    print(f"Failed after {elapsed:.1f}s: {e}")
