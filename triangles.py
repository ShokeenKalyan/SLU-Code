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
# Part 1B: All-Profiles Pre-Processing (R Chunks 1–4)
# ---------------------------------------------------------------------------

def prepare_all_profiles_triangles(raw_data, vena_transform_module, config):
    """
    Build incurred & paid triangles for ALL profiles at once, then do SML
    classification and profile filtering. This matches R Chunks 1–4 (lines 1–584).

    In R, this work happens BEFORE the per-profile run_mbr() loop:
      1. Transform raw incurred/paid data
      2. Inner join with profile_mapping to keep only active profiles
      3. Build complete grid (profile × exp_year × dev_len)
      4. Fill missing upper-triangle cells with zero
      5. Compute cumulative (YQ) and convert to YY
      6. Same for paid
      7. SML classification
      8. Filter out profiles with <5 years of non-zero data
      9. Compute max non-zero incurred year per profile

    Parameters
    ----------
    raw_data : dict
        Output of data_reader.load_all_data(). Keys: 'incurred_raw', 'paid_raw',
        'vena_data_extract_raw', 'method_raw_extract', 'profile_mapping', etc.
    vena_transform_module : module
        The vena_transform module (passed to avoid circular imports).
    config : dict
        Pipeline configuration from config.load_config().

    Returns
    -------
    all_profiles_data : dict with keys:
        "actuals_cum"         : pd.DataFrame — YQ cumulative incurred, all profiles
        "actuals_yy"          : pd.DataFrame — YY cumulative incurred, all profiles
        "actuals_cl"          : pd.DataFrame — YQ incremental incurred (with lower_tri_cmbn)
        "paid_yq_cum"         : pd.DataFrame — YQ cumulative paid, all profiles
        "paid_yy"             : pd.DataFrame — YY cumulative paid, all profiles
        "exp_year_dev_len"    : pd.DataFrame — exp_year to max_dev_len mapping
        "max_non_zero_inc_year" : dict — profile_id → latest year with non-zero incurred
        "sml_mapping"         : pd.DataFrame — profile_id → SML_flag
        "profile_list"        : list — profile IDs that passed all filters
        "inputs_vena_all_profiles" : pd.DataFrame — Vena assumptions joined with profile_mapping
        "inputs_vena_method_names" : pd.DataFrame — Vena method names joined with profile_mapping
        "vena_ldf"            : pd.DataFrame — Vena LDF data
        "actuals_cum_df"      : pd.DataFrame — diagnostic DF for SQL export
        "paid_yq_cum_df"      : pd.DataFrame — diagnostic DF for SQL export
    """
    analysis_year = config["analysis_year"]
    analysis_qtr = config["analysis_qtr"]
    analysis_val_flag = config["analysis_val_flag"]
    years_analyzed = config["years_analyzed"]
    ri_type_run = config["ri_type_run"]

    profile_mapping = raw_data["profile_mapping"]
    id_col = "profile_id" if "profile_id" in profile_mapping.columns else "Profile_ID"

    # =================================================================
    # STEP 1: Transform incurred data and join with profile_mapping
    # R: lines 156–167 — fn_to_transform_incurred_paid + inner_join
    # =================================================================
    incurred_tri_data = vena_transform_module.transform_incurred_paid(
        raw_data["incurred_raw"],
        res_year=analysis_year,
        res_qtr=analysis_qtr,
        val_flag=analysis_val_flag,
        vector_name="Incurred Loss"
    )

    # Inner join with profile_mapping — keeps only active profiles
    # R: actuals_all_profiles = inner_join(incurred_tri_data, profile_mapping)
    actuals_all_profiles = incurred_tri_data.merge(
        profile_mapping[[id_col, "res_year", "res_qtr", "val_flag"]],
        left_on=["Product", "res_year", "res_qtr", "val_flag"],
        right_on=[id_col, "res_year", "res_qtr", "val_flag"],
        how="inner"
    )

    # Rename to standard column names
    actuals_all_profiles = actuals_all_profiles.rename(columns={
        "Product": "profile_id",
        "Exposure Year": "exp_year",
        "Development Period": "dev_len",
        "Measure": "Ri_type",
        "Value": "Gross_Incurred",
    })
    actuals_all_profiles = actuals_all_profiles[
        ["profile_id", "exp_year", "dev_len", "Ri_type", "Gross_Incurred"]
    ].copy()

    # Filter to relevant years and cast types
    actuals_all_profiles["exp_year"] = pd.to_numeric(actuals_all_profiles["exp_year"])
    actuals_all_profiles["dev_len"] = pd.to_numeric(actuals_all_profiles["dev_len"])
    actuals_all_profiles = actuals_all_profiles[
        actuals_all_profiles["exp_year"] >= (analysis_year - years_analyzed + 1)
    ].copy()

    # =================================================================
    # STEP 2: Transform Vena all-vector data
    # R: lines 182–203 — fn_to_transform_vena_all_data + inner_join
    # =================================================================
    vena_all_profile_data = vena_transform_module.transform_vena_all_data(
        raw_data["vena_data_extract_raw"],
        res_year=analysis_year,
        analysis_qtr=analysis_qtr,
        analysis_val_flag=analysis_val_flag,
        years_analyzed=years_analyzed
    )

    inputs_vena_all_profiles = pd.DataFrame(vena_all_profile_data[0]) if isinstance(vena_all_profile_data, (list, tuple)) else vena_all_profile_data.get("inputs", pd.DataFrame())
    vena_ldf = vena_all_profile_data[1] if isinstance(vena_all_profile_data, (list, tuple)) else vena_all_profile_data.get("ldf", pd.DataFrame())

    # Compute Financial Budget LR (Att)
    if "Budget EP FY" in inputs_vena_all_profiles.columns and "Financial Budget Loss" in inputs_vena_all_profiles.columns:
        inputs_vena_all_profiles["Financial Budget LR (Att)"] = np.where(
            inputs_vena_all_profiles["Budget EP FY"] == 0, 0,
            inputs_vena_all_profiles["Financial Budget Loss"] / inputs_vena_all_profiles["Budget EP FY"]
        )
        inputs_vena_all_profiles = inputs_vena_all_profiles.drop(
            columns=["Financial Budget Loss", "Budget EP FY"], errors="ignore"
        )

    # Inner join with profile_mapping
    if "Product" in inputs_vena_all_profiles.columns:
        pre_join_cols = list(inputs_vena_all_profiles.columns)
        inputs_vena_all_profiles = inputs_vena_all_profiles.merge(
            profile_mapping[[id_col, "res_year", "res_qtr", "val_flag"]],
            left_on=["Product", "res_year", "res_qtr", "val_flag"],
            right_on=[id_col, "res_year", "res_qtr", "val_flag"],
            how="inner"
        )
        inputs_vena_all_profiles = inputs_vena_all_profiles[
            [c for c in pre_join_cols if c in inputs_vena_all_profiles.columns]
        ].copy()
        if "Exposure Year" in inputs_vena_all_profiles.columns:
            inputs_vena_all_profiles["Exposure Year"] = pd.to_numeric(
                inputs_vena_all_profiles["Exposure Year"], errors="coerce"
            )
        if "Development Period" in inputs_vena_all_profiles.columns:
            inputs_vena_all_profiles["Development Period"] = pd.to_numeric(
                inputs_vena_all_profiles["Development Period"], errors="coerce"
            )

    # =================================================================
    # STEP 3: Transform Vena method name data
    # R: lines 222–228 — fn_to_transform_method_data + inner_join
    # =================================================================
    vena_method_data = vena_transform_module.transform_method_data(
        raw_data["method_raw_extract"],
        res_year=analysis_year,
        res_qtr=analysis_qtr,
        val_flag=analysis_val_flag,
        Ri_type_run=ri_type_run
    )

    inputs_vena_method_names = pd.DataFrame()
    if isinstance(vena_method_data, pd.DataFrame) and "Product" in vena_method_data.columns:
        pre_join_cols = list(vena_method_data.columns)
        inputs_vena_method_names = vena_method_data.merge(
            profile_mapping[[id_col, "res_year", "res_qtr", "val_flag"]],
            left_on=["Product", "res_year", "res_qtr", "val_flag"],
            right_on=[id_col, "res_year", "res_qtr", "val_flag"],
            how="inner"
        )
        inputs_vena_method_names = inputs_vena_method_names[
            [c for c in pre_join_cols if c in inputs_vena_method_names.columns]
        ].copy()
        if "Exposure Year" in inputs_vena_method_names.columns:
            inputs_vena_method_names["Exposure Year"] = pd.to_numeric(
                inputs_vena_method_names["Exposure Year"], errors="coerce"
            )
        if "Development Period" in inputs_vena_method_names.columns:
            inputs_vena_method_names["Development Period"] = pd.to_numeric(
                inputs_vena_method_names["Development Period"], errors="coerce"
            )

    # =================================================================
    # STEP 4: Build all-profiles incurred triangle (grid + fill + cumulative + YY)
    # R: lines 343–426
    # =================================================================
    profile_ids = sorted(actuals_all_profiles["profile_id"].unique().tolist())
    ri_types = actuals_all_profiles["Ri_type"].unique().tolist()

    all_cmbn, exp_year_dev_len = build_all_combinations(
        profile_ids, analysis_year, analysis_qtr, years_analyzed, ri_types
    )

    actuals_cl = fill_missing_upper_triangle(actuals_all_profiles, all_cmbn)
    actuals_cum = create_cumulative(actuals_cl)

    # Diagnostic DF for SQL export (R: actuals_cum_df, line 406)
    actuals_cum_df = actuals_cum.copy()
    actuals_cum_df["res_year"] = analysis_year
    actuals_cum_df["res_qtr"] = analysis_qtr
    actuals_cum_df["val_flag"] = analysis_val_flag

    # YY conversion for long-tailed profiles (R: lines 411-426)
    actuals_yy = convert_yq_to_yy(actuals_cl, analysis_qtr)

    # =================================================================
    # STEP 5: Build all-profiles paid triangle (same process)
    # R: lines 296–461
    # =================================================================
    paid_tri_data = vena_transform_module.transform_incurred_paid(
        raw_data["paid_raw"],
        res_year=analysis_year,
        res_qtr=analysis_qtr,
        val_flag=analysis_val_flag,
        vector_name="Paid Loss"
    )

    paid_all_profiles = paid_tri_data.merge(
        profile_mapping[[id_col, "res_year", "res_qtr", "val_flag"]],
        left_on=["Product", "res_year", "res_qtr", "val_flag"],
        right_on=[id_col, "res_year", "res_qtr", "val_flag"],
        how="inner"
    )
    paid_all_profiles = paid_all_profiles.rename(columns={
        "Product": "profile_id",
        "Exposure Year": "exp_year",
        "Development Period": "dev_len",
        "Measure": "Ri_type",
        "Value": "Gross_Paid",
    })
    paid_all_profiles = paid_all_profiles[
        ["profile_id", "exp_year", "dev_len", "Ri_type", "Gross_Paid"]
    ].copy()
    paid_all_profiles["exp_year"] = pd.to_numeric(paid_all_profiles["exp_year"])
    paid_all_profiles["dev_len"] = pd.to_numeric(paid_all_profiles["dev_len"])

    # Use incurred grid to fill missing paid combos (R: lines 432-436)
    paid_grid = actuals_cl[["profile_id", "exp_year", "dev_len", "Ri_type", "lower_tri_cmbn"]].copy()
    paid_yq = paid_grid.merge(paid_all_profiles, on=["profile_id", "exp_year", "dev_len", "Ri_type"], how="left")
    paid_yq["Gross_Paid"] = paid_yq["Gross_Paid"].fillna(0.0)

    # Cumulative paid (R: lines 438-444)
    paid_yq = paid_yq.sort_values(["profile_id", "exp_year", "Ri_type", "dev_len"])
    paid_yq_cum = paid_yq.copy()
    paid_yq_cum["Cumulative_Gross_Paid"] = (
        paid_yq_cum.groupby(["profile_id", "exp_year", "Ri_type"])["Gross_Paid"].cumsum()
    )

    # Diagnostic DF for SQL export (R: paid_yq_cum_df, line 443)
    paid_yq_cum_df = paid_yq_cum.copy()
    paid_yq_cum_df["res_year"] = analysis_year
    paid_yq_cum_df["res_qtr"] = analysis_qtr
    paid_yq_cum_df["val_flag"] = analysis_val_flag

    # YY paid (R: lines 447-460)
    paid_yy = paid_yq.copy()
    if analysis_qtr == 1:
        paid_yy["dev_len"] = (
            analysis_qtr * 3
            + np.ceil((paid_yy["dev_len"] - 3) / 12).astype(int) * 12
        )
    else:
        paid_yy["dev_len"] = (
            analysis_qtr * 3
            + (paid_yy["dev_len"] // 12).astype(int) * 12
        )
    paid_yy = (
        paid_yy
        .groupby(["profile_id", "exp_year", "dev_len", "Ri_type", "lower_tri_cmbn"], as_index=False)["Gross_Paid"]
        .sum()
    )
    paid_yy = paid_yy.sort_values(["profile_id", "exp_year", "Ri_type", "dev_len"])
    paid_yy["Cumulative_Gross_Paid"] = (
        paid_yy.groupby(["profile_id", "exp_year", "Ri_type", "lower_tri_cmbn"])["Gross_Paid"].cumsum()
    )

    # =================================================================
    # STEP 6: SML classification (R Chunk 2, lines 467-531)
    # =================================================================
    from data_reader import load_sml_mapping
    sml_mapping = load_sml_mapping(config)

    # =================================================================
    # STEP 7: Profile filtering — remove profiles with <5 non-zero years
    # R Chunk 3, lines 535-548
    # =================================================================
    eligible_profiles = filter_profiles_by_data(
        actuals_cl, sml_mapping, config
    )

    # =================================================================
    # STEP 8: Max non-zero incurred year per profile (R Chunk 4, lines 551-576)
    # =================================================================
    max_non_zero = compute_max_non_zero_inc_year(actuals_all_profiles, analysis_year)

    # Final profile list = profiles that passed filtering AND are in profile_mapping
    profile_list = [p for p in eligible_profiles if p in profile_ids]

    return {
        "actuals_cum": actuals_cum,
        "actuals_yy": actuals_yy,
        "actuals_cl": actuals_cl,
        "paid_yq_cum": paid_yq_cum,
        "paid_yy": paid_yy,
        "exp_year_dev_len": exp_year_dev_len,
        "max_non_zero_inc_year": max_non_zero,
        "sml_mapping": sml_mapping,
        "profile_list": profile_list,
        "inputs_vena_all_profiles": inputs_vena_all_profiles,
        "inputs_vena_method_names": inputs_vena_method_names,
        "vena_ldf": vena_ldf,
        "actuals_cum_df": actuals_cum_df,
        "paid_yq_cum_df": paid_yq_cum_df,
    }


def filter_profiles_by_data(actuals_cl, sml_mapping, config):
    """
    Remove profiles with fewer than 5 years of non-zero incurred data.
    Only considers years within each profile's SML lookback window.

    R equivalent: Chunk 3 (lines 535–548) of SLU_main_code.R.

    Parameters
    ----------
    actuals_cl : pd.DataFrame
        Incremental incurred data (all profiles).
    sml_mapping : pd.DataFrame
        Must have columns [profile_id, SML_flag].
    config : dict

    Returns
    -------
    list : Profile IDs that passed the filter (>= 5 non-zero years).
    """
    analysis_year = config["analysis_year"]
    years_S = config["years_analyzed_S"]
    years_M = config["years_analyzed_M"]

    # Sum incurred by (profile, exp_year, Ri_type)
    by_ey = (
        actuals_cl
        .groupby(["profile_id", "exp_year", "Ri_type"], as_index=False)["Gross_Incurred"]
        .sum()
    )

    # Join SML flag
    if "profile_id" in sml_mapping.columns and "SML_flag" in sml_mapping.columns:
        by_ey = by_ey.merge(
            sml_mapping[["profile_id", "SML_flag"]], on="profile_id", how="left"
        )
    else:
        by_ey["SML_flag"] = "M"

    by_ey["SML_flag"] = by_ey["SML_flag"].fillna("M")

    # Filter to each SML's lookback window
    # R: SML_flag=='S' & exp_year >= (analysis_year - years_analyzed_S + 1)
    #  | SML_flag=='M' & exp_year >= (analysis_year - years_analyzed_M + 1)
    mask_s = (by_ey["SML_flag"] == "S") & (by_ey["exp_year"] >= analysis_year - years_S + 1)
    mask_m = (by_ey["SML_flag"] == "M") & (by_ey["exp_year"] >= analysis_year - years_M + 1)
    mask_l = (by_ey["SML_flag"] == "L")
    filtered = by_ey[mask_s | mask_m | mask_l].copy()

    # Keep only non-zero years
    filtered = filtered[filtered["Gross_Incurred"] != 0]

    # Count non-zero years per profile
    year_counts = (
        filtered
        .groupby(["profile_id", "SML_flag", "Ri_type"], as_index=False)
        .agg(year_count=("exp_year", "count"))
    )

    # Keep profiles with >= 5 non-zero years
    eligible = year_counts[year_counts["year_count"] >= 5]
    return sorted(eligible["profile_id"].unique().tolist())


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
