import os
import sys
from dotenv import load_dotenv

load_dotenv()

results = {"Neo4j": "PENDING", "Gemini": "PENDING", "OpenRouter": "PENDING"}

# 1. Test Neo4j
print("Testing Neo4j...")
try:
    from neo4j import GraphDatabase
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USERNAME")
    pwd = os.getenv("NEO4J_PASSWORD")
    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    driver.verify_connectivity()
    results["Neo4j"] = "OK"
    driver.close()
except Exception as e:
    results["Neo4j"] = f"FAIL ({type(e).__name__}): {e}"

# 2. Test Gemini
print("Testing Gemini...")
try:
    from google import genai
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        client = genai.Client(api_key=gemini_key)
        resp = client.models.generate_content(
            model='gemini-2.5-flash',
            contents='Say hi'
        )
        if resp.text:
            results["Gemini"] = "OK"
        else:
            results["Gemini"] = "FAIL: No response text"
    else:
        results["Gemini"] = "FAIL: Missing API key"
except Exception as e:
    results["Gemini"] = f"FAIL ({type(e).__name__}): {e}"

# 3. Test OpenRouter
print("Testing OpenRouter...")
try:
    import requests
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if openrouter_key:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {openrouter_key}"},
            json={
                "model": "google/gemini-2.5-pro",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 10
            }
        )
        if resp.status_code == 200:
            results["OpenRouter"] = "OK"
        else:
            results["OpenRouter"] = f"FAIL (HTTP {resp.status_code}): {resp.text[:100]}"
    else:
        results["OpenRouter"] = "FAIL: Missing API key"
except Exception as e:
    results["OpenRouter"] = f"FAIL ({type(e).__name__}): {e}"

print("="*40)
print("API KEYS TEST RESULTS")
print("="*40)
for k, v in results.items():
    print(f"{k}: {v}")
