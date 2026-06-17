"""Generate CompetitionGroups person QR PNGs and update registration CSV."""

from __future__ import annotations

import csv
from pathlib import Path

import qrcode
from qrcode.constants import ERROR_CORRECT_M
from PIL import Image

COMP_URL = "https://www.competitiongroups.com/competitions/ChinchinaOpen2026"
PERSON_BASE = f"{COMP_URL}/persons"
REPO_ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = REPO_ROOT / "ChinchinaOpen2026-registration.csv"
OUT_DIR = REPO_ROOT / "img" / "chinchina_open2026_qr"


def _write_qr_png(url: str, out_path: Path) -> None:
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=12,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    # Build the QR in black/white first, then convert to white modules
    # on a transparent background for print workflows.
    img = qr.make_image(fill_color="black", back_color="white").convert("RGBA")
    pixels = img.getdata()
    converted = []
    for r, g, b, _a in pixels:
        if (r, g, b) == (0, 0, 0):
            converted.append((255, 255, 255, 255))  # QR modules in white
        else:
            converted.append((255, 255, 255, 0))  # transparent background
    img.putdata(converted)
    img.save(out_path)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    fieldnames = list(rows[0].keys()) if rows else []
    qr_col = "QR path"
    if qr_col not in fieldnames:
        fieldnames.append(qr_col)

    for row in rows:
        pid = (row.get("Id") or "").strip()
        if pid:
            url = f"{PERSON_BASE}/{pid}"
            rel = Path("img") / "chinchina_open2026_qr" / f"person_{pid}.png"
        else:
            url = COMP_URL
            rel = Path("img") / "chinchina_open2026_qr" / "competition.png"
        out_path = REPO_ROOT / rel
        _write_qr_png(url, out_path)
        row[qr_col] = str(rel).replace("\\", "/")

    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
