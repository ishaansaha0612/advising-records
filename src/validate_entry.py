"""Data-entry checks for the hand-typed advising sheet.

Run before uploading a new batch: it lists every row that breaks a rule, so
student workers fix errors at entry time instead of someone cleaning later.
Usage:  python -m src.validate_entry data/advising_contacts.xlsx
"""
from __future__ import annotations

import re
import sys

import pandas as pd

RULES = [
    ("ID # missing", lambda r: str(r["ID #"]).strip() in ("", "nan")),
    ("ID # not 7 digits (leading zero dropped?)",
     lambda r: str(r["ID #"]).strip() not in ("", "nan") and not re.fullmatch(r"\d{7}", str(r["ID #"]).strip())),
    ("Name not 'Last, First'", lambda r: not re.fullmatch(r"[A-Za-z'\- ]+, [A-Za-z'\- ]+", str(r["Name"]).strip())),
    ("Name typed in ALL CAPS", lambda r: str(r["Name"]).split(",")[0].isupper()),
    ("Extra spaces", lambda r: str(r["Name"]) != str(r["Name"]).strip()),
    ("Email not a school address", lambda r: not str(r["E-mail"]).lower().endswith("@student.example.edu")),
    ("Phone not (###) ###-####", lambda r: not re.fullmatch(r"\(\d{3}\) \d{3}-\d{4}", str(r["Phone"]))),
]


def check(df: pd.DataFrame) -> pd.DataFrame:
    issues = []
    for i, r in df.iterrows():
        for name, rule in RULES:
            if rule(r):
                issues.append({"excel_row": i + 2, "issue": name, "Name": r["Name"], "ID #": r["ID #"]})
    return pd.DataFrame(issues)


def main(path: str) -> None:
    df = pd.read_excel(path, dtype=str).fillna("")
    issues = check(df)
    rows_bad = issues.excel_row.nunique() if len(issues) else 0
    print(f"{len(df):,} rows checked, {rows_bad:,} rows with at least one issue ({rows_bad / len(df):.0%})\n")
    if len(issues):
        print(issues.issue.value_counts().to_string())
        out = path.rsplit(".", 1)[0] + "_issues.csv"
        issues.to_csv(out, index=False)
        print(f"\nRow-by-row list: {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/advising_contacts.xlsx")
