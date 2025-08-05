import json
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

table_name = 'adult'
# table_name = 'stackoverflow_db_uncleaned'
# table_name = 'crimes___one_year_prior_to_present_20250421'

DATA_FILE = Path(f"results/{table_name}_runtimes_imputation.json")
PLOT_DIR  = Path(f"results/plot_imputation_{table_name}")


# ────────── helpers ────────────────────────────────────────────────────────────
def _save(fig: plt.Figure, stem: str) -> None:
    """Save *fig* as both PNG and SVG using *stem* as the filename prefix."""
    for ext in ("png", "svg"):
        fig.savefig(PLOT_DIR / f"{stem}.{ext}", dpi=300, bbox_inches="tight")
    plt.close(fig)


def load_data(json_path: Path) -> pd.DataFrame:
    """json → tidy DataFrame  (dbms, size, time_s)."""
    with json_path.open() as fp:
        raw = json.load(fp)

    records = [
        {"dbms": dbms, "size": int(size), "time_s": t}
        for dbms, sizes in raw.items()
        for size, times in sizes.items()
        for t in times
    ]
    return pd.DataFrame.from_records(records)


def plot_box_violin(df: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(8, 6))
    sns.violinplot(
        data=df,
        x="size",
        y="time_s",
        hue="dbms",
        scale="width",
        inner="quartile",
        cut=0,
        ax=ax,
    )
    ax.set(
        xscale="log",
        yscale="log",
        xlabel="Dataset size (#rows)",
        ylabel="Query time (s)",
        title="Imputation Time",
    )
    ax.legend(title="DBMS")
    _save(fig, "01_box_violin")


def plot_median_error(df: pd.DataFrame) -> None:
    summary = (
        df.groupby(["dbms", "size"])["time_s"]
        .agg(
            median="median",
            q1=lambda s: s.quantile(0.25),
            q3=lambda s: s.quantile(0.75),
        )
        .reset_index()
    )

    fig, ax = plt.subplots(figsize=(8, 6))
    for dbms, grp in summary.groupby("dbms"):
        ax.errorbar(
            grp["size"],
            grp["median"],
            yerr=[grp["median"] - grp["q1"], grp["q3"] - grp["median"]],
            marker="o",
            label=dbms,
            capsize=4,
        )
    ax.set(
        xscale="log",
        xlabel="Dataset size (#rows)",
        ylabel="Median query time (s)",
        title="Imputation Time",
    )
    ax.legend()
    _save(fig, "02_median_error")


def plot_speed_ratio(df: pd.DataFrame) -> None:
    med = df.groupby(["dbms", "size"])["time_s"].median().unstack("dbms")
    ratio = med["pandas"] / med["postgres"]

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.plot(ratio.index, ratio.values, marker="o")
    ax.axhline(1, ls="--", color="grey")
    ax.set(
        xscale="log",
        xlabel="Dataset size (#rows)",
        ylabel="Speed-up (Postgres ÷ Pandas)",
        title="Relative speed of Postgres vs. Pandas",
    )
    _save(fig, "03_speed_ratio")


# ────────── main ───────────────────────────────────────────────────────────────
def main() -> None:
    PLOT_DIR.mkdir(parents=True, exist_ok=True)
    df = load_data(DATA_FILE)

    plot_box_violin(df)
    plot_median_error(df)
    plot_speed_ratio(df)


if __name__ == "__main__":
    main()
