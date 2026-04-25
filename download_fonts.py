#!/usr/bin/env python3
"""Download NotoSansTamil-Regular.ttf from Google's noto-fonts GitHub repo."""
import os
import urllib.request

FONTS_DIR = os.path.join(os.path.dirname(__file__), "fonts")
FONT_FILE = os.path.join(FONTS_DIR, "NotoSansTamil-Regular.ttf")

# Static regular-weight TTF from the official Google noto-fonts repository
FONT_URL = (
    "https://github.com/googlefonts/noto-fonts/raw/main"
    "/hinted/ttf/NotoSansTamil/NotoSansTamil-Regular.ttf"
)


def download() -> None:
    os.makedirs(FONTS_DIR, exist_ok=True)
    if os.path.exists(FONT_FILE):
        print(f"✅ Font already present: {FONT_FILE}")
        return

    print(f"⬇️  Downloading NotoSansTamil-Regular.ttf …")
    try:
        urllib.request.urlretrieve(FONT_URL, FONT_FILE)
        size_kb = os.path.getsize(FONT_FILE) / 1024
        print(f"✅ Saved to {FONT_FILE}  ({size_kb:.0f} KB)")
    except Exception as exc:
        print(f"❌ Download failed: {exc}")
        print(
            "\nManual alternative:\n"
            "1. Open https://fonts.google.com/noto/specimen/Noto+Sans+Tamil\n"
            "2. Click 'Download family'\n"
            "3. Extract NotoSansTamil-Regular.ttf\n"
            "4. Place it in the fonts/ directory"
        )
        raise


if __name__ == "__main__":
    download()
