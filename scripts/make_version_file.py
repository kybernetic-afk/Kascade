"""Write version_info.txt for PyInstaller's --version-file.

Version source priority: KASCADE_VERSION env var (e.g. set from a git tag),
else kascade.__version__. Always writes a valid file.

Usage:  python scripts/make_version_file.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from kascade import __version__ as DEFAULT  # noqa: E402

OUT = os.path.join(ROOT, "version_info.txt")

TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({a}, {b}, {c}, 0),
    prodvers=({a}, {b}, {c}, 0),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'Kascade'),
        StringStruct('FileDescription', 'Kascade - modpack server updater'),
        StringStruct('FileVersion', '{v}'),
        StringStruct('InternalName', 'Kascade'),
        StringStruct('OriginalFilename', 'Kascade.exe'),
        StringStruct('ProductName', 'Kascade'),
        StringStruct('ProductVersion', '{v}'),
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main():
    raw = (os.environ.get("KASCADE_VERSION") or "").lstrip("vV").strip()
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", raw) or re.match(r"^(\d+)\.(\d+)\.(\d+)", DEFAULT)
    a, b, c = (int(match.group(i)) for i in (1, 2, 3))
    version = f"{a}.{b}.{c}.0"
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(TEMPLATE.format(a=a, b=b, c=c, v=version))
    print(f"Wrote {OUT} (version {version})")


if __name__ == "__main__":
    main()
