"""When do students want advising, and where should drop-in hours go?

Compares appointment requests to advisor capacity by week of semester and hour
of day, then finds the smallest set of drop-in blocks that absorbs the
overflow. Also writes a star-schema export that loads straight into Power BI
or Tableau (fact table + date dimension).
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

ADVISORS = 5
SLOTS_PER_ADVISOR_HOUR = 2       # 30-minute appointments
CAPACITY_PER_HOUR = ADVISORS * SLOTS_PER_ADVISOR_HOUR * 0.6  # 60% of time is bookable; rest is email/admin
INK, MUTED = "#1f2a37", "#8a94a3"
SEQ = LinearSegmentedColormap.from_list("blue", ["#f1f6fd", "#9ec5f4", "#3987e5", "#184f95", "#0d366b"])


def load(path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["date"], dtype={"student_id": str})
    df["weekday"] = df.date.dt.day_name().str[:3]
    return df


def load_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Average requests per hour, by week of semester x hour of day."""
    days_per_week = df.groupby(["semester", "week_of_semester"]).date.nunique().groupby(level=1).sum()
    m = df.groupby(["week_of_semester", "hour"]).size().unstack(fill_value=0)
    return m.div(days_per_week, axis=0)


def drop_in_plan(m: pd.DataFrame) -> pd.DataFrame:
    """Each (week, hour) cell where demand beats capacity gets a drop-in block,
    sized to the number of extra advisors needed."""
    over = (m - CAPACITY_PER_HOUR).clip(lower=0)
    plan = over.stack().reset_index(name="excess_requests")
    plan = plan[plan.excess_requests > 0.5]
    plan["extra_advisors"] = np.ceil(plan.excess_requests / SLOTS_PER_ADVISOR_HOUR).astype(int)
    return plan.sort_values(["week_of_semester", "hour"])


def plot(m: pd.DataFrame, plan: pd.DataFrame, path: Path):
    fig, ax = plt.subplots(figsize=(9, 6))
    util = m / CAPACITY_PER_HOUR * 100
    im = ax.imshow(util.values, cmap=SEQ, aspect="auto", vmin=0, vmax=max(150, util.values.max()))
    ax.set_yticks(range(len(m.index)), [f"Wk {w}" for w in m.index])
    ax.set_xticks(range(len(m.columns)), [f"{h % 12 or 12}{'a' if h < 12 else 'p'}" for h in m.columns])
    for _, r in plan.iterrows():
        y = list(m.index).index(r.week_of_semester)
        x = list(m.columns).index(r.hour)
        ax.add_patch(plt.Rectangle((x - 0.5, y - 0.5), 1, 1, fill=False, ec="#eb6834", lw=2))
    for (y, x), v in np.ndenumerate(util.values):
        if v >= 100:
            ax.text(x, y, f"{v:.0f}", ha="center", va="center", fontsize=7, color="white")
    cb = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.02)
    cb.set_label("Demand as % of advisor capacity", color=INK)
    ax.set_title("Appointment demand vs. capacity, by week of semester and hour\n"
                 "Orange outline = drop-in block recommended (demand over ~108% of capacity)", loc="left", color=INK, fontsize=11)
    for s in ax.spines.values():
        s.set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def bi_export(df: pd.DataFrame, golden: pd.DataFrame, out: Path):
    bi = out / "powerbi"
    bi.mkdir(exist_ok=True)
    fact = df[["date", "hour", "student_id", "semester", "week_of_semester"]].copy()
    fact.insert(0, "appointment_id", range(1, len(fact) + 1))
    fact.to_csv(bi / "fact_appointment_requests.csv", index=False)
    dates = pd.DataFrame({"date": pd.to_datetime(sorted(df.date.unique()))})
    dates["weekday"] = dates.date.dt.day_name()
    dates["month"] = dates.date.dt.month_name()
    dates.merge(df[["date", "semester", "week_of_semester"]].drop_duplicates(), on="date") \
        .to_csv(bi / "dim_date.csv", index=False)
    golden.to_csv(bi / "dim_student.csv", index=False)


def run(appt_path, golden: pd.DataFrame, out: Path) -> dict:
    df = load(appt_path)
    m = load_matrix(df)
    plan = drop_in_plan(m)
    plot(m, plan, out / "demand_heatmap.png")
    plan.round(2).to_csv(out / "drop_in_plan.csv", index=False)
    bi_export(df, golden, out)
    weeks = sorted(plan.week_of_semester.unique().tolist())
    return {
        "requests": int(len(df)),
        "capacity_per_hour": CAPACITY_PER_HOUR,
        "peak_weeks": weeks,
        "drop_in_blocks": int(len(plan)),
        "drop_in_advisor_hours_per_semester": int(plan.extra_advisors.sum() * 5),  # each block runs Mon-Fri that week
        "busiest_cell_pct_of_capacity": round(float((m / CAPACITY_PER_HOUR).values.max() * 100), 0),
    }
