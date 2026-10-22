"""
triangles.py — Triangle Building and Outlier Detection

Converts from:
  - SLU_main_code.R (triangle building sections inside run_mbr, lines ~340-730)
  - MBR_weighted_average.R (fn_get_age_to_age_outliers function, lines 1-76)

This module handles two things:
  1. Building loss development triangles (incremental and cumulative) from raw data,
     supporting both YQ (quarterly) and YY (annual) granularity.
  2. Detecting outlier age-to-age factors using the adjusted boxplot method with medcouple.
"""

import numpy as np
import pandas as pd
from scipy.stats import skew

try:
    from statsmodels.stats.statlib import medcouple_1d
except ImportError:
    medcouple_1d = None


# ---------------------------------------------------------------------------
# Part 1: Triangle Building
# ---------------------------------------------------------------------------

def build_all_combinations(profile_ids, analysis_year, analysis_qtr, years_analyzed, ri_types):
    """
    Build the complete grid of (profile_id x exp_year x dev_len x Ri_type)
    and mark which cells fall in the lower triangle (future, unobserved).

    R equivalent: lines ~349-374 in SLU_main_code.R — the cross-join of
    exp_year, dev_len, profile_id, Ri_type with lower_tri_cmbn flag.

    Parameters
    ----------
    profile_ids : list
        Unique profile identifiers.
    analysis_year : int
        The evaluation year (e.g., 2026).
    analysis_qtr : int
        The evaluation quarter (1-4).
    years_analyzed : int
        Number of exposure years in the analysis window.
    ri_types : list
        Reinsurance types (e.g., ['Gross']).

    Returns
    -------
    all_cmbn : pd.DataFrame
        Complete grid with columns [profile_id, exp_year, dev_len, Ri_type,
        Gross_Incurred, max_dev_len, lower_tri_cmbn].
    exp_year_dev_len : pd.DataFrame
        Mapping of each exp_year to its max observable dev_len.
    """
    # Exposure years: from (analysis_year - years_analyzed + 1) to analysis_year
    exp_years = list(range(analysis_year - years_analyzed + 1, analysis_year + 1))

    # Development periods in months: 3, 6, 9, ... up to the max observable
    max_dev = 3 * 4 * years_analyzed - 3 * (4 - analysis_qtr)
    dev_lens = list(range(3, max_dev + 1, 3))

    # Each exposure year has a maximum observable development length
    # Oldest year has the longest history, newest year has the shortest
    max_dev_lens = [3 * analysis_qtr + 12 * i for i in range(years_analyzed)]
    exp_year_dev_len = pd.DataFrame({
        "exp_year": exp_years,
        "max_dev_len": max_dev_lens
    })

    # Build the full cross-join grid
    grid_rows = []
    for pid in profile_ids:
        for ey in exp_years:
            for dl in dev_lens:
                for ri in ri_types:
                    grid_rows.append((pid, ey, dl, ri, 0.0))

    all_cmbn = pd.DataFrame(
        grid_rows,
        columns=["profile_id", "exp_year", "dev_len", "Ri_type", "Gross_Incurred"]
    )

    # Merge max_dev_len and flag lower triangle (unobserved) cells
    all_cmbn = all_cmbn.merge(exp_year_dev_len, on="exp_year", how="left")
    all_cmbn["lower_tri_cmbn"] = (all_cmbn["dev_len"] > all_cmbn["max_dev_len"]).astype(int)

    return all_cmbn, exp_year_dev_len


def fill_missing_upper_triangle(actuals_cl, all_cmbn):
    """
    Ensure the upper triangle has no missing (profile_id, exp_year, dev_len) cells.
    Missing cells are filled with zero incurred. Lower triangle cells are removed.

    R equivalent: lines ~378-394 in SLU_main_code.R — the anti_join + rbind for
    missing upper-triangle combinations.

    Parameters
    ----------
    actuals_cl : pd.DataFrame
        Raw incremental incurred data with columns
        [profile_id, exp_year, dev_len, Ri_type, Gross_Incurred].
    all_cmbn : pd.DataFrame
        Complete grid from build_all_combinations().

    Returns
    -------
    actuals_cl : pd.DataFrame
        Incurred data with missing upper-triangle cells filled, lower-triangle removed.
        Includes the lower_tri_cmbn column (all zeros since lower tri is removed).
    """
    # Keep only upper triangle from the grid
    upper_grid = all_cmbn[all_cmbn["lower_tri_cmbn"] == 0].copy()

    # Left join actuals onto the grid to find which cells have data
    merge_keys = ["profile_id", "exp_year", "dev_len", "Ri_type"]
    merged = upper_grid[merge_keys + ["lower_tri_cmbn"]].merge(
        actuals_cl, on=merge_keys, how="left"
    )

    # Fill missing incurred values with 0
    merged["Gross_Incurred"] = merged["Gross_Incurred"].fillna(0.0)

    return merged


def create_cumulative(actuals_cl):
    """
    Create cumulative incurred from incremental data (YQ granularity).
    Data must be sorted by (profile_id, exp_year, Ri_type, dev_len) before cumsum.

    R equivalent: lines ~399-401 in SLU_main_code.R — the cumsum grouped by
    profile_id, exp_year, Ri_type.

    Parameters
    ----------
    actuals_cl : pd.DataFrame
        Incremental incurred data.

    Returns
    -------
    actuals_cum : pd.DataFrame
        Same data with an added Cumulative_Gross_Incurred column.
    """
    actuals_cum = actuals_cl.sort_values(
        ["profile_id", "exp_year", "Ri_type", "dev_len"]
    ).copy()

    actuals_cum["Cumulative_Gross_Incurred"] = (
        actuals_cum
        .groupby(["profile_id", "exp_year", "Ri_type"])["Gross_Incurred"]
        .cumsum()
    )

    return actuals_cum


def convert_yq_to_yy(actuals_cl, analysis_qtr):
    """
    Convert quarterly (YQ) incremental data to annual (YY) by aggregating
    dev_len into annual buckets, then recomputing cumulative.

    R equivalent: lines ~412-421 in SLU_main_code.R — the YQ-to-YY conversion
    using dev_year_month calculation and re-aggregation.

    The annual development period anchor depends on the analysis quarter:
      - Q1: dev_year_month = 3 + ceiling((dev_len - 3) / 12) * 12
      - Q2-Q4: dev_year_month = analysis_qtr*3 + floor(dev_len / 12) * 12

    Parameters
    ----------
    actuals_cl : pd.DataFrame
        Quarterly incremental data with [profile_id, exp_year, dev_len,
        Ri_type, lower_tri_cmbn, Gross_Incurred].
    analysis_qtr : int
        The evaluation quarter (1-4).

    Returns
    -------
    actuals_yy : pd.DataFrame
        Annual data with cumulative column added.
    """
    df = actuals_cl.copy()

    # Compute the annual development period bucket
    if analysis_qtr == 1:
        df["dev_len"] = (
            analysis_qtr * 3
            + np.ceil((df["dev_len"] - 3) / 12).astype(int) * 12
        )
    else:
        df["dev_len"] = (
            analysis_qtr * 3
            + (df["dev_len"] // 12).astype(int) * 12
        )

    # Aggregate incremental values into the annual bucket
    group_cols = ["profile_id", "exp_year", "dev_len", "Ri_type", "lower_tri_cmbn"]
    actuals_yy = (
        df.groupby(group_cols, as_index=False)["Gross_Incurred"]
        .sum()
    )

    # Sort and compute cumulative
    actuals_yy = actuals_yy.sort_values(
        ["profile_id", "exp_year", "Ri_type", "dev_len"]
    )
    actuals_yy["Cumulative_Gross_Incurred"] = (
        actuals_yy
        .groupby(["profile_id", "exp_year", "Ri_type", "lower_tri_cmbn"])["Gross_Incurred"]
        .cumsum()
    )

    return actuals_yy.reset_index(drop=True)


def build_triangle_for_profile(actuals_data, profile_id, ri_type, sml_flag, config):
    """
    Build the incremental and cumulative loss triangles for a single profile.

    This is the main triangle-building function called per profile.
    R equivalent: lines ~603-720 in SLU_main_code.R inside run_mbr().

    Parameters
    ----------
    actuals_data : dict
        Must contain keys:
          - "actuals_cum" : pd.DataFrame — YQ cumulative data (for S/M profiles)
          - "actuals_yy"  : pd.DataFrame — YY cumulative data (for L profiles)
          - "actuals_cl"  : pd.DataFrame — YQ incremental data (for S/M profiles)
          - "exp_year_dev_len" : pd.DataFrame — exp_year to max_dev_len mapping
    profile_id : str
        The profile being processed.
    ri_type : str
        Reinsurance type to filter on (e.g., "Gross").
    sml_flag : str
        "S", "M", or "L" — determines YQ vs YY and lookback years.
    config : dict
        Must contain: analysis_year, analysis_qtr, years_analyzed,
        years_analyzed_S_tailed, years_analyzed_M_tailed, years_analyzed_L_tailed,
        years_capped.

    Returns
    -------
    result : dict with keys:
        "triangle_incr"        : pd.DataFrame — incremental triangle (pivot table)
        "triangle_cum"         : pd.DataFrame — cumulative triangle (pivot table)
        "triangle_cum_matrix"  : np.ndarray   — cumulative as a numpy matrix
        "development_index_df" : pd.DataFrame — mapping of index to dev month
        "inc_by_ay"            : pd.DataFrame — total incurred by exposure year
        "exp_year_negative_cum_inc" : pd.DataFrame — years with negative cum incurred
        "last_dev_period_index": int
        "sml_flag"             : str
        "actuals_cum_profile"  : pd.DataFrame — filtered cumulative actuals for this profile
    """
    analysis_year = config["analysis_year"]
    analysis_qtr = config["analysis_qtr"]
    years_analyzed = config["years_analyzed"]
    exp_year_dev_len = actuals_data["exp_year_dev_len"]
    max_non_zero_inc_year = actuals_data.get("max_non_zero_inc_year", {}).get(profile_id, analysis_year)

    # --- Select the right data source and lookback window based on SML ---
    if sml_flag == "L":
        # Long-tailed: use annual (YY) triangles
        actuals_cl = actuals_data["actuals_yy"].copy()
        actuals_cum = actuals_data["actuals_yy"].copy()
        oldest_year = analysis_year - config["years_analyzed_L_tailed"] + 1
        last_dev_period_index = years_analyzed

    elif sml_flag == "S":
        # Short-tailed: use quarterly (YQ) triangles
        actuals_cl = actuals_data["actuals_cl"].copy()
        actuals_cum = actuals_data["actuals_cum"].copy()
        oldest_year = max(
            max_non_zero_inc_year - config["years_analyzed_S_tailed"] + 1,
            analysis_year - config["years_capped"] + 1
        )
        last_dev_period_index = 4 * years_analyzed - (4 - analysis_qtr)

    else:  # sml_flag == "M"
        # Medium-tailed: use quarterly (YQ) triangles
        actuals_cl = actuals_data["actuals_cl"].copy()
        actuals_cum = actuals_data["actuals_cum"].copy()
        oldest_year = max(
            max_non_zero_inc_year - config["years_analyzed_M_tailed"] + 1,
            analysis_year - config["years_capped"] + 1
        )
        last_dev_period_index = 4 * years_analyzed - (4 - analysis_qtr)

    # Filter to this profile and ri_type
    actuals_cl = actuals_cl[
        (actuals_cl["profile_id"] == profile_id) &
        (actuals_cl["Ri_type"] == ri_type)
    ].copy()

    actuals_cum = actuals_cum[
        (actuals_cum["profile_id"] == profile_id) &
        (actuals_cum["Ri_type"] == ri_type)
    ].copy()

    # Zero out years older than the lookback window
    actuals_cl.loc[actuals_cl["exp_year"] < oldest_year, "Gross_Incurred"] = 0.0
    actuals_cum.loc[actuals_cum["exp_year"] < oldest_year, "Gross_Incurred"] = 0.0
    actuals_cum.loc[actuals_cum["exp_year"] < oldest_year, "Cumulative_Gross_Incurred"] = 0.0

    # --- Development index mapping ---
    # Maps sequential index (1, 2, 3...) to actual development months (3, 6, 9... or 9, 21, 33...)
    unique_dev = sorted(actuals_cum["dev_len"].unique())
    development_index_df = pd.DataFrame({
        "development_index": range(1, len(unique_dev) + 1),
        "development_month": unique_dev
    })

    # --- Total incurred by exposure year (used later for RMSE) ---
    inc_by_ay = (
        actuals_cl.groupby("exp_year", as_index=False)["Gross_Incurred"]
        .sum()
    )

    # --- Build incremental triangle as a pivot table ---
    # Rows = exposure years, Columns = development periods, Values = incremental incurred
    triangle_incr = actuals_cl.pivot_table(
        index="exp_year",
        columns="dev_len",
        values="Gross_Incurred",
        aggfunc="sum"
    )
    triangle_incr = triangle_incr.sort_index()

    # --- Build cumulative triangle from incremental ---
    # cumsum across columns (left to right) for each row
    triangle_cum = triangle_incr.cumsum(axis=1)

    # --- Trim cumulative triangle to max observable dev_len per exp_year ---
    # Each exposure year can only observe up to its max_dev_len
    for _, row in exp_year_dev_len.iterrows():
        ey = row["exp_year"]
        max_dl = row["max_dev_len"]
        if ey in triangle_cum.index:
            # Set values beyond max observable to NaN (lower triangle)
            cols_beyond = [c for c in triangle_cum.columns if c > max_dl]
            triangle_cum.loc[ey, cols_beyond] = np.nan

    # --- Remove exposure years with negative cumulative incurred ---
    exp_year_negative_cum_inc = actuals_cum[
        actuals_cum["Cumulative_Gross_Incurred"] < 0
    ]["exp_year"].unique()

    count_years_removed = 0
    if len(exp_year_negative_cum_inc) < years_analyzed:
        # Only remove if not ALL years are negative (edge case protection)
        triangle_cum = triangle_cum.drop(
            index=[y for y in exp_year_negative_cum_inc if y in triangle_cum.index],
            errors="ignore"
        )
        count_years_removed = len(exp_year_negative_cum_inc)

    # --- Convert to numpy matrix for downstream calculations ---
    triangle_cum_matrix = triangle_cum.values.copy()

    return {
        "triangle_incr": triangle_incr,
        "triangle_cum": triangle_cum,
        "triangle_cum_matrix": triangle_cum_matrix,
        "development_index_df": development_index_df,
        "inc_by_ay": inc_by_ay,
        "exp_year_negative_cum_inc": pd.DataFrame({"exp_year": exp_year_negative_cum_inc}),
        "last_dev_period_index": last_dev_period_index,
        "sml_flag": sml_flag,
        "actuals_cum_profile": actuals_cum,
        "exp_year_dev_len": exp_year_dev_len,
        "count_years_removed": count_years_removed,
    }


# ---------------------------------------------------------------------------
# Part 2: Outlier Detection
# ---------------------------------------------------------------------------

def compute_age_to_age_factors(actuals_cum, exp_year_dev_len):
    """
    Compute age-to-age development factors from cumulative incurred data.

    For each row, the factor = Cumulative at (dev_len + 1) / Cumulative at dev_len.
    Invalid values (NA, NaN, Inf, division by zero) are replaced with 1.0.

    R equivalent: first few lines of fn_get_age_to_age_outliers() in
    MBR_weighted_average.R.

    Parameters
    ----------
    actuals_cum : pd.DataFrame
        Must have columns [profile_id, exp_year, dev_len, Ri_type,
        Gross_Incurred, Cumulative_Gross_Incurred].
    exp_year_dev_len : pd.DataFrame
        Mapping of exp_year to max_dev_len (used to exclude last diagonal).

    Returns
    -------
    actuals_cum : pd.DataFrame
        Same data with an added "age_to_age" column.
    """
    df = actuals_cum.copy()

    # Compute the next period's cumulative within each (profile, exp_year, Ri_type)
    df = df.sort_values(["profile_id", "exp_year", "Ri_type", "dev_len"])
    df["next_cum"] = (
        df.groupby(["profile_id", "exp_year", "Ri_type"])["Cumulative_Gross_Incurred"]
        .shift(-1)
    )

    # age_to_age = next cumulative / current cumulative
    # Guard against division by zero
    df["age_to_age"] = np.where(
        df["Cumulative_Gross_Incurred"] != 0,
        df["next_cum"] / df["Cumulative_Gross_Incurred"],
        1.0
    )

    # Replace invalid values (NaN, Inf) with 1.0
    df["age_to_age"] = df["age_to_age"].replace([np.inf, -np.inf], 1.0).fillna(1.0)

    # Remove the last diagonal (where dev_len == max_dev_len for that exp_year)
    # because age-to-age factors cannot be computed for the most recent observation
    df = df.merge(
        exp_year_dev_len.rename(columns={"max_dev_len": "max_dl"}),
        on="exp_year", how="left"
    )
    df = df[df["dev_len"] != df["max_dl"]].copy()
    df = df.drop(columns=["next_cum", "max_dl"])

    return df


def detect_outliers(actuals_cum, exp_year_dev_len, sml_flag, config):
    """
    Detect outlier age-to-age factors using the adjusted boxplot method.

    Uses medcouple (a robust measure of skewness) to compute asymmetric fences:
      Lower fence = Q1 - 3 * exp(-Skewness * |MC|) * IQR
      Upper fence = Q3 + 3 * exp( Skewness *  MC ) * IQR

    This is more appropriate than standard boxplots for LDF data because
    loss development factor distributions are inherently right-skewed.

    R equivalent: fn_get_age_to_age_outliers() in MBR_weighted_average.R.

    Parameters
    ----------
    actuals_cum : pd.DataFrame
        Cumulative incurred data (one profile, filtered).
    exp_year_dev_len : pd.DataFrame
        Mapping of exp_year to max_dev_len.
    sml_flag : str
        "S", "M", or "L".
    config : dict
        Must contain "outlier_detection_min_points" (default 4).

    Returns
    -------
    result : dict with keys:
        "actuals_cum" : pd.DataFrame — data with outlier_flag column (1 = outlier)
        "outlier_detection_last_dev_period_index" : int
    """
    min_points = config.get("outlier_detection_min_points", 4)
    actuals_cum_copy = actuals_cum.copy()

    # --- Step 1: Compute age-to-age factors ---
    df = compute_age_to_age_factors(actuals_cum, exp_year_dev_len)

    # --- Step 2: Remove exposure years with all non-positive incurred ---
    ey_totals = (
        df.groupby(["profile_id", "exp_year"], as_index=False)["Gross_Incurred"]
        .sum()
        .rename(columns={"Gross_Incurred": "Total_Gross_Incurred"})
    )
    ey_non_positive = ey_totals[ey_totals["Total_Gross_Incurred"] <= 0]["exp_year"]
    df = df[~df["exp_year"].isin(ey_non_positive)]

    # --- Step 3: Remove exposure years with negative cumulative incurred ---
    ey_neg_cum = actuals_cum[
        actuals_cum["Cumulative_Gross_Incurred"] < 0
    ]["exp_year"].unique()
    df = df[~df["exp_year"].isin(ey_neg_cum)]

    # --- Step 4: Compute quartiles, IQR, medcouple, and skewness per dev_len ---
    quartile_records = []
    for dev, group in df.groupby("dev_len"):
        values = group["age_to_age"].values

        if len(values) < 2:
            # Not enough data points for meaningful statistics
            quartile_records.append({
                "dev_len": dev, "IQR_value": 0.0,
                "Q1_value": values[0] if len(values) == 1 else 0.0,
                "Q3_value": values[0] if len(values) == 1 else 0.0,
                "MC": 0.0, "Skewness": 0.0
            })
            continue

        q1 = np.percentile(values, 25)
        q3 = np.percentile(values, 75)
        iqr = q3 - q1

        # Medcouple — robust skewness measure
        if medcouple_1d is not None and len(values) >= 3:
            mc = medcouple_1d(values)
        else:
            mc = 0.0

        # Classical skewness
        sk = float(skew(values, bias=True)) if len(values) >= 3 else 0.0

        quartile_records.append({
            "dev_len": dev,
            "IQR_value": iqr,
            "Q1_value": q1,
            "Q3_value": q3,
            "MC": mc,
            "Skewness": sk,
        })

    quartiles_df = pd.DataFrame(quartile_records)

    # --- Step 5: Clip medcouple to [-0.5, 0.5] ---
    quartiles_df["MC"] = quartiles_df["MC"].clip(-0.5, 0.5)

    # --- Step 6: Compute asymmetric outlier fences ---
    # If IQR is non-zero, use the adjusted boxplot formula
    # If IQR is zero (all values identical), use 5% buffer around Q1/Q3
    quartiles_df["Min_Range"] = np.where(
        quartiles_df["IQR_value"] != 0,
        quartiles_df["Q1_value"] - 3 * np.exp(-quartiles_df["Skewness"] * quartiles_df["MC"].abs()) * quartiles_df["IQR_value"],
        0.95 * quartiles_df["Q1_value"]
    )
    quartiles_df["Max_Range"] = np.where(
        quartiles_df["IQR_value"] != 0,
        quartiles_df["Q3_value"] + 3 * np.exp(quartiles_df["Skewness"] * quartiles_df["MC"]) * quartiles_df["IQR_value"],
        1.05 * quartiles_df["Q3_value"]
    )

    # --- Step 7: Determine the last dev period eligible for outlier detection ---
    # Only do outlier detection for dev periods with at least min_points data points
    dev_len_counts = (
        df.groupby("dev_len", as_index=False)
        .size()
        .rename(columns={"size": "count"})
    )
    eligible_devs = dev_len_counts[dev_len_counts["count"] == min_points]

    if len(eligible_devs) >= 1:
        outlier_detection_last_dev_month = eligible_devs["dev_len"].max()
    else:
        outlier_detection_last_dev_month = actuals_cum_copy["dev_len"].min()

    # Restrict outlier detection to dev periods up to this cutoff
    quartiles_df = quartiles_df[quartiles_df["dev_len"] <= outlier_detection_last_dev_month]

    # --- Step 8: Join fence values and flag outliers ---
    df = df.merge(quartiles_df[["dev_len", "Min_Range", "Max_Range", "IQR_value",
                                 "Q1_value", "Q3_value"]],
                  on="dev_len", how="left")

    df["outlier_flag"] = np.where(
        (df["age_to_age"] < df["Min_Range"]) | (df["age_to_age"] > df["Max_Range"]),
        1, 0
    )

    # For dev periods beyond the outlier detection range, flag = 0 (not checked)
    df["outlier_flag"] = df["outlier_flag"].fillna(0).astype(int)

    # --- Step 9: Compute the period index ---
    if sml_flag == "L":
        # For long-tailed, find the row index in exp_year_dev_len where
        # max_dev_len matches the outlier detection cutoff
        match = exp_year_dev_len[
            exp_year_dev_len["max_dev_len"] == outlier_detection_last_dev_month
        ]
        if len(match) > 0:
            # +1 because R is 1-indexed; Python index is already 0-based,
            # but the R code uses which() which returns 1-based, and downstream
            # code expects the 1-based index
            outlier_detection_last_dev_period_index = match.index[0] + 1
        else:
            outlier_detection_last_dev_period_index = 1
    else:
        # For S/M, dev periods are quarterly (3, 6, 9, ...), so index = dev_month / 3
        outlier_detection_last_dev_period_index = outlier_detection_last_dev_month // 3

    return {
        "actuals_cum": df,
        "outlier_detection_last_dev_period_index": outlier_detection_last_dev_period_index,
    }


# ---------------------------------------------------------------------------
# Part 3: Helper — Compute max non-zero incurred year per profile
# ---------------------------------------------------------------------------

def compute_max_non_zero_inc_year(actuals_all_profiles, analysis_year):
    """
    For each (profile_id, Ri_type), find the most recent exposure year
    with non-zero incurred. Profiles with ALL zero incurred default to
    the analysis year.

    R equivalent: lines ~552-576 in SLU_main_code.R (Latest_Ay calculation).

    Parameters
    ----------
    actuals_all_profiles : pd.DataFrame
        Columns: [profile_id, exp_year, dev_len, Ri_type, Gross_Incurred].
    analysis_year : int

    Returns
    -------
    latest_ay : dict
        Keyed by profile_id, value is the max non-zero incurred year.
    """
    # Sum incurred by profile + exposure year
    ay_totals = (
        actuals_all_profiles
        .groupby(["profile_id", "exp_year", "Ri_type"], as_index=False)["Gross_Incurred"]
        .sum()
    )
    ay_totals["is_nonzero"] = (ay_totals["Gross_Incurred"] != 0).astype(int)

    # Check which profiles have at least one non-zero year
    profile_nonzero_count = (
        ay_totals.groupby(["profile_id", "Ri_type"], as_index=False)["is_nonzero"]
        .sum()
        .rename(columns={"is_nonzero": "nonzero_count"})
    )

    # For profiles with non-zero years: take the max such year
    nonzero_years = ay_totals[ay_totals["is_nonzero"] == 1]
    max_year_nonzero = (
        nonzero_years.groupby(["profile_id", "Ri_type"], as_index=False)["exp_year"]
        .max()
        .rename(columns={"exp_year": "max_non_zero_inc_year"})
    )

    # For profiles with ALL zero years: default to analysis_year
    all_zero_profiles = profile_nonzero_count[profile_nonzero_count["nonzero_count"] == 0]
    all_zero_profiles = all_zero_profiles[["profile_id", "Ri_type"]].copy()
    all_zero_profiles["max_non_zero_inc_year"] = analysis_year

    # Combine
    result_df = pd.concat([max_year_nonzero, all_zero_profiles], ignore_index=True)

    # Convert to a simple dict keyed by profile_id (using Gross Ri_type values)
    gross_rows = result_df[result_df["Ri_type"] == "Gross"]
    return dict(zip(gross_rows["profile_id"], gross_rows["max_non_zero_inc_year"]))
