"""Clean, merge and de-duplicate three student-record exports into one table.

Matching runs in passes, strictest first, so every merge has a reason:
  1. Same normalized student ID
  2. No ID: same email
  3. No ID or email: same phone AND same last name
  4. Still unmatched: fuzzy full-name match (nicknames and typos tolerated)
     against records sharing the same phone, with no conflicting email
Anything left over becomes its own record and is flagged for review.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

NICKNAMES = {"jim": "james", "bob": "robert", "mike": "michael", "jen": "jennifer", "will": "william",
             "dan": "daniel", "matt": "matthew", "tony": "anthony", "josh": "joshua", "drew": "andrew",
             "chris": "christopher", "joe": "joseph", "bella": "isabella", "sam": "samuel", "nate": "nathan"}
SOURCE_PRIORITY = {"registrar": 0, "advising": 1, "early_alert": 2}
FUZZY_THRESHOLD = 88


def norm_id(x) -> str:
    s = re.sub(r"\D", "", str(x or ""))
    return s.zfill(7) if s else ""


def norm_phone(x) -> str:
    s = re.sub(r"\D", "", str(x or ""))
    return s[-10:] if len(s) >= 10 else ""


def norm_email(x) -> str:
    s = str(x or "").strip().lower()
    return s if re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", s) else ""


def title(x) -> str:
    return " ".join(w.capitalize() for w in str(x or "").strip().split())


def standardize(registrar: pd.DataFrame, advising: pd.DataFrame, early: pd.DataFrame) -> pd.DataFrame:
    r = pd.DataFrame({
        "source": "registrar", "row": registrar.index,
        "student_id": registrar["Student ID"].map(norm_id),
        "first": registrar["First Name"].map(title), "last": registrar["Last Name"].map(title),
        "email": registrar["Email"].map(norm_email), "phone": "",
        "major": registrar["Major"], "expected_grad": registrar["Expected Grad"],
    })
    split = advising["Name"].fillna("").str.split(",", n=1, expand=True)
    a = pd.DataFrame({
        "source": "advising", "row": advising.index,
        "student_id": advising["ID #"].map(norm_id),
        "first": split[1].map(title), "last": split[0].map(title),
        "email": advising["E-mail"].map(norm_email), "phone": advising["Phone"].map(norm_phone),
        "advisor": advising["Advisor"],
    })
    e = pd.DataFrame({
        "source": "early_alert", "row": early.index,
        "student_id": early["STUDENT_NUM"].map(norm_id),
        "first": early["FIRST"].map(title), "last": early["LAST"].map(title),
        "email": early["EMAIL_ADDR"].map(norm_email), "phone": early["PHONE"].map(norm_phone),
        "alert_reason": early["ALERT_REASON"],
    })
    df = pd.concat([r, a, e], ignore_index=True)
    df["first_canon"] = df["first"].str.lower().map(lambda f: NICKNAMES.get(f, f))
    df["full_canon"] = df.first_canon + " " + df["last"].str.lower()
    return df


def assign_ids(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    df = df.copy()
    df["match_key"] = df.student_id
    df["match_rule"] = np.where(df.student_id != "", "1 student ID", "")
    known = df[df.match_key != ""]

    by_email = known[known.email != ""].drop_duplicates("email").set_index("email").match_key
    by_phone_last = known[known.phone != ""].assign(k=lambda d: d.phone + "|" + d["last"].str.lower()) \
        .drop_duplicates("k").set_index("k").match_key
    pending = df.match_key == ""

    hit = pending & df.email.isin(by_email.index)
    df.loc[hit, "match_key"] = df.loc[hit, "email"].map(by_email)
    df.loc[hit, "match_rule"] = "2 email"

    pending = df.match_key == ""
    k = df.phone + "|" + df["last"].str.lower()
    hit = pending & (df.phone != "") & k.isin(by_phone_last.index)
    df.loc[hit, "match_key"] = k[hit].map(by_phone_last)
    df.loc[hit, "match_rule"] = "3 phone + last name"

    # Pass 4: fuzzy name within a candidate block
    ref = df[df.match_key != ""].drop_duplicates(["match_key", "full_canon", "phone", "email"])
    for i in df.index[df.match_key == ""]:
        row = df.loc[i]
        block = ref[((ref.phone == row.phone) & (row.phone != "")) | (ref["last"].str.lower() == row["last"].lower())]
        if block.empty:
            continue
        scores = block.full_canon.map(lambda n: fuzz.ratio(n, row.full_canon))
        strong = block[scores >= FUZZY_THRESHOLD]
        if strong.match_key.nunique() == 1:
            # A name alone is never enough: common names collide (two Grace Walkers).
            # Require the same phone, and no conflicting email.
            same_phone = row.phone != "" and (strong.phone == row.phone).any()
            emails = set(strong.email) - {""}
            conflict = row.email != "" and emails and row.email not in emails
            if same_phone and not conflict:
                df.at[i, "match_key"] = strong.match_key.iloc[0]
                df.at[i, "match_rule"] = "4 fuzzy name + phone"

    leftover = df.match_key == ""
    # Leftovers may still repeat each other: group them by email, else phone
    left = df[leftover]
    key = np.where(left.email != "", "e:" + left.email,
                   np.where(left.phone != "", "p:" + left.phone, "r:" + left.index.astype(str)))
    codes = pd.Series(key, index=left.index).astype("category").cat.codes
    df.loc[leftover, "match_key"] = "NEW-" + codes.astype(str).str.zfill(3)
    df.loc[leftover, "match_rule"] = "5 unmatched (review)"
    stats = df.match_rule.value_counts().sort_index().to_dict()
    return df, stats


def golden_records(df: pd.DataFrame) -> pd.DataFrame:
    """One row per student: each field taken from the highest-priority source that has it."""
    df = df.assign(prio=df.source.map(SOURCE_PRIORITY)).sort_values(["match_key", "prio"])

    def first_nonblank(s):
        s = s.replace("", np.nan).dropna()
        return s.iloc[0] if len(s) else ""

    g = df.groupby("match_key").agg(
        first=("first", first_nonblank), last=("last", first_nonblank), email=("email", first_nonblank),
        phone=("phone", first_nonblank), major=("major", first_nonblank),
        expected_grad=("expected_grad", first_nonblank), advisor=("advisor", first_nonblank),
        in_registrar=("source", lambda s: "registrar" in set(s)),
        in_advising=("source", lambda s: "advising" in set(s)),
        early_alerts=("alert_reason", lambda s: s.dropna().nunique()),
        source_rows=("source", "size"),
    ).reset_index().rename(columns={"match_key": "student_id"})
    g["needs_review"] = g.student_id.str.startswith("NEW-")
    return g


def score(df: pd.DataFrame, truth: pd.DataFrame) -> dict:
    """Pairwise precision/recall: of all row pairs we merged, how many are truly the same person?"""
    m = df.merge(truth, on=["source", "row"])
    pred = m.groupby("match_key").size()
    true = m.groupby("true_id").size()
    both = m.groupby(["match_key", "true_id"]).size()
    pairs = lambda s: int((s * (s - 1) // 2).sum())
    tp, pp, ap = pairs(both), pairs(pred), pairs(true)
    return {
        "rows_in": int(len(m)),
        "records_out": int(m.match_key.nunique()),
        "true_students": int(m.true_id.nunique()),
        "pair_precision": round(tp / pp, 4) if pp else 1.0,
        "pair_recall": round(tp / ap, 4) if ap else 1.0,
        "duplicates_removed": int(len(m) - m.match_key.nunique()),
    }
