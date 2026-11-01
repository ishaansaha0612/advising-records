"""One command: generate messy exports, validate, merge, score, analyze demand."""
import json
import sqlite3
from pathlib import Path

import pandas as pd

from src.generate_data import generate, appointments
from src.merge import standardize, assign_ids, golden_records, score
from src.validate_entry import check
from src import demand

data, out = Path("data"), Path("outputs")
data.mkdir(exist_ok=True); out.mkdir(exist_ok=True)

# 1. Raw exports, written the way each office would hand them over
g = generate()
g["registrar"].to_csv(data / "registrar_roster.csv", index=False)
g["advising"].to_excel(data / "advising_contacts.xlsx", index=False)
g["early_alert"].to_excel(data / "early_alert_list.xlsx", index=False)
g["truth"].to_csv(data / "_ground_truth.csv", index=False)
appointments(g["population"]).to_csv(data / "appointments.csv", index=False)

# 2. Read them back as a stranger would (everything as text)
reg = pd.read_csv(data / "registrar_roster.csv", dtype=str).fillna("")
adv = pd.read_excel(data / "advising_contacts.xlsx", dtype=str).fillna("")
ea = pd.read_excel(data / "early_alert_list.xlsx", dtype=str).fillna("")

issues = check(adv)
issues.to_csv(out / "entry_issues.csv", index=False)

# 3. Merge and de-duplicate
rows = standardize(reg, adv, ea)
matched, rule_counts = assign_ids(rows)
golden = golden_records(matched)
quality = score(matched, g["truth"])

con = sqlite3.connect(out / "students.db")
golden.to_sql("students", con, if_exists="replace", index=False)
matched.drop(columns=["first_canon", "full_canon"]).to_sql("source_rows", con, if_exists="replace", index=False)
golden.to_csv(out / "students_clean.csv", index=False)

# 4. Appointment demand
dem = demand.run(data / "appointments.csv", golden, out)

report = {
    "input_rows": {"registrar": len(reg), "advising": len(adv), "early_alert": len(ea), "total": len(rows)},
    "entry_validation": {"rows_with_issues": int(issues.excel_row.nunique()),
                         "by_issue": issues.issue.value_counts().to_dict()},
    "rows_matched_by_rule": rule_counts,
    "merge_quality_vs_ground_truth": quality,
    "records_needing_review": int(golden.needs_review.sum()),
    "demand": dem,
}
(out / "report.json").write_text(json.dumps(report, indent=2, default=int))
print(json.dumps(report, indent=2, default=int))
