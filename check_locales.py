"""Checks that every language in locales/ has the same texts and the same {placeholders} as en.json."""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ref = json.loads((HERE / "locales" / "en.json").read_text(encoding="utf-8"))
source = (HERE / "phone_transfer.py").read_text(encoding="utf-8")
used = set(re.findall(r'T\("(\w+)"', source)) | set(re.findall(r'self\.label\([^\n]*?, "(\w+)"\)', source)) | set(re.findall(r'\("(g_\w+)"', source))
bad = 0
for key in sorted(used - set(ref)):
    print(f"en: text used by the program is missing: {key}")
    bad += 1
for f in sorted((HERE / "locales").glob("*.json")):
    lang = json.loads(f.read_text(encoding="utf-8"))
    for key, text in ref.items():
        if key not in lang:
            print(f"{f.stem}: missing {key}")
            bad += 1
        elif sorted(re.findall(r"\{(\w+)\}", text)) != sorted(re.findall(r"\{(\w+)\}", lang[key])):
            print(f"{f.stem}: placeholders differ in {key}")
            bad += 1
    for key in lang:
        if key not in ref:
            print(f"{f.stem}: unknown {key}")
            bad += 1
print("ok" if not bad else f"{bad} problem(s)")
sys.exit(1 if bad else 0)
