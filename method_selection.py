"""
method_selection.py — Select the best actuarial method per exposure year.

Converts: MBR_method_selection_by_exposure_year_cc_change.R.txt

The selection logic uses two passes:
  Pass 1 — Rule-based:  hard thresholds assign methods to extreme years
  Pass 2 — Simulation:  RMSE hindsight test picks the best method for
                         the remaining "middle" years

After both passes, Vena overrides (manual actuarial selections) take
final precedence.
"""

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# 1. Check which methods have valid inputs
# ---------------------------------------------------------------------------
# R equivalent: get_valid_methods()
# Some methods need non-zero assumptions. If the assumptions are missing,
# the method is excluded from the selection.
# ---------------------------------------------------------------------------

def get_valid_methods(df_methods, vena_inputs, config):
    """
    Determine which of the four actuarial methods have valid assumptions
    and can be considered for selection.

    Returns a dict with boolean flags: {'DFM': True, 'BF': True/False,
    'CC': True/False, 'LR': True}.

    Parameters
    ----------
    df_methods : dict
        Method availability flags, e.g. {'DFM': 1, 'BF': 1, 'CC': 1, 'LR': 1}.
    vena_inputs : pd.DataFrame
        Vena assumption vectors. Must contain 'exp_year', 'BF_IELR',
        'Financial_Budget_LR', 'CC_Exp_weight'.
    config : dict
        Must contain 'analysis_year'.

    Returns
    -------
    dict
        Method flags, e.g. {'DFM': 1, 'BF': 1, 'CC': 0, 'LR': 1}.
        A value of 0 means that method is excluded.
    """
    result = dict(df_methods)  # copy
    analysis_year = config["analysis_year"]

    # BF requires a non-zero current-year loss ratio
    # (either BF_IELR or Financial_Budget_LR)
    cy_mask = vena_inputs["exp_year"] == analysis_year
    cy_bf_ielr = vena_inputs.loc[cy_mask, "BF_IELR"].values
    cy_budget_lr = vena_inputs.loc[cy_mask, "Financial_Budget_LR"].values

    if len(cy_bf_ielr) > 0:
        cy_lr = cy_budget_lr[0] if cy_bf_ielr[0] == 0 else cy_bf_ielr[0]
    else:
        cy_lr = 0.0

    if cy_lr == 0:
        result["BF"] = 0

    # CC requires at least one non-zero exposure weight
    if vena_inputs["CC_Exp_weight"].sum() == 0:
        result["CC"] = 0

    return result


# ---------------------------------------------------------------------------
# 2. RMSE helper — root mean squared error
# ---------------------------------------------------------------------------

def _rmse(actual, predicted):
    """Compute RMSE between two arrays. Returns 0 if empty."""
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    if len(actual) == 0:
        return 0.0
    return np.sqrt(np.mean((actual - predicted) ** 2))


# ---------------------------------------------------------------------------
# 3. Main method selection per exposure year
# ---------------------------------------------------------------------------
# R equivalent: fn_select_ultimate_by_exp_year()
#
# Two-pass logic:
#   Pass 1 (Rules):
#     - Cum_Percentages >= 0.85  →  DFM
#     - Oldest years (outside lookback window)  →  DFM
#     - Current year  →  LR
#     - Cum_Percentages <= 0.40  →  LR
#
#   Pass 2 (Simulation — only for years not assigned by rules):
#     - For each unassigned year, look at all older years
#     - Compute what DFM/BF/CC would have predicted at that dev stage
#     - Compare to actual DFM ultimate → RMSE per method
#     - Pick the method with lowest RMSE
#
#   Consistency enforcement:
#     - If DFM is selected for any year, all older years also get DFM
#
#   Vena overrides: applied last (not in this function — done in main.py)
# ---------------------------------------------------------------------------

def select_method_by_exposure_year(
    ultimates_df,
    best_iter_result,
    ultimate_methods_to_use,
    actuals_cum,
    config
):
    """
    Select the best actuarial method for each exposure year.

    Parameters
    ----------
    ultimates_df : pd.DataFrame
        All exposure years with columns: 'exp_year', 'Cum_Percentages',
        'Gross_Incurred', 'Premium', 'DFM_Ultimate', 'BF_Ultimate',
        'CC_Ultimate', 'LR_Ultimate', 'BF_IELR_MBR', 'PAI', 'LTI',
        'CC_Detrended_LR_MBR', 'res_year', 'res_qtr', 'val_flag',
        'profile_id'.
    best_iter_result : pd.DataFrame
        Selected LDF iteration result with 'exp_year', 'Cum_Percentages',
        and ultimate columns.
    ultimate_methods_to_use : dict
        Which methods are valid, e.g. {'DFM': 1, 'BF': 1, 'CC': 1, 'LR': 1}.
    actuals_cum : pd.DataFrame
        Cumulative incurred actuals with 'exp_year', 'dev_len',
        'Cumulative_Gross_Incurred'.
    config : dict
        Must contain: 'analysis_year', 'years_capped', 'exp_year_dev_len'
        (DataFrame mapping exp_year to dev_len).

    Returns
    -------
    dict with keys:
        'selections_df': pd.DataFrame with 'selectedMethod' and 'SelectedUltimate'
        'exp_year_simulate_rmse_df': pd.DataFrame with RMSE details (for diagnostics)
        'exp_year_simulate_data_df': pd.DataFrame with simulation details
    """
    analysis_year = config["analysis_year"]
    years_capped = config["years_capped"]
    exp_year_dev_len = config["exp_year_dev_len"]

    # Keep a copy of all years (used later to look up ultimate values)
    ultimates_all_years_df = ultimates_df.copy()

    # --- Filter to recent years for the method selection window ---
    # Only consider years within the lookback window
    max_non_zero_inc_year = ultimates_df.loc[
        ultimates_df["Gross_Incurred"] != 0, "exp_year"
    ].max() if (ultimates_df["Gross_Incurred"] != 0).any() else analysis_year

    year_cutoff = max(max_non_zero_inc_year - 12, analysis_year - years_capped)
    ultimates_df = ultimates_df[ultimates_df["exp_year"] > year_cutoff].copy()
    ultimates_df = ultimates_df[ultimates_df["Cum_Percentages"] >= 0.5].copy()

    # --- Compute average DFM ULR for outlier filtering ---
    # Exclude years with 0 incurred or 0 premium
    rmse_filter = ultimates_df[
        (ultimates_df["Cum_Percentages"] >= 0.5) &
        (ultimates_df["Gross_Incurred"] != 0)
    ].copy()

    if len(rmse_filter) > 0:
        total_premium = rmse_filter["Premium"].sum()
        avg_dfm_ulr = (
            rmse_filter["DFM_Ultimate"].sum() / total_premium
            if total_premium != 0 else 0.0
        )
    else:
        avg_dfm_ulr = 0.0

    # Flag years with DFM ULR within 0.5x to 1.5x of average (reasonable range)
    ultimates_df["DFM_ULR"] = np.where(
        ultimates_df["Premium"] != 0,
        ultimates_df["DFM_Ultimate"] / ultimates_df["Premium"],
        0.0
    )
    ultimates_df["exp_year_to_include_rmse_calc"] = np.where(
        (ultimates_df["DFM_ULR"] <= 1.5 * avg_dfm_ulr) &
        (ultimates_df["DFM_ULR"] >= 0.5 * avg_dfm_ulr),
        "Y", "N"
    )

    # ===================================================================
    # PASS 1: Rule-based method assignment
    # ===================================================================
    selections_df = best_iter_result.copy()

    # Rule 1: Mature years (>= 85% developed) → DFM
    selections_df["selectedMethod"] = np.where(
        selections_df["Cum_Percentages"] >= 0.85,
        "DFM_Ultimate", None
    )

    # Rule 2: Old years (outside lookback) → DFM
    old_year_cutoff = max(max_non_zero_inc_year - 11, analysis_year - years_capped + 1)
    selections_df["selectedMethod"] = np.where(
        (selections_df["exp_year"] <= old_year_cutoff) & selections_df["selectedMethod"].isna(),
        "DFM_Ultimate",
        selections_df["selectedMethod"]
    )
    # Re-apply: the np.where above may have stringified None, fix with explicit None
    selections_df["selectedMethod"] = selections_df["selectedMethod"].replace("None", None)

    # Rule 3: Current year → LR
    selections_df["selectedMethod"] = np.where(
        (selections_df["exp_year"] == analysis_year) & selections_df["selectedMethod"].isna(),
        "LR_Ultimate",
        selections_df["selectedMethod"]
    )
    selections_df["selectedMethod"] = selections_df["selectedMethod"].replace("None", None)

    # Rule 4: Very immature years (<= 40% developed) → LR
    selections_df["selectedMethod"] = np.where(
        (selections_df["Cum_Percentages"] <= 0.40) & selections_df["selectedMethod"].isna(),
        "LR_Ultimate",
        selections_df["selectedMethod"]
    )
    selections_df["selectedMethod"] = selections_df["selectedMethod"].replace("None", None)

    # ===================================================================
    # PASS 2: Hindsight RMSE simulation for unassigned years
    # ===================================================================
    unassigned_mask = selections_df["selectedMethod"].isna()
    exp_year_simulate_df = selections_df[unassigned_mask].copy()

    exp_year_simulate_rmse_df = pd.DataFrame()
    exp_year_simulate_data_df = pd.DataFrame()

    all_outlier_excluded = (
        len(ultimates_df) == 0
        or (ultimates_df["exp_year_to_include_rmse_calc"] == "N").all()
    )

    if len(exp_year_simulate_df) > 0 and not all_outlier_excluded:

        frames = []

        for _, sim_row in exp_year_simulate_df.iterrows():
            sim_year = sim_row["exp_year"]
            sim_cum_pct = sim_row["Cum_Percentages"]

            # Get the development month for this simulated year
            dev_len_row = exp_year_dev_len[exp_year_dev_len["exp_year"] == sim_year]
            if len(dev_len_row) == 0:
                continue
            dev_month = int(dev_len_row.iloc[0, 1])

            # Get all older years from the ultimates window
            data_df = ultimates_df[ultimates_df["exp_year"] < sim_year].copy()
            if len(data_df) == 0:
                continue

            data_df["exp_year_simulated"] = sim_year
            data_df["Cum_Percentages"] = sim_cum_pct

            # Get actual cumulative incurred at that dev month
            actuals_at_dev = actuals_cum[actuals_cum["dev_len"] == dev_month].copy()
            actuals_at_dev = actuals_at_dev.rename(columns={
                "dev_len": "max_dev_len",
                "Cumulative_Gross_Incurred": "Cumulative_Gross_Incurred_as_at_max_dev_len"
            })

            data_df = data_df.merge(
                actuals_at_dev[["exp_year", "max_dev_len",
                                "Cumulative_Gross_Incurred_as_at_max_dev_len"]],
                on="exp_year", how="left"
            )

            # Compute what each method would have predicted at that dev stage
            data_df["DFM_Ultimate_as_at_max_dev_len"] = np.where(
                sim_cum_pct != 0,
                data_df["Cumulative_Gross_Incurred_as_at_max_dev_len"] / sim_cum_pct,
                0.0
            )
            data_df["BF_Ultimate_as_at_max_dev_len"] = (
                data_df["Cumulative_Gross_Incurred_as_at_max_dev_len"]
                + (1 - sim_cum_pct) * data_df["Premium"] * data_df["BF_IELR_MBR"]
            )
            data_df["CC_Ultimate_as_at_max_dev_len"] = (
                data_df["Cumulative_Gross_Incurred_as_at_max_dev_len"]
                + (1 - sim_cum_pct) * data_df["Premium"] * data_df["CC_Detrended_LR_MBR"]
            )

            frames.append(data_df)

        if frames:
            exp_year_simulate_data_df = pd.concat(frames, ignore_index=True)

            # Filter to only "reasonable" years if any exist
            if (exp_year_simulate_data_df["exp_year_to_include_rmse_calc"] == "Y").any():
                exp_year_simulate_data_df = exp_year_simulate_data_df[
                    exp_year_simulate_data_df["exp_year_to_include_rmse_calc"] == "Y"
                ].copy()

            # --- Compute RMSE per simulated year ---
            rmse_rows = []
            for sim_year, grp in exp_year_simulate_data_df.groupby("exp_year_simulated"):
                row = {
                    "exp_year_simulated": sim_year,
                    "DFM_RMSE": _rmse(grp["DFM_Ultimate"], grp["DFM_Ultimate_as_at_max_dev_len"]),
                    "BF_RMSE":  _rmse(grp["DFM_Ultimate"], grp["BF_Ultimate_as_at_max_dev_len"]),
                    "CC_RMSE":  _rmse(grp["DFM_Ultimate"], grp["CC_Ultimate_as_at_max_dev_len"]),
                }
                # Carry forward profile identifiers
                first = grp.iloc[0]
                for col in ["res_year", "res_qtr", "val_flag", "profile_id"]:
                    if col in grp.columns:
                        row[col] = first[col]
                rmse_rows.append(row)

            if rmse_rows:
                exp_year_simulate_rmse_df = pd.DataFrame(rmse_rows)

                # Add Cum_Percentages for each simulated year
                cum_pct_map = exp_year_simulate_df.set_index("exp_year")["Cum_Percentages"]
                exp_year_simulate_rmse_df["Cum_Percentages"] = (
                    exp_year_simulate_rmse_df["exp_year_simulated"].map(cum_pct_map)
                )

                # --- Determine which methods are available ---
                methods_to_use = ultimate_methods_to_use
                available_rmse_cols = ["DFM_RMSE"]  # DFM always available
                if methods_to_use.get("BF", 1) == 1:
                    available_rmse_cols.append("BF_RMSE")
                if methods_to_use.get("CC", 1) == 1:
                    available_rmse_cols.append("CC_RMSE")

                # For years >= 50% developed: consider all available methods
                # For years < 50% developed: exclude DFM (BF/CC only)
                def _pick_method(row):
                    cum_pct = row.get("Cum_Percentages", 0)

                    if cum_pct >= 0.50:
                        cols = available_rmse_cols
                    else:
                        # Exclude DFM for immature years
                        cols = [c for c in available_rmse_cols if c != "DFM_RMSE"]

                    if not cols:
                        return "DFM_RMSE"

                    # Find the method with minimum RMSE
                    min_val = None
                    min_col = cols[0]
                    for c in cols:
                        val = row.get(c, np.inf)
                        if min_val is None or val < min_val:
                            min_val = val
                            min_col = c
                    return min_col

                exp_year_simulate_rmse_df["selectedMethod"] = (
                    exp_year_simulate_rmse_df.apply(_pick_method, axis=1)
                )

                # --- Consistency: if DFM is selected for any year, all older → DFM ---
                exp_year_simulate_rmse_df = exp_year_simulate_rmse_df.sort_values(
                    "exp_year_simulated"
                ).reset_index(drop=True)

                if (exp_year_simulate_rmse_df["selectedMethod"] == "DFM_RMSE").any():
                    first_dfm_idx = (
                        exp_year_simulate_rmse_df["selectedMethod"] == "DFM_RMSE"
                    ).idxmax()
                    exp_year_simulate_rmse_df.loc[:first_dfm_idx, "selectedMethod"] = "DFM_RMSE"

                # --- Map RMSE column names to ultimate column names ---
                method_name_map = {
                    "DFM_RMSE": "DFM_Ultimate",
                    "BF_RMSE":  "BF_Ultimate",
                    "CC_RMSE":  "CC_Ultimate",
                }
                exp_year_simulate_rmse_df["selectedMethod"] = (
                    exp_year_simulate_rmse_df["selectedMethod"].map(method_name_map)
                )

                # --- Merge simulation results back into selections ---
                sim_merge = exp_year_simulate_rmse_df[
                    ["exp_year_simulated", "selectedMethod"]
                ].rename(columns={
                    "exp_year_simulated": "exp_year",
                    "selectedMethod": "selectedMethod_simulated"
                })

                selections_df = selections_df.merge(sim_merge, on="exp_year", how="left")

                # Fill in simulated methods where rules didn't assign
                selections_df["selectedMethod"] = np.where(
                    selections_df["selectedMethod"].isna(),
                    selections_df.get("selectedMethod_simulated"),
                    selections_df["selectedMethod"]
                )

                if "selectedMethod_simulated" in selections_df.columns:
                    selections_df = selections_df.drop(columns=["selectedMethod_simulated"])

    # --- Fallback: any still-unassigned years get DFM ---
    selections_df["selectedMethod"] = selections_df["selectedMethod"].fillna("DFM_Ultimate")

    # ===================================================================
    # Look up the actual ultimate value for the selected method
    # ===================================================================
    selections_df["SelectedUltimate"] = 0.0

    for idx in selections_df.index:
        method = selections_df.loc[idx, "selectedMethod"]
        exp_yr = selections_df.loc[idx, "exp_year"]

        # Find matching row in the full ultimates table
        match = ultimates_all_years_df[ultimates_all_years_df["exp_year"] == exp_yr]
        if len(match) > 0 and method in match.columns:
            selections_df.loc[idx, "SelectedUltimate"] = match.iloc[0][method]

    return {
        "selections_df": selections_df,
        "exp_year_simulate_rmse_df": exp_year_simulate_rmse_df,
        "exp_year_simulate_data_df": exp_year_simulate_data_df,
    }
