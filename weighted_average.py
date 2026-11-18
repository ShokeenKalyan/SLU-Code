"""
weighted_average.py — Volume-Weighted Average LDF Computation

Converted from: MBR_weighted_average.R (calc_weighted_average function)

This module computes volume-weighted average Loss Development Factors (LDFs)
for multiple "best-N" windows (e.g., best-3, best-5, best-7 years), converts
them to cumulative development factors (CDFs) and percent-developed figures.

Volume-weighted means larger exposure years (by loss volume) have more
influence on the average. The "best-N" window means we only use the N most
recent non-outlier years at each development period.
"""

import numpy as np
import pandas as pd


def compute_weighted_average(triangle_matrix, age_to_age_outliers, n_periods,
                             years_analyzed, analysis_qtr,
                             remove_outliers=True):
    """
    Compute volume-weighted average LDFs for a given n-period window.

    R equivalent: calc_weighted_average(n, data, age_to_age_outliers, remove_outliers_flag)

    How it works:
    For each development period (column pair in the triangle), it takes the
    N most recent non-outlier, non-zero exposure years and computes:
        VW_Average = sum(next_period_values) / sum(current_period_values)

    This gives more weight to years with larger loss volumes.

    Parameters
    ----------
    triangle_matrix : pd.DataFrame
        Cumulative incurred triangle. Rows = exposure years, columns = dev periods.
        Column names are development lengths (e.g., 3, 6, 9, ... for quarterly).
    age_to_age_outliers : pd.DataFrame
        Data frame with columns: exp_year, dev_len, outlier_flag.
        outlier_flag = 1 means the point is an outlier and should be excluded.
    n_periods : int
        Number of most recent years to use for averaging (e.g., 3, 5, 7, 10).
    years_analyzed : int
        Number of exposure years in the analysis window.
    analysis_qtr : int
        The evaluation quarter (1-4).
    remove_outliers : bool
        If True, exclude points flagged as outliers.

    Returns
    -------
    np.ndarray
        1D array of volume-weighted average LDFs, one per development period.
        Length = 4*years_analyzed - (4-analysis_qtr), matching R's wa_matrix.
    """
    columns = triangle_matrix.columns.tolist()
    num_periods = len(columns)
    expected_length = 4 * years_analyzed - (4 - analysis_qtr)
    wa_array = np.ones(expected_length)

    for i in range(num_periods - 1):
        current_col = columns[i]
        next_col = columns[i + 1]

        # Build a temporary dataframe with current and next period values
        temp_df = pd.DataFrame({
            "current_val": triangle_matrix[current_col],
            "next_val": triangle_matrix[next_col],
            "exp_year": triangle_matrix.index,
            "dev_len": int(current_col)
        })

        # Merge outlier flags for this development period
        outlier_subset = age_to_age_outliers[
            age_to_age_outliers["dev_len"] == int(current_col)
        ][["exp_year", "outlier_flag"]]
        temp_df = temp_df.merge(outlier_subset, on="exp_year", how="left")

        # Filter out outliers if requested
        # R: filter(temp_df, outlier_flag==0) — removes NaN rows too
        if remove_outliers:
            temp_df = temp_df[temp_df["outlier_flag"] == 0]

        # Filter out zero and NaN values (can't compute age-to-age for these)
        # R: filter(temp_df, d!=0) — NA!=0 is NA, which R removes
        temp_df = temp_df.dropna(subset=["current_val", "next_val"])
        temp_df = temp_df[temp_df["current_val"] != 0]
        temp_df = temp_df[temp_df["next_val"] != 0]

        k = len(temp_df)

        if k == 0:
            # No valid data points — default to 1.0 (no development)
            wa_array[i] = 1.0
            continue

        # Use the N most recent years (by exp_year descending)
        temp_df = temp_df.sort_values("exp_year", ascending=False)
        if k >= n_periods:
            temp_df = temp_df.head(n_periods)

        # Volume-weighted average: sum(next) / sum(current)
        numerator = temp_df["next_val"].sum()
        denominator = temp_df["current_val"].sum()

        if denominator == 0 or np.isnan(denominator):
            wa_array[i] = 1.0
        else:
            vw = numerator / denominator
            # Guard against bad values
            if vw == 0 or np.isnan(vw) or np.isinf(vw):
                wa_array[i] = 1.0
            else:
                wa_array[i] = vw

    # Last development period is always 1.0 (no further development observable)
    wa_array[-1] = 1.0

    return wa_array


def compute_all_vw_averages(triangle_matrix, age_to_age_outliers, n_period_candidates,
                            years_analyzed, analysis_qtr,
                            remove_outliers=True):
    """
    Compute VW averages for all candidate n-period windows.

    R equivalent: Called in a loop in SLU_main_code.R over multiple n values.

    Parameters
    ----------
    triangle_matrix : pd.DataFrame
        Cumulative incurred triangle.
    age_to_age_outliers : pd.DataFrame
        Outlier flags per (exp_year, dev_len).
    n_period_candidates : list of int
        List of n values to test, e.g. [3, 4, 5, 6, 7, 8, 9, 10] for Medium.
    years_analyzed : int
        Number of exposure years in the analysis window.
    analysis_qtr : int
        The evaluation quarter (1-4).
    remove_outliers : bool
        Whether to exclude outlier-flagged points.

    Returns
    -------
    dict
        Keys are n values, values are dicts with:
            "n": the n value
            "ldfs": np.ndarray of VW average LDFs
            "cdfs": np.ndarray of cumulative development factors
            "cum_pct": np.ndarray of percent-developed figures
    """
    results = {}

    for n in n_period_candidates:
        ldfs = compute_weighted_average(
            triangle_matrix, age_to_age_outliers, n,
            years_analyzed, analysis_qtr, remove_outliers
        )
        cdfs = compute_cdf_chain(ldfs)
        cum_pct = compute_percent_developed(cdfs)

        results[n] = {
            "n": n,
            "ldfs": ldfs,
            "cdfs": cdfs,
            "cum_pct": cum_pct,
        }

    return results


def compute_cdf_chain(ldfs):
    """
    Convert incremental LDFs to Cumulative Development Factors (CDFs).

    R equivalent: cumprod(rev(Incr_Factors))

    The LDFs are reversed (longest dev first) then cumulatively multiplied.
    This gives the factor to multiply current incurred by to project to ultimate.

    Example:
        LDFs (short→long): [1.50, 1.20, 1.08, 1.02, 1.00]
        Reversed:           [1.00, 1.02, 1.08, 1.20, 1.50]
        CDF (cumprod):      [1.00, 1.02, 1.1016, 1.3219, 1.9829]

        At dev period 1 (earliest), multiply incurred by 1.98 to get ultimate.
        At dev period 5 (latest), multiply by 1.00 (already at ultimate).

    Parameters
    ----------
    ldfs : np.ndarray
        Incremental LDFs from shortest to longest development period.

    Returns
    -------
    np.ndarray
        Cumulative development factors, from shortest to longest dev period.
        Same order as input (reversed internally then reversed back).
    """
    reversed_ldfs = ldfs[::-1]
    reversed_cdfs = np.cumprod(reversed_ldfs)
    cdfs = reversed_cdfs[::-1]
    return cdfs


def compute_percent_developed(cdfs):
    """
    Convert CDFs to percent-developed (Cum_Percentages).

    R equivalent: Cum_Percentages = 1 / Cum_Factors

    Percent developed = 1 / CDF. Tells you what fraction of ultimate losses
    have been reported at each development period.

    Example:
        CDF:     [1.98, 1.32, 1.10, 1.02, 1.00]
        Cum_Pct: [0.50, 0.76, 0.91, 0.98, 1.00]

        At dev period 1: 50% developed (half the losses are still to come)
        At dev period 5: 100% developed (all losses reported)

    Parameters
    ----------
    cdfs : np.ndarray
        Cumulative development factors.

    Returns
    -------
    np.ndarray
        Percent developed at each development period (values between 0 and 1).
    """
    # Guard against division by zero
    with np.errstate(divide="ignore", invalid="ignore"):
        cum_pct = np.where(cdfs != 0, 1.0 / cdfs, 0.0)
    return cum_pct


def build_ldf_dataframe(ldfs, cdfs, cum_pct, best_n, sml_flag,
                        years_analyzed, analysis_qtr, analysis_year,
                        analysis_val_flag, profile_id, ri_type="Gross"):
    """
    Build the final long-format LDF dataframe for one profile.

    R equivalent: Lines 817-821 (build wide ldf_df) + fn_avg_ldf_transform()
    (lines 1827-1870 of SLU_main_code.R) which unpivots and adds dev_len.

    In R this is a two-step process:
      1. Stack wa_matrix, cdf_matrix, inc_perc_dev_matrix into a wide dataframe
         with columns V1, V2, ..., VN plus metadata columns.
      2. fn_avg_ldf_transform() unpivots the V-columns into rows, trims L-tailed
         padding, and computes dev_len from column position.

    This function does both steps in one go — no intermediate wide format needed.

    How dev_len is computed from column position (1-based):
      S/M profiles: dev_len = position * 3          → 3, 6, 9, 12, ...
      L profiles:   dev_len = 12*(position-1) + 3*analysis_qtr
                    For Q3: → 9, 21, 33, 45, ...

    For L-tailed profiles, the LDF/CDF/cum_pct arrays have length
    4*years_analyzed-(4-analysis_qtr) (e.g., 99 for Q3/25yr), but only
    the first years_analyzed positions (25) carry real values — the rest
    are padding (1.0). R trims with: filter(dev_value <= years_analyzed).

    Parameters
    ----------
    ldfs : np.ndarray
        Volume-weighted average LDFs (length = 4*years_analyzed-(4-analysis_qtr)).
    cdfs : np.ndarray
        Cumulative development factors (same length).
    cum_pct : np.ndarray
        Percent developed as fractions 0-1 (same length).
        Will be multiplied by 100 to match R's "Incurred % Developed".
    best_n : int
        The selected best-N value (used in the Averages label).
    sml_flag : str
        "S", "M", or "L".
    years_analyzed : int
        Number of exposure years in the analysis window.
    analysis_qtr : int
        Evaluation quarter (1-4).
    analysis_year : int
        Evaluation year (e.g., 2026).
    analysis_val_flag : str
        Valuation flag (e.g., "Val").
    profile_id : str
        The profile identifier.
    ri_type : str
        Reinsurance type, default "Gross".

    Returns
    -------
    pd.DataFrame
        Long-format dataframe with columns:
        res_year, res_qtr, val_flag, profile_id, Ri_type, Averages, dev_len, Value
        Three rows per dev_len (one each for VW Average, CDF, Incurred % Developed).
    """
    # Determine how many positions to keep
    if sml_flag == "L":
        # L-tailed: only first years_analyzed positions are real, rest is padding
        n_keep = years_analyzed
    else:
        # S/M: all positions are real
        n_keep = len(ldfs)

    # Trim arrays to the positions we keep
    ldfs_trimmed = ldfs[:n_keep]
    cdfs_trimmed = cdfs[:n_keep]
    # R uses 100/cdf for "Incurred % Developed", Python's cum_pct is 1/cdf
    cum_pct_trimmed = cum_pct[:n_keep] * 100

    # Compute dev_len for each position (1-based like R's V1, V2, ...)
    positions = np.arange(1, n_keep + 1)
    if sml_flag == "L":
        dev_lens = 12 * (positions - 1) + 3 * analysis_qtr
    else:
        dev_lens = positions * 3

    # Row label matching R: "Volume-Weighted Average 7"
    avg_label = f"Volume-Weighted Average {best_n}"

    # Build long-format rows: 3 rows per dev_len
    rows = []
    for idx in range(n_keep):
        dl = int(dev_lens[idx])
        rows.append({
            "res_year": analysis_year,
            "res_qtr": analysis_qtr,
            "val_flag": analysis_val_flag,
            "profile_id": profile_id,
            "Ri_type": ri_type,
            "Averages": avg_label,
            "dev_len": dl,
            "Value": ldfs_trimmed[idx],
        })
        rows.append({
            "res_year": analysis_year,
            "res_qtr": analysis_qtr,
            "val_flag": analysis_val_flag,
            "profile_id": profile_id,
            "Ri_type": ri_type,
            "Averages": "CDF",
            "dev_len": dl,
            "Value": cdfs_trimmed[idx],
        })
        rows.append({
            "res_year": analysis_year,
            "res_qtr": analysis_qtr,
            "val_flag": analysis_val_flag,
            "profile_id": profile_id,
            "Ri_type": ri_type,
            "Averages": "Incurred % Developed",
            "dev_len": dl,
            "Value": cum_pct_trimmed[idx],
        })

    result_df = pd.DataFrame(rows)
    return result_df
