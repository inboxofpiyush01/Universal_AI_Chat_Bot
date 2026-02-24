"""
check_rag.py — Universal RAG diagnostic + repair tool
Runs WITHOUT the server. Works for any website.

Usage:
  python check_rag.py              # check status + auto-fix if empty
  python check_rag.py --reindex    # force full re-crawl even if DB has data
"""
import sys, os, asyncio
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

G="\033[92m"; Y="\033[93m"; R="\033[91m"; W="\033[1m"; X="\033[0m"
FORCE = "--reindex" in sys.argv

# ── 1. Load client ────────────────────────────────────────────────────────────
print(f"\n{W}[1] Loading client from database...{X}")
from config.database import AsyncSessionLocal, Client
from sqlalchemy import select

async def get_clients():
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Client).order_by(Client.created_at.desc()))
        return r.scalars().all()

async def save_client_status(cid, pages):
    from datetime import datetime
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Client).where(Client.id == cid))
        c = r.scalar_one_or_none()
        if c:
            c.crawl_status = "done"
            c.total_pages_crawled = pages
            c.last_crawled_at = datetime.utcnow()
            await db.commit()

clients = asyncio.run(get_clients())
if not clients:
    print(f"{R}No clients found. Register a client first with register_client.py{X}")
    sys.exit(1)

# Pick client — if multiple, show list
if len(clients) == 1:
    client = clients[0]
else:
    print(f"\nMultiple clients found:")
    for i, c in enumerate(clients):
        print(f"  [{i}] {c.name} — {c.website_url} ({c.crawl_status})")
    while True:
        raw = input(f"Pick number (0 to {len(clients)-1}): ").strip()
        if raw.isdigit() and 0 <= int(raw) < len(clients):
            client = clients[int(raw)]
            break
        print(f"  Please enter a number between 0 and {len(clients)-1}")

print(f"{G}  Client  : {client.name}{X}")
print(f"{G}  ID      : {client.id}{X}")
print(f"{G}  Website : {client.website_url}{X}")
print(f"{G}  Status  : {client.crawl_status} | Pages crawled: {client.total_pages_crawled}{X}")

# ── 2. Check vector DB ────────────────────────────────────────────────────────
print(f"\n{W}[2] Checking Vector DB...{X}")
from vector_db.chroma_manager import VectorDBManager
vdb = VectorDBManager()

count = 0
try:
    col = vdb._get_collection(client.id)
    count = col.count()
    print(f"  Documents in DB: {W}{count}{X}")
    if count > 0 and not FORCE:
        sample = col.get(limit=5, include=["documents","metadatas"])
        print(f"{G}  Sample stored documents:{X}")
        for doc, meta in zip(sample['documents'], sample['metadatas']):
            print(f"    [{meta.get('page_type','?')}] {meta.get('title','?')[:45]}")
            print(f"    price={meta.get('price','')}  image={'YES' if meta.get('image_url') else 'NO'}")
            print(f"    {doc[:80]}...")
            print()
except Exception as e:
    print(f"{R}  DB error: {e}{X}")
    count = 0

# ── 3. Test search ────────────────────────────────────────────────────────────
if count > 0 and not FORCE:
    print(f"\n{W}[3] Testing search...{X}")
    # Use first word of client name as test query
    test_q = client.name.split()[0].lower()
    results = vdb.search(client.id, test_q, n_results=3)
    if results:
        print(f"{G}  Search working! Top results:{X}")
        for r in results:
            print(f"    ✓ {r['title'][:50]} (score:{r['relevance_score']})")
        print(f"\n{G}  RAG IS WORKING.{X}")
        print(f"  If bot still gives wrong answers, do: python check_rag.py --reindex")
        sys.exit(0)
    else:
        print(f"{Y}  Search returns empty. Re-crawling...{X}")
        count = 0

# ── 4. Crawl website ─────────────────────────────────────────────────────────
print(f"\n{W}[4] Crawling {client.website_url} ...{X}")
print(f"  (Make sure your website server is running)\n")

import requests
from crawler.scraper import WebScraper

# Test connectivity
try:
    r = requests.get(client.website_url, timeout=8)
    if r.status_code != 200:
        raise Exception(f"HTTP {r.status_code}")
    print(f"{G}  Website reachable ✓{X}")
except Exception as e:
    print(f"{R}  Cannot reach {client.website_url}: {e}{X}")
    print(f"""
  Make sure your website is running. For example:
    cd test_website\\e-commerce_fashion
    python -m http.server 3001
  
  Then run this script again.
    """)
    sys.exit(1)

# Run the scraper
scraper = WebScraper(client.website_url, max_pages=50)
pages = scraper.crawl()

if not pages:
    print(f"{R}  Crawl returned 0 pages!{X}")
    sys.exit(1)

total_products = sum(len(p.get("products", [])) for p in pages)
print(f"\n{G}  Crawled {len(pages)} pages, found {total_products} products{X}")

for p in pages:
    prods = p.get("products", [])
    print(f"  [{p.get('page_type','?')}] {p.get('title','')[:45]} — {len(prods)} products")
    for prod in prods[:3]:
        print(f"      ✓ {prod['name']} | {prod['price']} | img={'YES' if prod.get('image') else 'NO'}")
    if len(prods) > 3:
        print(f"      ... and {len(prods)-3} more")

# ── 5. Store in DB ────────────────────────────────────────────────────────────
print(f"\n{W}[5] Storing in Vector DB...{X}")

# Clear old data
try:
    col = vdb._get_collection(client.id)
    old_ids = col.get()['ids']
    if old_ids:
        col.delete(ids=old_ids)
        print(f"  Cleared {len(old_ids)} old documents")
except Exception as e:
    print(f"{Y}  Could not clear old data: {e}{X}")

# Store new data
vdb.add_pages(client.id, pages)
new_count = vdb._get_collection(client.id).count()
print(f"{G}  Stored {new_count} documents ✓{X}")

asyncio.run(save_client_status(client.id, len(pages)))

# ── 6. Verify search ─────────────────────────────────────────────────────────
print(f"\n{W}[6] Verifying search...{X}")
# Test with actual product names from crawl
all_products = [p for page in pages for p in page.get("products", [])]
test_names = [p["name"] for p in all_products[:4]]

for name in test_names:
    results = vdb.search(client.id, name, n_results=1)
    if results:
        r = results[0]
        print(f"{G}  ✓ '{name[:35]}' → score:{r['relevance_score']} price:{r.get('price','')} img:{'YES' if r.get('image_url') else 'NO'}{X}")
    else:
        print(f"{R}  ✗ '{name}' → NOT FOUND in DB!{X}")

# ── 7. Done ───────────────────────────────────────────────────────────────────
print(f"""
{W}{'='*60}{X}
{G}  DONE! {new_count} documents indexed for {client.name}{X}

  Next steps:
  1. {W}Restart the API server:{X}
       uvicorn api.main:app --reload

  2. {W}Refresh your browser{X} (Ctrl+Shift+R)

  3. {W}Test the chatbot{X} — ask about any product on your site

  Client ID : {client.id}
  API Key   : {client.api_key}
{W}{'='*60}{X}
""")
