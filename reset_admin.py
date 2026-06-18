"""CLI script to reset the admin account — run when locked out.

Usage:
    python reset_admin.py            # Reset password to 'admin' + enable account
    python reset_admin.py --username myuser --password mypass
"""
import argparse
import sqlite3
import os
import sys

DB_PATH = os.path.join(os.path.dirname(__file__), "database", "plpr.db")


def main():
    parser = argparse.ArgumentParser(description="Reset admin credentials")
    parser.add_argument("--username", default="admin", help="Admin username (default: admin)")
    parser.add_argument("--password", default="admin", help="New password (default: admin)")
    args = parser.parse_args()

    if not os.path.isfile(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        print("Make sure the server has been started at least once.")
        sys.exit(1)

    from auth.security import hash_password

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    row = conn.execute("SELECT id, username, disabled FROM users WHERE username = ?", (args.username,)).fetchone()
    if row is None:
        print(f"User '{args.username}' not found.")
        print("Creating a new admin account...")
        from datetime import datetime
        conn.execute(
            "INSERT INTO users (username, password_hash, role, disabled, created_at) VALUES (?, ?, 'Admin', 0, ?)",
            (args.username, hash_password(args.password), datetime.now().isoformat()),
        )
        conn.commit()
        print(f"Admin account '{args.username}' created with the specified password.")
    else:
        uid = row["id"]
        was_disabled = bool(row["disabled"])
        conn.execute("UPDATE users SET password_hash = ?, disabled = 0 WHERE id = ?", (hash_password(args.password), uid))
        conn.commit()
        parts = []
        parts.append(f"password reset to '{args.password}'")
        if was_disabled:
            parts.append("account re-enabled")
        print(f"Admin '{args.username}' — {' and '.join(parts)}.")

    conn.close()
    print("\nYou can now log in with:")
    print(f"  Username: {args.username}")
    print(f"  Password: {args.password}")


if __name__ == "__main__":
    main()
