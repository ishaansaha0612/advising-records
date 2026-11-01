"""Generate three messy student-record exports the way real offices produce them.

- registrar_roster.csv        clean-ish, has IDs, "First Last" names
- advising_contacts.xlsx      typed by hand: "Last, First", phone formats vary,
                              IDs sometimes missing or missing leading zeros
- early_alert_list.xlsx       pulled from a different system: IDs prefixed
                              "NT", emails in caps, nicknames, typos, repeats

A hidden ground-truth file maps every row to the real student so the merge
can be scored honestly. All people are fictional.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

FIRST = ["James", "Maria", "Robert", "Priya", "Michael", "Jennifer", "William", "Aisha", "David", "Linh",
         "Daniel", "Sofia", "Matthew", "Fatima", "Anthony", "Emily", "Joshua", "Grace", "Andrew", "Mei",
         "Christopher", "Olivia", "Joseph", "Isabella", "Kevin", "Ananya", "Brian", "Chloe", "Jacob", "Zara",
         "Nathan", "Hannah", "Ryan", "Camila", "Tyler", "Leah", "Samuel", "Nia", "Ethan", "Rosa"]
NICK = {"James": "Jim", "Robert": "Bob", "Michael": "Mike", "Jennifer": "Jen", "William": "Will",
        "Daniel": "Dan", "Matthew": "Matt", "Anthony": "Tony", "Joshua": "Josh", "Andrew": "Drew",
        "Christopher": "Chris", "Joseph": "Joe", "Isabella": "Bella", "Samuel": "Sam", "Nathan": "Nate"}
LAST = ["Garcia", "Nguyen", "Smith", "Patel", "Johnson", "Kim", "Williams", "Hernandez", "Brown", "Tran",
        "Jones", "Lopez", "Miller", "Shah", "Davis", "Martinez", "Wilson", "Chen", "Anderson", "Okafor",
        "Thomas", "Rodriguez", "Moore", "Ali", "Jackson", "Gonzalez", "White", "Pham", "Harris", "Reddy",
        "Clark", "Ramirez", "Lewis", "Singh", "Walker", "Torres", "Hall", "Mensah", "Young", "Rivera"]
MAJORS = ["Information Systems", "Computer Science", "Biology", "Accounting", "Psychology", "Marketing",
          "Mechanical Engineering", "Finance", "Nursing", "Economics"]


def _typo(rng, s: str) -> str:
    if len(s) < 4:
        return s
    i = int(rng.integers(1, len(s) - 1))
    return s[:i] + s[i + 1] + s[i] + s[i + 2:]  # swap two letters


def _phone(rng, digits: str) -> str:
    style = rng.integers(0, 4)
    return [f"({digits[:3]}) {digits[3:6]}-{digits[6:]}", f"{digits[:3]}-{digits[3:6]}-{digits[6:]}",
            f"{digits[:3]}.{digits[3:6]}.{digits[6:]}", digits][style]


def students(rng, n=4200) -> pd.DataFrame:
    first = rng.choice(FIRST, n)
    last = rng.choice(LAST, n)
    sid = rng.choice(np.arange(1000000, 9999999), n, replace=False).astype(str)
    sid = np.array(["0" + s[1:] if rng.random() < 0.15 else s for s in sid])  # some IDs start with 0
    email = [f"{f[0].lower()}{l.lower()}{s[-4:]}@student.example.edu" for f, l, s in zip(first, last, sid)]
    phone = ["".join(map(str, rng.integers(0, 10, 10))) for _ in range(n)]
    for i in range(n):
        if phone[i][0] in "01":
            phone[i] = "9" + phone[i][1:]
    return pd.DataFrame({"true_id": sid, "first": first, "last": last, "email": email, "phone": phone,
                         "major": rng.choice(MAJORS, n), "class_year": rng.choice([2026, 2027, 2028, 2029], n)})


def generate(seed: int = 42) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    pop = students(rng)

    # Registrar: 3,600 students, tidy, a handful of exact duplicate rows
    reg = pop.sample(3600, random_state=seed).copy()
    reg = pd.concat([reg, reg.sample(40, random_state=1)])
    registrar = pd.DataFrame({
        "Student ID": reg.true_id, "First Name": reg["first"], "Last Name": reg["last"],
        "Email": reg.email, "Major": reg.major, "Expected Grad": reg.class_year,
    })

    # Advising contacts: 3,500 rows typed by hand
    adv = pop.sample(3300, random_state=seed + 1)
    adv = pd.concat([adv, adv.sample(200, random_state=2)])
    ids = []
    for s in adv.true_id:
        r = rng.random()
        ids.append("" if r < 0.12 else (s.lstrip("0") if r < 0.30 else s))
    names = [f"{l}, {f}" if rng.random() > 0.08 else f"{l.upper()}, {f}" for f, l in zip(adv["first"], adv["last"])]
    names = [_typo(rng, n) if rng.random() < 0.03 else n for n in names]
    advising = pd.DataFrame({
        "ID #": ids, "Name": [n + ("  " if rng.random() < 0.1 else "") for n in names],
        "E-mail": adv.email, "Phone": [_phone(rng, p) for p in adv.phone],
        "Advisor": rng.choice(["Ortiz", "Brennan", "Kaur", "Whitfield", "Adeyemi"], len(adv)),
    })

    # Early alert list: 2,300 rows from another system
    ea = pop.sample(2100, random_state=seed + 2)
    ea = pd.concat([ea, ea.sample(200, random_state=3)])
    firsts = [NICK[f] if f in NICK and rng.random() < 0.35 else f for f in ea["first"]]
    firsts = [_typo(rng, f) if rng.random() < 0.03 else f for f in firsts]
    early = pd.DataFrame({
        "STUDENT_NUM": ["NT" + s if rng.random() > 0.1 else "" for s in ea.true_id],
        "FIRST": firsts, "LAST": ea["last"].str.upper(),
        "EMAIL_ADDR": [e.upper() if rng.random() < 0.5 else e for e in ea.email],
        "PHONE": [_phone(rng, p) for p in ea.phone],
        "ALERT_REASON": rng.choice(["Missed classes", "Low midterm grade", "Financial hold", "Self-referral"], len(ea)),
    })
    # When an ID is missing AND the email is missing, a row can only be matched by name + phone
    drop_email = rng.random(len(early)) < 0.05
    early.loc[drop_email, "EMAIL_ADDR"] = ""

    truth = pd.concat([
        pd.DataFrame({"source": "registrar", "row": range(len(reg)), "true_id": reg.true_id.values}),
        pd.DataFrame({"source": "advising", "row": range(len(adv)), "true_id": adv.true_id.values}),
        pd.DataFrame({"source": "early_alert", "row": range(len(ea)), "true_id": ea.true_id.values}),
    ])
    return {"registrar": registrar.reset_index(drop=True), "advising": advising.reset_index(drop=True),
            "early_alert": early.reset_index(drop=True), "truth": truth, "population": pop}


def appointments(pop: pd.DataFrame, seed: int = 42) -> pd.DataFrame:
    """Two fall semesters of advising appointment requests (15-minute grain)."""
    rng = np.random.default_rng(seed)
    rows = []
    for start in ["2024-08-26", "2025-08-25"]:
        days = pd.bdate_range(start, periods=16 * 5)
        for d in days:
            week = (d - pd.Timestamp(start)).days // 7 + 1
            # registration week (11) and midterm feedback (8) spike; quiet weeks 13-15
            mult = {1: 1.4, 2: 1.2, 8: 1.6, 10: 1.5, 11: 2.4, 12: 1.3}.get(week, 0.8 if week >= 13 else 1.0)
            dow_mult = [1.2, 1.1, 1.0, 1.0, 0.7][d.dayofweek]
            n = rng.poisson(26 * mult * dow_mult)
            hours = rng.choice(np.arange(9, 17), n, p=[0.07, 0.13, 0.14, 0.12, 0.13, 0.17, 0.14, 0.10])
            for h in hours:
                rows.append((d, int(week), h, rng.choice(pop.true_id)))
    df = pd.DataFrame(rows, columns=["date", "week_of_semester", "hour", "student_id"])
    df["semester"] = np.where(df.date.dt.year == 2024, "Fall 2024", "Fall 2025")
    return df


if __name__ == "__main__":
    out = Path("data"); out.mkdir(exist_ok=True)
    g = generate()
    g["registrar"].to_csv(out / "registrar_roster.csv", index=False)
    g["advising"].to_excel(out / "advising_contacts.xlsx", index=False)
    g["early_alert"].to_excel(out / "early_alert_list.xlsx", index=False)
    g["truth"].to_csv(out / "_ground_truth.csv", index=False)
    appointments(g["population"]).to_csv(out / "appointments.csv", index=False)
    print("Wrote raw files to data/")
