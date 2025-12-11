"""
Utility: re-scan images and reconcile missing thumbnail URLs in the CSV.
Run: python recover_image_links.py
"""
from pathlib import Path
import csv
from config import CSV_FILE
from utils import get_thumbnail_url


def main():
    rows = []
    changed = 0
    if not Path(CSV_FILE).exists():
        print(f"No CSV at {CSV_FILE}")
        return
    with open(CSV_FILE, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            img = row.get("image_filename", "")
            thumb = get_thumbnail_url(img)
            if thumb and thumb != row.get("thumb_url", ""):
                row["thumb_url"] = thumb
                changed += 1
            rows.append(row)

    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id","name","description","qty","image_filename","thumb_url"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    print(f"Updated {changed} row(s). Saved -> {CSV_FILE}")


if __name__ == "__main__":
    main()