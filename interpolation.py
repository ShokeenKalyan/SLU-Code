"""
interpolation.py — Annual-to-quarterly interpolation for long-tailed profiles.

R source: MBR_interpolation.R

Long-tailed profiles use annual (Year-Year) triangles because annual data is
more stable. But downstream financial reporting needs quarterly granularity.
This module uses cubic spline interpolation to convert annual cumulative
percentage patterns into quarterly (monthly dev-period) values.
"""

import numpy as np
import pandas as pd
from scipy.interpolate import CubicSpline


# =============================================================================
# Annual to Quarterly Interpolation
# R source: calc_interpolation()
# =============================================================================

def annual_to_quarterly(cum_percentages_df, profile_id, analysis_qtr, years_analyzed):
    """
    Interpolate annual cumulative development percentages into quarterly values
    using a natural cubic spline.

    The R code creates spline knots at annual intervals (every 12 months) and
    evaluates the spline at every month, then filters to quarterly dev periods.
    There is special handling for Q3 analysis quarter vs other quarters.

    R equivalent: calc_interpolation()

    Parameters
    ----------
    cum_percentages_df : pd.DataFrame
        Long-tail annual cumulative percentages for this profile.
        Must have columns ['dev_len', 'Cum_Percentages', 'profile_id'].
        Should be pre-filtered to the current profile.
    profile_id : str
        The profile being processed.
    analysis_qtr : int
        The analysis quarter (1, 2, 3, or 4).
    years_analyzed : int
        Number of years analyzed (determines how far out to interpolate).

    Returns
    -------
    pd.DataFrame
        Quarterly interpolated values with columns:
        ['dev_len', 'Cum_Percentages', 'profile_id'].
    """
    # Sort by development length ascending
    df = cum_percentages_df.sort_values("dev_len", ascending=True).reset_index(drop=True)
    pattern = df["Cum_Percentages"].values

    # Edge case: empty pattern
    if len(pattern) == 0:
        return pd.DataFrame(columns=["dev_len", "Cum_Percentages", "profile_id"])

    if analysis_qtr == 3:
        # -----------------------------------------------------------
        # Q3 branch: two splines
        # First spline covers the initial ramp-up (months 0-9)
        # Second spline covers the main development (months 9-297)
        # -----------------------------------------------------------

        # First spline: early development (months 0 to 9)
        x1 = np.array([0, 3, 6, 9])
        y1 = np.array([0.0, 0.0, 0.0, pattern[0]])
        spline1 = CubicSpline(x1, y1, bc_type="natural")

        # Evaluate at months 1, 2, 3
        months_early = np.arange(1, 4)  # [1, 2, 3]
        values_early = spline1(months_early)
        result1 = pd.DataFrame({
            "Dev Month": months_early,
            "Pattern": values_early,
        })

        # Second spline: main development (months 9, 21, 33, ... up to 297)
        x_main = np.concatenate(([0], np.arange(9, 298, 12)))
        y_main = np.concatenate(([0.0], pattern))
        # Trim to equal length — pattern may be shorter than the full
        # 25-year grid that np.arange() generates.
        n = min(len(x_main), len(y_main))
        x_main = x_main[:n]
        y_main = y_main[:n]
        spline2 = CubicSpline(x_main, y_main, bc_type="natural")

        # Evaluate at every month from 3 to 297
        months_main = np.arange(3, 298)
        values_main = spline2(months_main)

        # Build result, labeling dev months starting at 3 (index offset of +2)
        result2 = pd.DataFrame({
            "Dev Month": np.arange(3, len(values_main) + 3),
            "Pattern": values_main,
        })
        # Remove the first row (R: result = result[-1,])
        result2 = result2.iloc[1:].reset_index(drop=True)

        result_final = pd.concat([result1, result2], ignore_index=True)

    else:
        # -----------------------------------------------------------
        # Non-Q3 branch: single spline
        # Knots at months 0, 3, 15, 27, 39, ... up to 291
        # -----------------------------------------------------------
        x_main = np.concatenate(([0], np.arange(3, 292, 12)))
        y_main = np.concatenate(([0.0], pattern))
        # Trim to equal length — pattern may be shorter than the x grid.
        n = min(len(x_main), len(y_main))
        x_main = x_main[:n]
        y_main = y_main[:n]
        spline = CubicSpline(x_main, y_main, bc_type="natural")

        # Evaluate at every month from 3 to 291
        months_main = np.arange(3, 292)
        values_main = spline(months_main)

        result_final = pd.DataFrame({
            "Dev Month": np.arange(3, len(values_main) + 3),
            "Pattern": values_main,
        })

    # -----------------------------------------------------------
    # Filter to quarterly development periods only
    # dev_len = 3, 6, 9, 12, ... up to 3*4*years_analyzed - 3*(4-analysis_qtr)
    # -----------------------------------------------------------
    max_dev = 3 * 4 * years_analyzed - 3 * (4 - analysis_qtr)
    quarterly_dev_lens = np.arange(3, max_dev + 1, 3)

    result_final = result_final[
        result_final["Dev Month"].isin(quarterly_dev_lens)
    ].copy()

    # Rename columns to match expected output format
    result_final = result_final.rename(columns={
        "Dev Month": "dev_len",
        "Pattern": "Cum_Percentages",
    })
    result_final["profile_id"] = profile_id

    result_final = result_final[["dev_len", "Cum_Percentages", "profile_id"]].reset_index(drop=True)

    return result_final


# =============================================================================
# Clamp After First 1.0
# R source: func_convert_after_first_one()
# =============================================================================

def clamp_after_first_one(interpolation_result_df, profile_id):
    """
    Once cumulative percentages reach 1.0, clamp all subsequent values to 1.0.

    Cubic splines can "overshoot" — the interpolated values might go above 1.0
    and then dip back. This function ensures that once we hit full development
    (Cum_Percentages == 1.0), it stays at 1.0 forever after.

    R equivalent: func_convert_after_first_one()

    Parameters
    ----------
    interpolation_result_df : pd.DataFrame
        Interpolated results with columns ['dev_len', 'Cum_Percentages', 'profile_id'].
        Can contain multiple profiles (will be filtered to the specified one).
    profile_id : str
        The profile to clamp.

    Returns
    -------
    pd.DataFrame
        Same structure with Cum_Percentages clamped to 1.0 after the first occurrence.
    """
    df = interpolation_result_df[
        interpolation_result_df["profile_id"] == profile_id
    ].copy()

    if df.empty:
        return df

    # Find the first index where Cum_Percentages == 1.0
    ones_mask = df["Cum_Percentages"] == 1.0
    if ones_mask.any():
        first_one_pos = ones_mask.idxmax()  # Index label of first True
        # Set all values from that point onward to 1.0
        df.loc[first_one_pos:, "Cum_Percentages"] = 1.0

    # Also floor at 0.0 — splines can undershoot into negatives at
    # early development months.
    df["Cum_Percentages"] = df["Cum_Percentages"].clip(lower=0.0)

    return df.reset_index(drop=True)


# =============================================================================
# Convenience Wrapper
# =============================================================================

def interpolate_profile(annual_cum_pct_df, profile_id, config):
    """
    Full interpolation pipeline for one Long-tailed profile:
      1. Spline-interpolate annual → quarterly.
      2. Clamp values after the first 1.0.

    Parameters
    ----------
    annual_cum_pct_df : pd.DataFrame
        Annual Cum_Percentages for this profile (columns: dev_len,
        Cum_Percentages, profile_id).
    profile_id : str
        Profile identifier.
    config : dict
        Pipeline configuration (needs 'analysis_qtr', 'years_analyzed').

    Returns
    -------
    pd.DataFrame
        Quarterly interpolated, clamped Cum_Percentages.
    """
    # Step 1: interpolate
    quarterly_df = annual_to_quarterly(
        annual_cum_pct_df, profile_id,
        config["analysis_qtr"], config["years_analyzed"],
    )

    if quarterly_df.empty:
        return quarterly_df

    # Step 2: clamp after first 1.0
    quarterly_df = clamp_after_first_one(quarterly_df, profile_id)

    return quarterly_df
