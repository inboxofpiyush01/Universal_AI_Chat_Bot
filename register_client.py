#!/usr/bin/env python3
"""
register_client.py — Universal ChatBot SaaS Client Registration Tool
=====================================================================
Run this script to register ANY new client website.
Each run creates a brand new unique Client ID + API Key.

Usage:
  python register_client.py                  # Interactive mode (prompts for input)
  python register_client.py --list           # List all registered clients
  python register_client.py --stats <id>     # Show stats for a specific client
  python register_client.py --sync  <id>     # Trigger a re-crawl for a client
  python register_client.py --delete <id>    # Delete a client (if supported)
"""

import sys
import json
import argparse
import requests
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL   = "http://localhost:8000"
PLANS      = ["starter", "growth", "pro"]
PROVIDERS  = ["groq", "claude", "openai"]
SEPARATOR  = "=" * 60

# ── Helpers ───────────────────────────────────────────────────────────────────

def header():
    print(f"\n{'='*60}")
    print("  🤖  ChatBot SaaS — CrewAI Edition")
    print("  Universal Client Registration Tool")
    print(f"{'='*60}\n")

def ask(prompt, default=None, options=None):
    """Interactive prompt with optional default and option validation."""
    if default:
        display = f"{prompt} [{default}]: "
    elif options:
        display = f"{prompt} ({'/'.join(options)}): "
    else:
        display = f"{prompt}: "

    while True:
        val = input(display).strip()
        if not val and default is not None:
            return default
        if not val:
            print("  ⚠️  This field is required.")
            continue
        if options and val not in options:
            print(f"  ⚠️  Choose one of: {', '.join(options)}")
            continue
        return val

def check_server():
    """Make sure the API server is running before anything else."""
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=4)
        if r.status_code == 200:
            return True
    except requests.exceptions.ConnectionError:
        pass
    print(f"❌  Cannot connect to server at {BASE_URL}")
    print("    Make sure the server is running:  uvicorn api.main:app --reload")
    sys.exit(1)

def save_client_to_log(data: dict):
    """Append registered client details to a local log file."""
    log_file = "registered_clients.json"
    try:
        with open(log_file, "r") as f:
            existing = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []

    existing.append({
        "registered_at": datetime.now().isoformat(),
        "id":            data["id"],
        "name":          data["name"],
        "website_url":   data["website_url"],
        "api_key":       data["api_key"],
        "bot_name":      data["bot_name"],
        "plan":          data["plan"],
        "ai_provider":   data["ai_provider"],
    })

    with open(log_file, "w") as f:
        json.dump(existing, f, indent=2)

    print(f"  💾  Credentials saved to: {log_file}")


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_register():
    """Interactive registration wizard for a new client."""
    header()
    print("Register a new client website. Press Enter to accept defaults.\n")

    # Collect all inputs
    name         = ask("Business name (e.g. StyleNest, TileVista)")
    website_url  = ask("Website URL (e.g. http://localhost:3001)")
    bot_name     = ask("Bot name", default=f"{name.split()[0]}Bot")
    bot_greeting = ask(
        "Bot greeting",
        default=f"Hi! I'm {bot_name}, your AI assistant. How can I help you today?"
    )
    bot_color    = ask("Brand color (hex)", default="#ff3f6c")
    ai_provider  = ask("AI provider", default="groq", options=PROVIDERS)
    plan         = ask("Plan", default="growth", options=PLANS)

    print(f"\n{SEPARATOR}")
    print("  Review your details:")
    print(f"  Business   : {name}")
    print(f"  Website    : {website_url}")
    print(f"  Bot Name   : {bot_name}")
    print(f"  Greeting   : {bot_greeting}")
    print(f"  Color      : {bot_color}")
    print(f"  Provider   : {ai_provider}")
    print(f"  Plan       : {plan}")
    print(SEPARATOR)

    confirm = input("\nCreate this client? (yes/no) [yes]: ").strip().lower()
    if confirm not in ("", "yes", "y"):
        print("\n❌  Cancelled.")
        return

    # Register
    print("\n⏳  Registering client and starting website crawl...")
    try:
        r = requests.post(f"{BASE_URL}/api/clients", json={
            "name":         name,
            "website_url":  website_url,
            "ai_provider":  ai_provider,
            "plan":         plan,
            "bot_name":     bot_name,
            "bot_greeting": bot_greeting,
            "bot_color":    bot_color,
        }, timeout=30)
    except requests.exceptions.Timeout:
        print("❌  Request timed out. Server may be busy — try again.")
        return
    except requests.exceptions.ConnectionError:
        print("❌  Connection lost. Is the server still running?")
        return

    if r.status_code != 200:
        print(f"❌  Registration failed (HTTP {r.status_code}):")
        print(f"    {r.text}")
        return

    data = r.json()
    CLIENT_ID = data["id"]
    API_KEY   = data["api_key"]

    # Test chat
    print("⏳  Testing chat endpoint...")
    try:
        r2 = requests.post(
            f"{BASE_URL}/api/chat/{CLIENT_ID}",
            headers={"X-API-Key": API_KEY},
            json={"message": "What do you offer?", "user_id": "register_test"},
            timeout=30
        )
        chat_ok = r2.status_code == 200
        chat_preview = r2.json().get("response", "")[:100] + "..." if chat_ok else r2.text[:80]
    except Exception as e:
        chat_ok = False
        chat_preview = str(e)

    # Save to log
    save_client_to_log(data)

    # Print results
    print(f"\n{'='*60}")
    print("  ✅  CLIENT REGISTERED SUCCESSFULLY!")
    print(f"{'='*60}")
    print(f"  Business   : {data['name']}")
    print(f"  Client ID  : {CLIENT_ID}")
    print(f"  API Key    : {API_KEY}")
    print(f"  Plan       : {data['plan']}")
    print(f"  Provider   : {data['ai_provider']}")
    print(f"  Crawl      : {data['crawl_status']} (running in background)")
    print(f"  Chat Test  : {'✅ OK' if chat_ok else '⚠️  Failed'}")
    if chat_ok:
        print(f"  Preview    : {chat_preview}")

    print(f"\n{'='*60}")
    print("  📋  EMBED SCRIPT — paste this on every page of the website:")
    print(f"{'='*60}")
    print(f"\n{data['embed_script']}\n")
    print(f"{'='*60}")
    print("  💡  Tips:")
    print("  • Paste the script tag just before </body> on every page")
    print("  • The bot will auto-appear as a floating button")
    print(f"  • Crawl runs in background — full answers ready in ~30 seconds")
    print(f"  • Run  python register_client.py --stats {CLIENT_ID}  to check crawl")
    print(f"{'='*60}\n")


def cmd_list():
    """List all registered clients from local log."""
    try:
        with open("registered_clients.json") as f:
            clients = json.load(f)
    except FileNotFoundError:
        print("\n📋  No clients registered yet. Run without flags to register one.\n")
        return
    except json.JSONDecodeError:
        print("\n❌  registered_clients.json is corrupted.\n")
        return

    if not clients:
        print("\n📋  No clients found.\n")
        return

    header()
    print(f"  Found {len(clients)} registered client(s):\n")
    print(f"  {'#':<4} {'Name':<20} {'Plan':<10} {'Provider':<10} {'Registered':<22} {'Client ID'}")
    print(f"  {'-'*90}")
    for i, c in enumerate(clients, 1):
        reg_at = c.get("registered_at", "")[:19].replace("T", " ")
        print(f"  {i:<4} {c['name']:<20} {c.get('plan','?'):<10} {c.get('ai_provider','?'):<10} {reg_at:<22} {c['id']}")
    print()


def cmd_stats(client_id: str):
    """Show live stats for a client from the server."""
    print(f"\n⏳  Fetching stats for {client_id}...")
    try:
        r = requests.get(f"{BASE_URL}/api/clients/{client_id}/stats", timeout=10)
    except Exception as e:
        print(f"❌  {e}")
        return

    if r.status_code == 404:
        print(f"❌  Client not found: {client_id}")
        return
    if r.status_code != 200:
        print(f"❌  Error: {r.text}")
        return

    d = r.json()
    last = d.get("last_crawled_at", "Never")
    if last and last != "Never":
        last = last[:19].replace("T", " ")

    print(f"\n{SEPARATOR}")
    print(f"  📊  Stats for: {d['business_name']}")
    print(SEPARATOR)
    print(f"  Client ID     : {d['client_id']}")
    print(f"  Website       : {d['website_url']}")
    print(f"  Plan          : {d['plan']}")
    print(f"  AI Provider   : {d['ai_provider']}")
    print(f"  Crawl Status  : {d['crawl_status']}")
    print(f"  Pages Crawled : {d['total_pages_crawled']}")
    print(f"  Vector Chunks : {d['vector_db_chunks']}")
    print(f"  Last Crawled  : {last}")
    print(SEPARATOR + "\n")


def cmd_sync(client_id: str):
    """Trigger a smart re-crawl for a client."""
    print(f"\n⏳  Triggering sync for {client_id}...")
    try:
        r = requests.post(f"{BASE_URL}/api/clients/{client_id}/sync", timeout=10)
    except Exception as e:
        print(f"❌  {e}")
        return

    if r.status_code == 404:
        print(f"❌  Client not found: {client_id}")
        return

    d = r.json()
    print(f"\n  ✅  {d.get('message', 'Sync triggered')}")
    print(f"  Status: {d.get('status')}")
    print(f"  Run  python register_client.py --stats {client_id}  to monitor progress\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="ChatBot SaaS — Universal Client Registration Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python register_client.py                    Register new client (interactive)
  python register_client.py --list             List all registered clients
  python register_client.py --stats <id>       Show stats for a client
  python register_client.py --sync  <id>       Trigger re-crawl for a client
        """
    )
    parser.add_argument("--list",   action="store_true",   help="List all registered clients")
    parser.add_argument("--stats",  metavar="CLIENT_ID",   help="Show stats for a client")
    parser.add_argument("--sync",   metavar="CLIENT_ID",   help="Trigger re-crawl for a client")
    args = parser.parse_args()

    check_server()

    if args.list:
        cmd_list()
    elif args.stats:
        cmd_stats(args.stats)
    elif args.sync:
        cmd_sync(args.sync)
    else:
        cmd_register()


if __name__ == "__main__":
    main()
