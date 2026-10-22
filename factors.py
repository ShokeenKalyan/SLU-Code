"""
factors.py — Factor indexes and tail factor computation.

Combines three R source files:
  - MBR_factor_one_index.R          → get_factor_one_index()
  - MBR_factor_less_than_one_index.R → get_factor_less_than_one_index(),
                                       get_proportion_less_than_one(),
                                       get_default_last_index_less_than_one()
  - MBR_tail_factor_methods.R       → compute_tail_factor_experience(),
                                       compute_tail_factor_ncci()
"""

import numpy as np
import pandas as pd


# =============================================================================
# Factor-One Index
# R source: MBR_factor_one_index.R → fn_get_end_triangle_index()
# =============================================================================

def get_factor_one_index(profile_id, sml_flag, actuals_df, last_dev_period_index,
                         factor_1_index_threshold, consecutive_less_than_one_num,
                         analysis_year, analysis_qtr, analysis_val_flag):
    """
    Find the earliest development period where loss development effectively ends.

    We calculate the proportion of absolute incremental incurred that lies beyond
    each development period. The "end index" is the first period where that
    proportion drops below a threshold AND no later period exceeds 1% of total
    incurred. This tells us: beyond this point, no meaningful development remains.

    R equivalent: fn_get_end_triangle_index()

    Parameters
    ----------
    profile_id : str
        The profile being analyzed.
    sml_flag : str
        'S', 'M', or 'L' — Short / Medium / Long tail classification.
    actuals_df : pd.DataFrame
        Incremental incurred data with columns ['dev_len', 'Gross_Incurred'].
        Already filtered to the current profile.
    last_dev_period_index : int
        The last development period index in the triangle.
    factor_1_index_threshold : float
        Percentage threshold (e.g. 0.5 means 0.5% of total incurred).
    consecutive_less_than_one_num : int
        Minimum allowed value for the end index (floor).
    analysis_year : int
        Current analysis/reservation year.
    analysis_qtr : int
        Current analysis/reservation quarter.
    analysis_val_flag : str
        Current analysis valuation flag.

    Returns
    -------
    dict with:
        'dev_prop_inc_df' : pd.DataFrame — diagnostic table of proportions per dev period
        'end_index'       : int          — the factor-one index
    """
    # Take absolute values of incurred (some periods can have negative development)
    dev_inc_df = actuals_df.copy()
    dev_inc_df["Gross_Incurred"] = dev_inc_df["Gross_Incurred"].abs()

    # Sum absolute incurred by development period
    dev_inc_df = dev_inc_df.groupby("dev_len", as_index=False)["Gross_Incurred"].sum()

    total_inc = dev_inc_df["Gross_Incurred"].sum()

    # -----------------------------------------------------------------
    # For each development period, compute the sum of incurred in ALL
    # later periods. This is a self-join where dev_len.x < dev_len.y,
    # then group by dev_len.x and sum the Gross_Incurred.y values.
    # -----------------------------------------------------------------
    dev_lens = dev_inc_df["dev_len"].values
    incurred = dev_inc_df["Gross_Incurred"].values

    rows = []
    for i, dl in enumerate(dev_lens):
        # Sum of incurred for all periods strictly after this one
        ahead_mask = dev_lens > dl
        gross_ahead = incurred[ahead_mask].sum()
        rows.append({"dev_len": dl, "Gross_Incurred_ahead": gross_ahead})

    temp_df = pd.DataFrame(rows)

    # Proportion of total incurred that lies beyond each period
    if total_inc != 0:
        temp_df["Prop_Total_Inc"] = temp_df["Gross_Incurred_ahead"] / total_inc
    else:
        temp_df["Prop_Total_Inc"] = 0.0

    # Flag periods where proportion <= threshold (development has ended)
    temp_df["dev_less_than_1"] = np.where(
        temp_df["Prop_Total_Inc"] * 100 <= factor_1_index_threshold, 1, 0
    )

    # Flag periods where absolute proportion > 1% (still significant development)
    temp_df["dev_greater_than_1"] = np.where(
        temp_df["Prop_Total_Inc"].abs() * 100 > 1, 1, 0
    )

    # Build the diagnostic output DataFrame
    dev_prop_inc_df = temp_df.copy()
    dev_prop_inc_df["res_year"] = analysis_year
    dev_prop_inc_df["res_qtr"] = analysis_qtr
    dev_prop_inc_df["val_flag"] = analysis_val_flag
    dev_prop_inc_df["profile_id"] = profile_id
    dev_prop_inc_df = dev_prop_inc_df[
        ["res_year", "res_qtr", "val_flag", "profile_id", "dev_len",
         "Gross_Incurred_ahead", "Prop_Total_Inc", "dev_less_than_1", "dev_greater_than_1"]
    ]

    # -----------------------------------------------------------------
    # Determine the end index:
    #   - First period where dev_less_than_1 == 1
    #   - Fall back to last_dev_period_index if none found
    #   - Enforce minimum of consecutive_less_than_one_num
    # -----------------------------------------------------------------
    below_threshold = temp_df[temp_df["dev_less_than_1"] == 1]

    if len(below_threshold) >= 1:
        # R's which.max returns the index of the first TRUE (first 1)
        # Since dev_less_than_1 is 0/1, which.max finds the first 1
        end_index = below_threshold.index[0]
        # Convert from DataFrame row index to a 1-based positional index
        # matching R's behavior (which.max returns position in the vector)
        end_index = temp_df.index.get_loc(below_threshold.index[0]) + 1  # 1-based
    else:
        end_index = last_dev_period_index

    # Enforce minimum floor
    if end_index < consecutive_less_than_one_num:
        end_index = consecutive_less_than_one_num

    return {"dev_prop_inc_df": dev_prop_inc_df, "end_index": end_index}


# =============================================================================
# Factor Less-Than-One Index
# R source: MBR_factor_less_than_one_index.R → fn_get_less_than_one_factors_index()
# =============================================================================

def get_factor_less_than_one_index(ldfs, consecutive_less_than_one_num, index_cons_1):
    """
    Find the first stretch of N consecutive LDFs that are all below 1.0.

    When loss development factors drop below 1.0, it means claims are shrinking
    (e.g., due to salvage or subrogation recoveries). This function finds where
    that pattern first appears consistently.

    R equivalent: fn_get_less_than_one_factors_index()

    Parameters
    ----------
    ldfs : array-like
        Vector of LDF values (1-based indexing in R, converted here to 0-based).
    consecutive_less_than_one_num : int
        Number of consecutive factors < 1.0 required (e.g. 5).
    index_cons_1 : int
        The factor-one index — upper bound for the search (1-based, as from R).

    Returns
    -------
    int
        The 1-based starting index of the first consecutive run of < 1.0 factors.
        Returns 0 if no such run exists.
    """
    x = np.array(ldfs, dtype=float)
    n = consecutive_less_than_one_num

    # R loop: for i in 1:(index_cons_1 - n + 1)
    # R is 1-based; we iterate 0-based in Python
    search_limit = index_cons_1 - n  # 0-based upper bound (inclusive)

    consecutive_flag = False
    consecutive_index = 0

    for i in range(search_limit):
        # Check if all n consecutive values starting at i are < 1.0
        found = True
        for j in range(i, i + n):
            if x[j] >= 1.0:
                found = False
                break

        if found:
            consecutive_flag = True
            consecutive_index = i + 1  # Return 1-based index to match R
            break

    if not consecutive_flag:
        consecutive_index = 0

    return consecutive_index


# =============================================================================
# Proportion of Less-Than-One Factors
# R source: MBR_factor_less_than_one_index.R → fn_get_prop_less_than_one_factors()
# =============================================================================

def get_proportion_less_than_one(ldfs, index_cons_1):
    """
    Compute the proportion of LDFs that are below 1.0 in the range from the
    first period up to (but not including) the factor-one index.

    R equivalent: fn_get_prop_less_than_one_factors()

    Parameters
    ----------
    ldfs : array-like
        Vector of LDF values.
    index_cons_1 : int
        Factor-one index (1-based).

    Returns
    -------
    float
        Proportion of factors < 1.0 in the range [0, index_cons_1-1) (0-based).
    """
    x = np.array(ldfs, dtype=float)

    # R: temp_df = x[1:(index_cons_1-1)]  → elements 1 through index_cons_1-1 (1-based)
    # Python 0-based: elements 0 through index_cons_1-2 (inclusive)
    subset = x[0 : index_cons_1 - 1]

    if len(subset) == 0:
        return 0.0

    count_below_one = np.sum(subset < 1.0)
    return count_below_one / len(subset)


# =============================================================================
# Default Last Index for Less-Than-One Factors
# R source: MBR_factor_less_than_one_index.R → fn_get_default_last_index_less_than_one_factors()
# =============================================================================

def get_default_last_index_less_than_one(ldfs, index_cons_1, incr_pct_change_threshold):
    """
    Look for pairs of consecutive LDFs that are both < 1.0 where the incremental
    percentage change exceeds a threshold. This identifies periods with significant
    negative development that should be flagged.

    R equivalent: fn_get_default_last_index_less_than_one_factors()

    Parameters
    ----------
    ldfs : array-like
        Vector of LDF values.
    index_cons_1 : int
        Factor-one index (1-based).
    incr_pct_change_threshold : float
        Threshold for incremental percentage change (e.g. 0.05 = 5%).

    Returns
    -------
    dict with:
        'default_last_index' : int  — 1-based index of first flagged point
        'incr_pct_change_grt_than_threshold' : bool — whether any point exceeds threshold
    """
    x = np.array(ldfs, dtype=float)

    # Build a DataFrame mirroring the R logic
    x_df = pd.DataFrame({"x": x})

    # Lag: previous value (first element has no lag, default to 1.0)
    x_df["lag_x"] = x_df["x"].shift(1).fillna(1.0)

    # Incremental percentage change: x/lag_x - 1
    # Handle division by zero: if lag_x == 0, set change to 0
    x_df["incr_pct_change"] = np.where(
        x_df["lag_x"] == 0, 0.0, x_df["x"] / x_df["lag_x"] - 1.0
    )

    # A "valid point" is where both current and previous are < 1.0
    # AND the incremental % change <= -threshold (i.e., a significant drop)
    x_df["valid_point"] = np.where(
        (x_df["x"] < 1.0) &
        (x_df["lag_x"] < 1.0) &
        (x_df["incr_pct_change"] <= -incr_pct_change_threshold),
        1, 0
    )

    # Check if any valid_point exists in range [1, index_cons_1-2] (0-based)
    # R: x_df$valid_point_threshold[2:(index_cons_1-1)]  → rows 2..index_cons_1-1 (1-based)
    check_range = x_df["valid_point"].iloc[1 : index_cons_1 - 1]
    incr_pct_change_grt_than_threshold = bool((check_range == 1).any())

    # Default last index: position of the first valid_point == 1
    # R: ifelse(any(valid_point==1), which.max(valid_point), index_cons_1)
    if (x_df["valid_point"] == 1).any():
        default_last_index = x_df["valid_point"].idxmax() + 1  # Convert to 1-based
    else:
        default_last_index = index_cons_1

    return {
        "default_last_index": default_last_index,
        "incr_pct_change_grt_than_threshold": incr_pct_change_grt_than_threshold,
    }


# =============================================================================
# Tail Factor — Experience Method
# R source: MBR_tail_factor_methods.R → fn_tail_factor_experience_method()
# =============================================================================

def compute_tail_factor_experience(initial_selected_incr_ldfs, factor_1_index,
                                   outlier_detection_last_dev_period_index):
    """
    Compute the tail factor using the experience method.

    The tail factor captures development beyond the observed triangle. It is
    the product of all incremental LDFs from the factor-one index through the
    last available period. If the triangle already covers full development
    (outlier_detection_last_dev_period_index <= factor_1_index), the tail is 1.0.

    R equivalent: fn_tail_factor_experience_method()

    Parameters
    ----------
    initial_selected_incr_ldfs : array-like
        Vector or single-column DataFrame of selected incremental LDFs.
    factor_1_index : int
        1-based index where LDFs stabilize at 1.0.
    outlier_detection_last_dev_period_index : int
        1-based index of the last dev period used in outlier detection.

    Returns
    -------
    float
        The tail factor (always >= 1.0 in practice, but this function returns
        the raw product).
    """
    ldfs = np.array(initial_selected_incr_ldfs, dtype=float).flatten()

    if outlier_detection_last_dev_period_index > factor_1_index:
        # R is 1-based: ldfs[factor_1_index:outlier_detection_last_dev_period_index]
        # Python 0-based: ldfs[factor_1_index-1 : outlier_detection_last_dev_period_index]
        tail_slice = ldfs[factor_1_index - 1 : outlier_detection_last_dev_period_index]
        tail_factor = np.prod(tail_slice)
    else:
        tail_factor = 1.0

    return tail_factor


# =============================================================================
# Tail Factor — NCCI Method
# R source: MBR_tail_factor_methods.R → fn_tail_factor_NCCI_method()
# =============================================================================

def compute_tail_factor_ncci(cumulative_incurred_df, factor_1_index, factor_1_dev_month):
    """
    Compute the tail factor using the NCCI method.

    This method estimates future incremental development beyond the observed
    triangle by looking at how prior accident years developed past the
    factor-one development month, then scaling by a growth factor.

    Tail = 1 + (estimated_future_incremental / current_cumulative)

    R equivalent: fn_tail_factor_NCCI_method()

    Parameters
    ----------
    cumulative_incurred_df : pd.DataFrame
        Must have columns: ['exp_year', 'dev_len', 'Gross_Incurred',
        'Cumulative_Gross_Incurred'].
    factor_1_index : int
        The factor-one index (1-based).
    factor_1_dev_month : int
        The development month corresponding to the factor-one index.

    Returns
    -------
    float
        The NCCI tail factor.
    """
    df = cumulative_incurred_df.copy()
    df = df.sort_values("exp_year").reset_index(drop=True)

    # Step 1: Filter to the factor-one development month
    data_filtered = df[df["dev_len"] == factor_1_dev_month].copy()

    if data_filtered.empty:
        return 1.0

    # Incremental incurred for the most recent exposure year at the factor-one dev month
    max_year_idx = data_filtered["exp_year"].idxmax()
    incr_dev = data_filtered.loc[max_year_idx, "Gross_Incurred"]

    # Step 2: Growth factor — ratio of average cumulative incurred of all prior years
    # to the cumulative incurred of the most recent year
    max_exp_year = data_filtered["exp_year"].max()
    prior_years = data_filtered[data_filtered["exp_year"] != max_exp_year]

    if prior_years.empty or data_filtered.loc[max_year_idx, "Cumulative_Gross_Incurred"] == 0:
        return 1.0

    growth_factor = (
        prior_years["Cumulative_Gross_Incurred"].mean()
        / data_filtered.loc[max_year_idx, "Cumulative_Gross_Incurred"]
    )

    # Step 3: Incremental development of prior accident years beyond factor-one dev month
    max_year_at_f1 = df.loc[
        df["dev_len"] == factor_1_dev_month, "exp_year"
    ].max()

    data_filtered_2 = df[
        (df["exp_year"] < max_year_at_f1) & (df["dev_len"] > factor_1_dev_month)
    ].copy()

    # Keep only the latest dev_len per exposure year
    if not data_filtered_2.empty:
        idx = data_filtered_2.groupby("exp_year")["dev_len"].idxmax()
        data_filtered_2 = data_filtered_2.loc[idx]
        incr_dev_prior_ay = data_filtered_2["Gross_Incurred"].sum()
    else:
        incr_dev_prior_ay = 0.0

    # Step 4: Estimated incremental development beyond the factor-one dev month
    if growth_factor == 0:
        return 1.0

    estimated_ay_incr_beyond_dev = incr_dev + (incr_dev_prior_ay / growth_factor)

    # Step 5: Tail factor
    cumulative_at_max_year = data_filtered.loc[max_year_idx, "Cumulative_Gross_Incurred"]

    if cumulative_at_max_year == 0:
        return 1.0

    tail_factor = 1.0 + (estimated_ay_incr_beyond_dev / cumulative_at_max_year)

    return tail_factor
