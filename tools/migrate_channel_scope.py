"""Migrate legacy channel registry rows whose display label was used as channel_id."""
from __future__ import annotations

import argparse
import re
import sqlite3
from pathlib import Path

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return slug or "channel"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("runtime/platform.sqlite3"))
    parser.add_argument("--channel-id", help="Existing invalid channel_id to migrate")
    parser.add_argument("--new-id", help="Safe replacement, e.g. kenh-nhat")
    parser.add_argument("--apply", action="store_true", help="Write the migration; otherwise preview")
    args = parser.parse_args()

    con = sqlite3.connect(args.db)
    rows = con.execute(
        "SELECT user_id, channel_id, youtube_channel_id, title, active FROM channels"
    ).fetchall()
    invalid = [row for row in rows if not SAFE_ID.fullmatch(str(row[1]))]
    if not invalid:
        print("No invalid channel scope IDs found.")
        return 0

    for user_id, old_id, youtube_id, title, active in invalid:
        new_id = args.new_id if args.channel_id == old_id and args.new_id else slugify(title or old_id)
        if not SAFE_ID.fullmatch(new_id):
            raise SystemExit(f"Invalid replacement ID: {new_id}")
        print(f"{user_id}: {old_id!r} -> {new_id!r} ({youtube_id})")
        if args.apply:
            con.execute(
                "UPDATE channels SET channel_id=?, updated_at=CURRENT_TIMESTAMP WHERE user_id=? AND channel_id=?",
                (new_id, user_id, old_id),
            )
    if args.apply:
        con.commit()
        print("Migration applied. The display label remains in title.")
    else:
        print("Preview only. Re-run with --apply after checking the replacements.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
