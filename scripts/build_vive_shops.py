"""Converts VIVE_Shop_List.xlsx into config/vive_shops.json.

The shop list (Name, Phone, City, State/Province, Country) is what
src/validation/location_lookup.py maps an extracted customer location onto.
Reads the xlsx with the standard library only (an .xlsx is a zip of XML), so
no spreadsheet package is needed. Re-run when the sheet changes, then commit
the JSON.

Run:  python scripts/build_vive_shops.py [path/to/VIVE_Shop_List.xlsx]
"""
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.validation.shop_list import SHOPS_PATH  # noqa: E402

DEFAULT_XLSX = os.path.join(PROJECT_ROOT, "VIVE_Shop_List.xlsx")
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
COLUMNS = {"B": "name", "C": "phone", "D": "city", "E": "state", "F": "country"}


def _cell_text(cell, shared) -> str:
    if cell.get("t") == "s":
        return shared[int(cell.find(NS + "v").text)]
    inline = "".join(t.text or "" for t in cell.iter(NS + "t"))
    if inline:
        return inline
    value = cell.find(NS + "v")
    return value.text if value is not None and value.text else ""


def _shared_strings(z) -> list:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter(NS + "t")) for si in root.findall(NS + "si")]


def read_shops(xlsx_path: str) -> list:
    with zipfile.ZipFile(xlsx_path) as z:
        shared = _shared_strings(z)
        sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    shops = []
    for row in list(sheet.iter(NS + "row"))[1:]:
        fields = {}
        for cell in row.findall(NS + "c"):
            column = re.match(r"[A-Z]+", cell.get("r")).group()
            if column in COLUMNS:
                fields[COLUMNS[column]] = _cell_text(cell, shared).strip()
        if fields.get("name"):
            shops.append({key: fields.get(key, "") for key in COLUMNS.values()})
    return shops


def main():
    xlsx_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_XLSX
    shops = read_shops(xlsx_path)
    with open(SHOPS_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump(shops, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"{len(shops)} shops written to {SHOPS_PATH}")


if __name__ == "__main__":
    main()
