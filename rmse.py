"""
rmse.py — Weighted RMSE Scoring for VW Average Selection and Iteration Ranking

Converted from:
  - MBR_iteration_weighted_rmse_sml.R  (calc_VW_Averages_weighted_RMSE, calc_weighted_RMSE, filter_list)
  - MBR_threshold_ultimate_weighted_RMSE.R  (calc_upper_tri_rmse)

This module is the single most important scoring function in the MBR system.
Every automated decision — which best-N to use, which iteration to pick,
which actuarial method to select — ultimately depends on the RMSE calculated here.

WHAT IS WEIGHTED RMSE?
  Not all development periods matter equally. Errors in early development
  periods (where most claims are still unreported) have a bigger impact
  on the final reserve estimate than errors in late periods.
  So we weight each period's RMSE by how much development is still to come:
      weight = |1 - Cum_Percentages|
  A period at 30% development has weight 0.70 (a lot still to happen).
  A period at 95% development has weight 0.05 (almost fully settled).
"""

import numpy as np
import pandas as pd

from weighted_average import compute_cdf_chain, compute_percent_developed


# ---------------------------------------------------------------------------
# Helper: compute RMSE between two arrays
# ---------------------------------------------------------------------------

def _rmse(actual, predicted):
    """
    Root Mean Squared Error between two arrays.

    R equivalent: Metrics::rmse(actual, predicted)

    Parameters
    ----------
    actual : array-like
    predicted : array-like

    Returns
    -------
    float
        RMSE value. Returns 0.0 if inputs are empty.
    """
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    if len(actual) == 0:
        return 0.0
    return np.sqrt(np.mean((actual - predicted) ** 2))


# ===========================================================================
# FUNCTION 1: calc_vw_weighted_rmse
#
# Scores a single VW-n candidate (e.g., VW-5 = "use last 5 years").
# Answers: "How well do these VW average LDFs predict the actual age-to-age
# factors in the triangle?"
#
# The SELECTION of best n uses weighted_rmse_excl1 (excluding the first
# development period, which is often noisy).
# ===========================================================================

def calc_vw_weighted_rmse(vw_ldfs, dev_lens, age_to_age_outliers,
                          n_period, sml_flag, config):
    """
    Compute weighted RMSE for a single VW averaging period.

    R equivalent: calc_VW_Averages_weighted_RMSE()

    How it works:
    1. Build a factors table (LDFs → CDFs → Cum_Percentages) from the VW averages.
    2. For each development period, compare VW average LDF vs actual age-to-age
       factors for the N most recent non-outlier exposure years.
    3. Compute RMSE per dev period, then weight by |1 - Cum_Percentages|.
    4. Return overall weighted RMSE plus variants excluding 1-4 early periods.

    Parameters
    ----------
    vw_ldfs : np.ndarray
        Volume-weighted average LDFs for this n (from weighted_average.compute_weighted_average).
    dev_lens : np.ndarray or list
        Development lengths corresponding to each LDF (e.g., [3,6,9,...] for quarterly).
    age_to_age_outliers : pd.DataFrame
        Actual age-to-age factors with columns:
        exp_year, dev_len, age_to_age, outlier_flag, Gross_Incurred.
    n_period : int
        The VW averaging window being scored (e.g., 5 for best-5).
    sml_flag : str
        "S", "M", or "L" for Short/Medium/Long-tailed profile.
    config : dict
        Configuration containing analysis_year, analysis_qtr, analysis_val_flag.

    Returns
    -------
    dict with keys:
        "weighted_rmse"       : float — overall weighted RMSE
        "weighted_rmse_excl1" : float — RMSE excluding first dev period
        "weighted_rmse_excl2" : float — RMSE excluding first 2 dev periods
        "weighted_rmse_excl3" : float — RMSE excluding first 3 dev periods
        "weighted_rmse_excl4" : float — RMSE excluding first 4 dev periods
        "factors_df"          : pd.DataFrame — LDF/CDF/Cum_Percentages table
    """

    # --- Step 1: Build the factors table ---
    # Reverse order: shortest dev first → compute CDF chain → Cum_Percentages
    factors_df = pd.DataFrame({
        "dev_len": np.array(dev_lens)[::-1],
        "Incr_Factors": vw_ldfs[::-1],
    })
    factors_df["Cum_Factors"] = factors_df["Incr_Factors"].cumprod()
    factors_df["Cum_Percentages"] = 1.0 / factors_df["Cum_Factors"]

    # Add metadata columns
    factors_df["res_year"] = config["analysis_year"]
    factors_df["res_qtr"] = config["analysis_qtr"]
    factors_df["val_flag"] = config["analysis_val_flag"]

    # --- Step 2: Join VW averages back to actual age-to-age factors ---
    ata = age_to_age_outliers.copy()
    ata = ata.merge(
        factors_df[["dev_len", "Incr_Factors", "Cum_Factors", "Cum_Percentages"]],
        on="dev_len",
        how="left"
    )

    # Filter to valid data points (same exclusions used when building VW averages)
    ata = ata[ata["outlier_flag"] == 0]
    ata = ata[ata["Gross_Incurred"] != 0]
    ata = ata.sort_values(["dev_len", "exp_year"], ascending=[True, False])

    # --- Step 3: Restrict to the n most recent years per dev period ---
    # For VW-5 (n=5), the RMSE should only compare against the same 5 years used
    ata = (
        ata.groupby("dev_len", group_keys=False)
        .apply(lambda g: g.nlargest(n_period, "exp_year"))
    )

    # --- Step 4: Compute RMSE per development period ---
    dev_len_rmse = (
        ata.groupby("dev_len")
        .apply(lambda g: _rmse(g["age_to_age"].values, g["Incr_Factors"].values))
        .reset_index(name="dev_len_rmse")
    )

    dev_len_rmse = dev_len_rmse.merge(
        factors_df[["dev_len", "Cum_Percentages"]], on="dev_len", how="left"
    )

    # --- Step 5: Compute weights ---
    # Weight = |1 - Cum_Percentages| = proportion of losses yet to develop
    # Early periods get high weight (errors matter more for reserves)
    # Late periods get low weight (almost fully settled)
    dev_len_rmse["weights"] = np.abs(1.0 - dev_len_rmse["Cum_Percentages"])

    # --- Step 6: Compute weighted RMSE (all periods) ---
    weighted_rmse = _compute_weighted_rmse_from_df(dev_len_rmse)

    # --- Step 7: Compute excl1 through excl4 variants ---
    # Exclude the earliest N development periods (they are often noisy)
    # slice_max(dev_len, n = nrow - k) keeps all rows EXCEPT the k smallest dev_lens
    n_rows = len(dev_len_rmse)

    weighted_rmse_excl1 = (
        _compute_weighted_rmse_from_df(
            dev_len_rmse.nlargest(n_rows - 1, "dev_len")
        ) if n_rows > 2 else 1.0
    )

    if n_rows > 4:
        weighted_rmse_excl2 = _compute_weighted_rmse_from_df(
            dev_len_rmse.nlargest(n_rows - 2, "dev_len")
        )
        weighted_rmse_excl3 = _compute_weighted_rmse_from_df(
            dev_len_rmse.nlargest(n_rows - 3, "dev_len")
        )
        weighted_rmse_excl4 = _compute_weighted_rmse_from_df(
            dev_len_rmse.nlargest(n_rows - 4, "dev_len")
        )
    else:
        weighted_rmse_excl2 = 1.0
        weighted_rmse_excl3 = 1.0
        weighted_rmse_excl4 = 1.0

    return {
        "weighted_rmse": weighted_rmse,
        "weighted_rmse_excl1": weighted_rmse_excl1,
        "weighted_rmse_excl2": weighted_rmse_excl2,
        "weighted_rmse_excl3": weighted_rmse_excl3,
        "weighted_rmse_excl4": weighted_rmse_excl4,
        "factors_df": factors_df,
    }


def _compute_weighted_rmse_from_df(df):
    """
    Compute weighted RMSE from a dataframe with 'dev_len_rmse' and 'weights' columns.

    Formula: sum(rmse_per_period * weight) / sum(weights)
    Returns 1.0 (worst score) if result is NaN or sum of weights is zero.
    """
    total_weight = df["weights"].sum()
    if total_weight == 0:
        return 1.0
    result = (df["dev_len_rmse"] * df["weights"]).sum() / total_weight
    if np.isnan(result):
        return 1.0
    return result


# ===========================================================================
# FUNCTION 2: select_best_n
#
# Runs calc_vw_weighted_rmse for all candidate n values and picks the one
# with the lowest weighted_rmse_excl1 (excluding the noisy first dev period).
# ===========================================================================

def select_best_n(vw_averages_dict, age_to_age_outliers, dev_lens, sml_flag, config):
    """
    Score all VW-n candidates and select the best one.

    R equivalent: Called in SLU_main_code.R via lapply + which.min on weighted_rmse_excl1.

    Parameters
    ----------
    vw_averages_dict : dict
        Output of weighted_average.compute_all_vw_averages().
        Keys = n values, values = dicts with "ldfs", "cdfs", "cum_pct".
    age_to_age_outliers : pd.DataFrame
        Actual age-to-age factors with outlier flags.
    dev_lens : np.ndarray or list
        Development lengths corresponding to each LDF position.
    sml_flag : str
        "S", "M", or "L".
    config : dict
        Configuration with analysis_year, analysis_qtr, etc.

    Returns
    -------
    dict with keys:
        "best_n"       : int — the selected n value
        "best_ldfs"    : np.ndarray — the LDFs from the best n
        "best_cdfs"    : np.ndarray — the CDFs from the best n
        "best_cum_pct" : np.ndarray — the percent-developed from the best n
        "all_rmse"     : dict — RMSE results for all n values
        "factors_df"   : pd.DataFrame — factors table for the best n
    """
    all_rmse = {}
    best_n = None
    best_rmse = float("inf")

    for n, vw_data in vw_averages_dict.items():
        rmse_result = calc_vw_weighted_rmse(
            vw_ldfs=vw_data["ldfs"],
            dev_lens=dev_lens,
            age_to_age_outliers=age_to_age_outliers,
            n_period=n,
            sml_flag=sml_flag,
            config=config,
        )
        all_rmse[n] = rmse_result

        # Selection uses excl1 (the first dev period is often noisy)
        if rmse_result["weighted_rmse_excl1"] < best_rmse:
            best_rmse = rmse_result["weighted_rmse_excl1"]
            best_n = n

    return {
        "best_n": best_n,
        "best_ldfs": vw_averages_dict[best_n]["ldfs"],
        "best_cdfs": vw_averages_dict[best_n]["cdfs"],
        "best_cum_pct": vw_averages_dict[best_n]["cum_pct"],
        "all_rmse": all_rmse,
        "factors_df": all_rmse[best_n]["factors_df"],
    }


# ===========================================================================
# FUNCTION 3: calc_iteration_weighted_rmse
#
# Scores a single converged iteration from the tree-search algorithm.
# Answers: "How well does this LDF sequence predict actual loss development?"
#
# It works differently from VW RMSE:
# - Computes DFM (chain ladder) ultimates per exposure year
# - For each observation, computes actual inc_to_ult = incurred / ultimate
# - Compares inc_to_ult against Cum_Percentages from the LDFs
# - Lower RMSE = the LDF pattern better explains the observed development
# ===========================================================================

def calc_iteration_weighted_rmse(iteration_ldfs, dev_lens, inc_by_ay,
                                 actuals_cum, exp_year_dev_len,
                                 profile_id, sml_flag, max_non_zero_inc_year,
                                 config):
    """
    Compute weighted RMSE for one converged iteration.

    R equivalent: calc_weighted_RMSE()

    Parameters
    ----------
    iteration_ldfs : np.ndarray
        The LDF sequence from one converged iteration (the Iteration_Values column).
    dev_lens : np.ndarray or list
        Development lengths corresponding to each LDF position.
    inc_by_ay : pd.DataFrame
        Total incurred per exposure year. Columns: exp_year, Gross_Incurred.
    actuals_cum : pd.DataFrame
        All actual cumulative incurred observations (the full triangle).
        Columns: profile_id, exp_year, dev_len, Gross_Incurred,
                 Cumulative_Gross_Incurred, lower_tri_cmbn.
    exp_year_dev_len : pd.DataFrame
        Maps each exposure year to its max observed dev_len (the diagonal).
        Columns: exp_year, max_dev_len.
    profile_id : str
        The profile being processed.
    sml_flag : str
        "S", "M", or "L".
    max_non_zero_inc_year : int
        Latest exposure year with non-zero incurred.
    config : dict
        Configuration with analysis_year, analysis_qtr, years_analyzed_*,
        years_capped, analysis_val_flag.

    Returns
    -------
    dict with keys:
        "weighted_rmse"    : float — the scalar score (lower = better)
        "dfm_ultimate"     : pd.DataFrame — DFM ultimates per exposure year
        "rmse_check"       : pd.DataFrame — diagnostic (actuals vs predicted)
        "actuals_cum_rmse" : pd.DataFrame — RMSE per development period
        "factors_df"       : pd.DataFrame — CDF and Cum_Percentages
    """

    # --- Step 1: Build factors table (reverse, cumprod, Cum_Percentages) ---
    factors_df = pd.DataFrame({
        "dev_len": np.array(dev_lens)[::-1],
        "Incr_Factors": iteration_ldfs[::-1],
    })
    factors_df["Cum_Factors"] = factors_df["Incr_Factors"].cumprod()
    factors_df["Cum_Percentages"] = 1.0 / factors_df["Cum_Factors"]
    factors_df["res_year"] = config["analysis_year"]
    factors_df["res_qtr"] = config["analysis_qtr"]
    factors_df["val_flag"] = config["analysis_val_flag"]
    factors_df["profile_id"] = profile_id

    # --- Step 2: Match factors to each exposure year's diagonal position ---
    # Each exposure year is observed at a specific dev_len (its diagonal)
    factors_at_diagonal = factors_df.merge(
        exp_year_dev_len.rename(columns={"max_dev_len": "dev_len"}),
        on="dev_len",
        how="inner"
    )

    dfm_ultimate = factors_at_diagonal[[
        "exp_year", "dev_len", "Incr_Factors", "Cum_Factors", "Cum_Percentages"
    ]].copy()
    dfm_ultimate["res_year"] = config["analysis_year"]
    dfm_ultimate["res_qtr"] = config["analysis_qtr"]
    dfm_ultimate["val_flag"] = config["analysis_val_flag"]
    dfm_ultimate["profile_id"] = profile_id

    # --- Step 3: Compute DFM ultimate per exposure year ---
    # DFM (Chain Ladder): Ultimate = Gross_Incurred * Cum_Factors
    dfm_ultimate = dfm_ultimate.merge(inc_by_ay[["exp_year", "Gross_Incurred"]],
                                      on="exp_year", how="inner")
    dfm_ultimate["Ultimate"] = dfm_ultimate["Cum_Factors"] * dfm_ultimate["Gross_Incurred"]

    # --- Step 4: Compute inc_to_ult = actual incurred / projected ultimate ---
    # This is the ACTUAL proportion developed at each observation point
    ac = actuals_cum.copy()
    ac = ac.merge(dfm_ultimate[["exp_year", "Ultimate"]], on="exp_year", how="inner")
    ac["inc_to_ult"] = np.where(
        ac["Ultimate"] == 0, 0.0,
        ac["Cumulative_Gross_Incurred"] / ac["Ultimate"]
    )

    # Join predicted Cum_Percentages to each observation
    ac = ac.merge(
        factors_df[["dev_len", "Cum_Percentages"]], on="dev_len", how="left"
    )

    # Build diagnostic dataframe
    rmse_check = ac[[
        "profile_id", "exp_year", "dev_len", "Gross_Incurred",
        "Cumulative_Gross_Incurred", "Ultimate", "inc_to_ult", "Cum_Percentages"
    ]].copy()
    rmse_check["res_year"] = config["analysis_year"]
    rmse_check["res_qtr"] = config["analysis_qtr"]
    rmse_check["val_flag"] = config["analysis_val_flag"]

    # --- Step 5: Apply SML lookback window ---
    # Only use exposure years within the SML-appropriate lookback range
    # Older years are less relevant and could distort the RMSE
    analysis_year = config["analysis_year"]
    years_capped = config["years_capped"]

    if sml_flag == "L":
        years_analyzed_for_sml = config["years_analyzed_L_tailed"]
    elif sml_flag == "S":
        years_analyzed_for_sml = config["years_analyzed_S_tailed"]
    else:  # M
        years_analyzed_for_sml = config["years_analyzed_M_tailed"]

    oldest_year = max(
        max_non_zero_inc_year - years_analyzed_for_sml + 1,
        analysis_year - years_capped + 1
    )
    ac = ac[ac["exp_year"] >= oldest_year]

    # --- Step 6: Compute RMSE per development period ---
    # Compare inc_to_ult (actual %) vs Cum_Percentages (predicted %)
    actuals_cum_rmse = (
        ac.groupby("dev_len")
        .apply(lambda g: _rmse(g["inc_to_ult"].values, g["Cum_Percentages"].values))
        .reset_index(name="RMSE")
    )

    actuals_cum_rmse = actuals_cum_rmse.merge(
        factors_df[["dev_len", "Cum_Percentages"]], on="dev_len", how="left"
    )

    # --- Step 7: Compute weights and final weighted RMSE ---
    # Same logic as VW RMSE: weight = |1 - Cum_Percentages|
    actuals_cum_rmse["weights"] = np.abs(1.0 - actuals_cum_rmse["Cum_Percentages"])

    total_weight = actuals_cum_rmse["weights"].sum()
    if total_weight == 0:
        weighted_rmse = 1.0
    else:
        weighted_rmse = (
            (actuals_cum_rmse["RMSE"] * actuals_cum_rmse["weights"]).sum() / total_weight
        )
    if np.isnan(weighted_rmse):
        weighted_rmse = 1.0

    return {
        "weighted_rmse": weighted_rmse,
        "dfm_ultimate": dfm_ultimate,
        "rmse_check": rmse_check,
        "actuals_cum_rmse": actuals_cum_rmse,
        "factors_df": factors_df,
    }


# ===========================================================================
# FUNCTION 4: select_best_iteration
#
# Scores all converged iterations and picks the one with lowest weighted RMSE.
# ===========================================================================

def select_best_iteration(converged_iterations, dev_lens, inc_by_ay,
                          actuals_cum, exp_year_dev_len,
                          profile_id, sml_flag, max_non_zero_inc_year,
                          config):
    """
    Score all converged iterations and select the best one.

    R equivalent: The loop in SLU_main_code.R that calls calc_weighted_RMSE()
    on each converged iteration and picks which.min(weighted_rmse).

    Parameters
    ----------
    converged_iterations : list of np.ndarray
        Each element is one converged LDF sequence (the Iteration_Values).
    dev_lens : np.ndarray or list
        Development lengths for each LDF position.
    inc_by_ay : pd.DataFrame
        Total incurred per exposure year.
    actuals_cum : pd.DataFrame
        Full cumulative incurred triangle.
    exp_year_dev_len : pd.DataFrame
        Exposure year to max dev_len mapping.
    profile_id : str
        Profile being processed.
    sml_flag : str
        "S", "M", or "L".
    max_non_zero_inc_year : int
        Latest exposure year with non-zero incurred.
    config : dict
        Configuration dictionary.

    Returns
    -------
    dict with keys:
        "best_index"       : int — index of the best iteration in the input list
        "best_weighted_rmse": float — the score of the best iteration
        "best_result"      : dict — full result from calc_iteration_weighted_rmse
        "all_rmse_scores"  : list of float — scores for each iteration
    """
    if not converged_iterations:
        return {
            "best_index": -1,
            "best_weighted_rmse": 1.0,
            "best_result": None,
            "all_rmse_scores": [],
        }

    all_scores = []
    all_results = []

    for iteration_ldfs in converged_iterations:
        result = calc_iteration_weighted_rmse(
            iteration_ldfs=iteration_ldfs,
            dev_lens=dev_lens,
            inc_by_ay=inc_by_ay,
            actuals_cum=actuals_cum,
            exp_year_dev_len=exp_year_dev_len,
            profile_id=profile_id,
            sml_flag=sml_flag,
            max_non_zero_inc_year=max_non_zero_inc_year,
            config=config,
        )
        all_scores.append(result["weighted_rmse"])
        all_results.append(result)

    best_idx = int(np.argmin(all_scores))

    return {
        "best_index": best_idx,
        "best_weighted_rmse": all_scores[best_idx],
        "best_result": all_results[best_idx],
        "all_rmse_scores": all_scores,
    }


# ===========================================================================
# FUNCTION 5: filter_converged
#
# Extracts only the converged iterations from the full iterations list.
# ===========================================================================

def filter_converged(iterations_list):
    """
    Filter the iterations list to only include converged iterations.

    R equivalent: filter_list() used with sapply() in SLU_main_code.R

    Parameters
    ----------
    iterations_list : list of dict
        Each dict has keys "Iteration_Values" (np.ndarray of LDFs) and
        "Convergence" (1 = converged, 0 = failed).

    Returns
    -------
    list of np.ndarray
        Only the Iteration_Values from converged iterations.
    """
    converged = []
    for iteration in iterations_list:
        if iteration.get("Convergence", 0) == 1:
            converged.append(iteration["Iteration_Values"])
    return converged


# ===========================================================================
# FUNCTION 6: calc_upper_tri_rmse
#
# Computes RMSE for the upper triangle back-calculation — used to determine
# the tail factor threshold (how far to extrapolate the curve fit).
# ===========================================================================

def calc_upper_tri_rmse(selected_ultimate_df, actuals_cum, exp_year_dev_len,
                        config):
    """
    Compute weighted RMSE for the upper triangle back-calculation.

    R equivalent: calc_upper_tri_rmse() from MBR_threshold_ultimate_weighted_RMSE.R

    How it works:
    1. Take the last diagonal of the triangle (most recent observation per exp year).
    2. Using selected ultimates, compute cumulative factors at each diagonal.
    3. Back-calculate what incurred SHOULD have been at each earlier dev period
       by dividing by the cumulative factor.
    4. Compare back-calculated values against actual incurred (RMSE).
    5. Weight each diagonal equally (1/count), giving less weight to diagonals
       with many observations.

    This tells us: "Given these ultimate estimates, how well do the implied
    development factors reproduce the actual triangle?" Lower RMSE = the
    ultimates are consistent with observed development.

    Parameters
    ----------
    selected_ultimate_df : pd.DataFrame
        Selected ultimates per exposure year.
        Columns: exp_year, SelectedUltimate.
    actuals_cum : pd.DataFrame
        Full cumulative incurred triangle.
        Columns: profile_id, exp_year, dev_len, Cumulative_Gross_Incurred.
    exp_year_dev_len : pd.DataFrame
        Exposure year to max dev_len mapping.
        Columns: exp_year, max_dev_len.
    config : dict
        Configuration with years_analyzed, analysis_qtr.

    Returns
    -------
    dict with keys:
        "upper_tri_wtd_rmse" : float — the weighted RMSE score
        "rmse_df"            : pd.DataFrame — diagnostic with actuals vs calculated
        "upper_tri_calc_df"  : pd.DataFrame — the back-calculated triangle
    """
    years_analyzed = config["years_analyzed"]
    analysis_qtr = config["analysis_qtr"]

    # --- Step 1: Get the last diagonal (most recent 4 observations per exp year) ---
    last_diagonal_df = (
        actuals_cum.groupby("exp_year", group_keys=False)
        .apply(lambda g: g.nlargest(4, "dev_len"))
    )[["profile_id", "exp_year", "dev_len", "Cumulative_Gross_Incurred"]].copy()

    # Triangle without last diagonal
    merge_keys = last_diagonal_df[["exp_year", "dev_len"]].drop_duplicates()
    actuals_without_last = actuals_cum.merge(merge_keys, on=["exp_year", "dev_len"],
                                             how="left", indicator=True)
    actuals_without_last = actuals_without_last[actuals_without_last["_merge"] == "left_only"]
    actuals_without_last = actuals_without_last.drop(columns=["_merge"])

    # Initialize back-calculated triangle with last diagonal values
    upper_tri_calc_df = last_diagonal_df.copy()

    # --- Step 2: Compute cumulative factors from selected ultimates ---
    last_with_ult = last_diagonal_df.merge(
        selected_ultimate_df[["exp_year", "SelectedUltimate"]],
        on="exp_year", how="left"
    )
    last_with_ult["cum_factor"] = np.where(
        last_with_ult["Cumulative_Gross_Incurred"] != 0,
        last_with_ult["SelectedUltimate"] / last_with_ult["Cumulative_Gross_Incurred"],
        1.0
    )

    # --- Step 3: Back-calculate the upper triangle ---
    # Work backwards from the last diagonal: at each earlier dev period,
    # divide the next period's value by the cumulative factor to get
    # what the incurred should have been
    total_periods = 4 * years_analyzed - (4 - analysis_qtr)

    for i in range(total_periods - 4, 0, -1):
        current_dev = i * 3
        next_dev = (i + 1) * 3

        # Get actual values at current dev period
        dev_df = actuals_without_last[
            actuals_without_last["dev_len"] == current_dev
        ][["profile_id", "exp_year", "dev_len", "Cumulative_Gross_Incurred"]].copy()

        # Get already-computed values at next dev period
        next_dev_df = upper_tri_calc_df[
            upper_tri_calc_df["dev_len"] == next_dev
        ][["exp_year", "Cumulative_Gross_Incurred"]].rename(
            columns={"Cumulative_Gross_Incurred": "Cum_GIL_next_dev"}
        )

        if dev_df.empty or next_dev_df.empty:
            continue

        dev_df = dev_df.merge(next_dev_df, on="exp_year", how="inner")

        # Get cumulative factor for this dev period
        cum_factor_df = last_with_ult[
            last_with_ult["dev_len"] == current_dev
        ][["dev_len", "cum_factor"]].drop_duplicates()
        dev_df = dev_df.merge(cum_factor_df, on="dev_len", how="inner")

        # Back-calculate: divide next period value by cum_factor
        dev_df["Cumulative_Gross_Incurred"] = np.where(
            dev_df["cum_factor"] != 0,
            dev_df["Cum_GIL_next_dev"] / dev_df["cum_factor"],
            0.0
        )
        dev_df = dev_df[["profile_id", "exp_year", "dev_len", "Cumulative_Gross_Incurred"]]

        upper_tri_calc_df = pd.concat([upper_tri_calc_df, dev_df], ignore_index=True)

    # --- Step 4: Compute RMSE between actual and back-calculated ---
    rmse_df = actuals_without_last[
        ["profile_id", "exp_year", "dev_len", "Cumulative_Gross_Incurred"]
    ].rename(columns={"Cumulative_Gross_Incurred": "Actual_GIL"})

    calc_values = upper_tri_calc_df[
        ["profile_id", "exp_year", "dev_len", "Cumulative_Gross_Incurred"]
    ].rename(columns={"Cumulative_Gross_Incurred": "Calculated_GIL"})

    rmse_df = rmse_df.merge(calc_values, on=["profile_id", "exp_year", "dev_len"], how="left")
    rmse_df["Difference_GIL"] = rmse_df["Calculated_GIL"] - rmse_df["Actual_GIL"]
    rmse_df["Squared_Difference_GIL"] = rmse_df["Difference_GIL"] ** 2

    rmse_df = rmse_df.merge(exp_year_dev_len, on="exp_year", how="left")
    rmse_df["diagonal_num"] = (rmse_df["max_dev_len"] - rmse_df["dev_len"]) / 3 + 1

    # --- Step 5: Weight by diagonal ---
    # Each diagonal gets weight = 1/count. Last diagonal has least weight
    # because it's closest to the known data and most influenced by the ultimates.
    diagonal_weights = (
        rmse_df.groupby("diagonal_num")
        .size()
        .reset_index(name="obs_count")
    )
    diagonal_weights["weight"] = 1.0 / diagonal_weights["obs_count"]

    rmse_df = rmse_df.merge(
        diagonal_weights[["diagonal_num", "obs_count"]], on="diagonal_num", how="left"
    )

    diagonal_rmse = (
        rmse_df.groupby("diagonal_num")
        .apply(lambda g: np.sqrt(g["Squared_Difference_GIL"].sum() / g["obs_count"].iloc[0]))
        .reset_index(name="rmse_val")
    )
    diagonal_rmse = diagonal_rmse.merge(diagonal_weights, on="diagonal_num", how="left")

    # Final weighted RMSE
    total_weight = diagonal_rmse["weight"].sum()
    if total_weight == 0:
        upper_tri_wtd_rmse = 0.0
    else:
        upper_tri_wtd_rmse = (
            (diagonal_rmse["rmse_val"] * diagonal_rmse["weight"]).sum() / total_weight
        )

    return {
        "upper_tri_wtd_rmse": upper_tri_wtd_rmse,
        "rmse_df": rmse_df,
        "upper_tri_calc_df": upper_tri_calc_df,
    }
