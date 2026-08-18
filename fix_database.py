#!/usr/bin/env python3
"""Fix database: link project owner to session"""

import sys
sys.path.insert(0, "/home/alan/Documents/chimera-miner")
from mega_db import load_db, save_db

print("🔧 Fixing database linkage...")

db = load_db()

# Update session-3 to reflect it created this project
session3 = db.get_session("session-3")
if session3:
    db.update_session("session-3", projects_created=1)
    print("✅ Updated session-3: projects_created = 1")

save_db(db)

print("\n📊 Database fixed!")
db.print_stats()
