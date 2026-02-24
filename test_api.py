"""
test_api.py — Register TileVista client and get embed script.
Run this ONCE after starting the server.
"""
import requests
import json

BASE = "http://localhost:8000"

print("\n🤖 ChatBot SaaS - CrewAI Edition")
print("=" * 50)

# Register client
print("\n[1] Registering TileVista client...")
r = requests.post(f"{BASE}/api/clients", json={
    "name":         "TileVista",
    "website_url":  "http://localhost:3000",
    "ai_provider":  "groq",
    "plan":         "growth",
    "bot_name":     "TileBot",
    "bot_greeting": "Hi! I'm TileBot. I can help you find the perfect tiles for your home!",
    "bot_color":    "#ff3f6c",
})

if r.status_code != 200:
    print(f"❌ Failed: {r.text}")
    exit(1)

data = r.json()
CLIENT_ID = data["id"]
API_KEY   = data["api_key"]

print(f"✅ Client created!")
print(f"   Name      : {data['name']}")
print(f"   Client ID : {CLIENT_ID}")
print(f"   API Key   : {API_KEY}")
print(f"   Status    : {data['crawl_status']}")

print(f"\n[2] Testing chat endpoint...")
r2 = requests.post(
    f"{BASE}/api/chat/{CLIENT_ID}",
    headers={"X-API-Key": API_KEY},
    json={"message": "What tiles do you have for a living room?", "user_id": "test_user"}
)

if r2.status_code == 200:
    d2 = r2.json()
    print(f"✅ Chat working!")
    print(f"   Agent used : {d2.get('agent_used', 'N/A')}")
    print(f"   Intent     : {d2.get('intent', 'N/A')}")
    print(f"   Response   : {d2['response'][:120]}...")
else:
    print(f"⚠️  Chat test failed: {r2.text}")

print(f"""
{'='*50}
✅ SETUP COMPLETE!

Paste this in your HTML pages (replace existing script tag):

<script
  src="http://localhost:8000/widget/chatbot.js"
  data-client-id="{CLIENT_ID}"
  data-api-key="{API_KEY}"
  defer>
</script>

Or open: http://localhost:3000/test_page.html
(Update YOUR_CLIENT_ID and YOUR_API_KEY in that file)
{'='*50}
""")
