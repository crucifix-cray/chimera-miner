#!/usr/bin/env python3
"""Initialize Mega database with existing sessions and project"""

import sys
import json
from pathlib import Path

sys.path.insert(0, "/home/alan/Documents/chimera-miner")
from mega_db import load_db, save_db

# Load session test results
results_file = Path("/home/alan/session_test_results.json")

print("=" * 60)
print("🔧 INITIALIZING MEGA DATABASE")
print("=" * 60)

# Load DB
print("\n📥 Loading Mega database...")
db = load_db()

# Load session test results
print("📋 Loading session test results...")
with open(results_file) as f:
    session_results = json.load(f)

# Add all sessions
print("\n👥 Adding sessions...")
for result in session_results:
    if result["status"] == "active":
        db.add_session(
            f"session-{result['id']}",
            result["email"],
            "active"
        )
    elif result["status"] == "expired":
        db.add_session(
            f"session-{result['id']}",
            result["email"],
            "red"
        )

# Add existing project (session 3's project)
print("\n📦 Adding existing project...")
db.add_project({
    "project_id": "c5a42f16-ef02-4ee8-93b8-dbbf781db421",
    "invite_link": "https://lovable.dev/projects/c5a42f16-ef02-4ee8-93b8-dbbf781db421",
    "chat_url": "https://lovable.dev/projects/c5a42f16-ef02-4ee8-93b8-dbbf781db421",
    "preview_url": "https://c5a42f16-ef02-4ee8-93b8-dbbf781db421.lovableproject.com",
    "created_by": "session-3",
    "usage_count": 0,
    "max_usage": 20,
    "status": "active"
})

# Save to Mega
print("\n💾 Saving to Mega...")
save_db(db)

# Show stats
print("\n")
db.print_stats()

print("✅ Database initialized successfully!")
print("\nNext steps:")
print("  1. Test Script 3: python3 script3_launch_miner.py --session 3 --mode oneshot")
print("  2. Create more projects: python3 script2_remix_link.py --session 3 --count 5")
