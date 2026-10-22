"""
actuarial_methods.py — Actuarial ultimate-loss estimation methods.

Converts: MBR_actuarial_method_ultimates.R.txt

Contains four standard actuarial methods to estimate ultimate losses:
  - DFM  (Development Factor Method / Chain Ladder)
  - BF   (Bornhuetter-Ferguson)
  - CC   (Cape Cod)
  - LR   (Loss Ratio)
Plus recovery-ratio methods for ceded/reinsurance.

Each function takes a pandas DataFrame of exposure-year data and returns
the same DataFrame with new columns for that method's ultimate.
"""

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# 1. Development Factor Method (DFM / Chain Ladder)
# ---------------------------------------------------------------------------
# R equivalent: DFM calculation in SLU_main_code.R
# Formula:  DFM_Ultimate = Cumulative_Incurred / Cum_Percentages
#           (i.e. current incurred divided by the fraction developed so far)
# ---------------------------------------------------------------------------

def compute_dfm_ultimate(df):
    """
    Compute DFM (Chain Ladder) ultimate for each exposure year.

    DFM simply projects current incurred to ultimate using the selected
    cumulative development percentages. It works best for mature years
    (>= 85% developed) where actual loss data is reliable.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain columns: 'Gross_Incurred', 'Cum_Percentages'

    Returns
    -------
    pd.DataFrame
        Input df with new column 'DFM_Ultimate'.
    """
    df = df.copy()

    # DFM Ultimate = Current Incurred / Cum_Percentages
    # Guard against division by zero: if Cum_Percentages is 0, set ultimate to 0
    df["DFM_Ultimate"] = np.where(
        df["Cum_Percentages"] != 0,
        df["Gross_Incurred"] / df["Cum_Percentages"],
        0.0
    )

    return df


# ---------------------------------------------------------------------------
# 2. Bornhuetter-Ferguson (BF)
# ---------------------------------------------------------------------------
# R equivalent: calc_BF_Inc_Loss()
# Formula:
#   BF_IELR_modified = current-year LR trended back using PAI/LTI indexes
#   BF_Ultimate = Actual_Incurred + (1 - Cum_Percentages) * Premium * BF_IELR_modified
#
# The BF method blends actual emerged losses with an a priori expected loss.
# For mature years the actual data dominates; for immature years the expected
# loss ratio dominates. This makes BF more stable than DFM for recent years.
# ---------------------------------------------------------------------------

def compute_bf_ultimate(df, config):
    """
    Compute Bornhuetter-Ferguson ultimate for each exposure year.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain columns: 'exp_year', 'Gross_Incurred', 'Premium',
        'Cum_Percentages', 'BF_IELR', 'Financial_Budget_LR', 'PAI', 'LTI'
    config : dict
        Must contain key 'analysis_year' (the current evaluation year).

    Returns
    -------
    pd.DataFrame
        Input df with new columns 'BF_IELR_modified' and 'BF_Ultimate'.
    """
    df = df.copy()
    analysis_year = config["analysis_year"]

    # --- Step 1: Determine current-year loss ratio ---
    # If BF_IELR is provided (non-zero) for the current year, use it.
    # Otherwise fall back to Financial_Budget_LR.
    cy_mask = df["exp_year"] == analysis_year
    cy_bf_ielr = df.loc[cy_mask, "BF_IELR"].values
    cy_budget_lr = df.loc[cy_mask, "Financial_Budget_LR"].values

    # Handle case where current year might not exist in data
    if len(cy_bf_ielr) == 0:
        cy_lr = 0.0
    else:
        cy_lr = cy_budget_lr[0] if cy_bf_ielr[0] == 0 else cy_bf_ielr[0]

    # --- Step 2: Trend the current-year LR back to each exposure year ---
    # For the current year: use cy_lr directly.
    # For prior years: cy_lr * PAI / LTI  (trend adjustment).
    # If LTI is 0, set to 0 to avoid division by zero.
    df["BF_IELR_modified"] = np.where(
        df["exp_year"] == analysis_year,
        cy_lr,
        np.where(
            df["LTI"] == 0,
            0.0,
            cy_lr * df["PAI"] / df["LTI"]
        )
    )

    # Clean up any NaN or Inf values
    df["BF_IELR_modified"] = df["BF_IELR_modified"].fillna(0.0)
    df["BF_IELR_modified"] = df["BF_IELR_modified"].replace([np.inf, -np.inf], 0.0)

    # --- Step 3: Compute BF Ultimate ---
    # BF = Actual Incurred + Expected Unreported
    # Expected Unreported = (1 - Cum_Percentages) * Premium * BF_IELR_modified
    df["BF_Ultimate"] = (
        df["Gross_Incurred"]
        + (1 - df["Cum_Percentages"]) * df["Premium"] * df["BF_IELR_modified"]
    )

    return df


# ---------------------------------------------------------------------------
# 3. Cape Cod (CC) — Gross version
# ---------------------------------------------------------------------------
# R equivalent: calc_cc_IELR()
# The Cape Cod method is like BF but derives its expected loss ratio from
# the data itself (instead of using an external a priori).
#
# Steps:
#   1. Compute trended development loss ratio per exposure year
#   2. Compute a portfolio-wide weighted average (the "CC IELR")
#   3. Detrend it back to each exposure year
#   4. Ultimate = Incurred + (1 - Cum%) * Premium * CC_Detrended_LR
# ---------------------------------------------------------------------------

def compute_cc_ielr(df, config, use_prev_valuation=False):
    """
    Compute Cape Cod IELR and CC Ultimate for each exposure year (gross).

    Parameters
    ----------
    df : pd.DataFrame
        Must contain: 'exp_year', 'Gross_Incurred', 'Premium', 'Cum_Percentages',
        'PAI', 'LTI', 'CC_Exp_weight', 'dev_len'.
        If use_prev_valuation is True, must also contain 'Prev_Val_CC_Detrended_LR'.
    config : dict
        Must contain: 'analysis_year', 'sml_flag',
        'years_analyzed_S_tailed', 'years_analyzed_M_tailed', 'years_analyzed_L_tailed'.
    use_prev_valuation : bool
        If True (muf==1 in R), use prior valuation's CC detrended LR instead
        of the newly computed one. This is used when the CC method is being
        held constant from a prior evaluation.

    Returns
    -------
    pd.DataFrame
        Input df with new columns: 'trended_dev_LR', 'CC_detrended_LR', 'CC_Ultimate'.
    """
    df = df.copy()
    analysis_year = config["analysis_year"]
    sml_flag = config["sml_flag"]

    # --- Step 1: Zero out CC weights for years outside the lookback window ---
    # The lookback window depends on the SML classification.
    if sml_flag == "S":
        lookback_years = config["years_analyzed_S_tailed"]
    elif sml_flag == "M":
        lookback_years = config["years_analyzed_M_tailed"]
    else:
        lookback_years = config["years_analyzed_L_tailed"]

    cutoff_year = analysis_year - lookback_years + 1
    df["CC_Exp_weight"] = np.where(df["exp_year"] < cutoff_year, 0, df["CC_Exp_weight"])

    # --- Step 2: Compute trended development loss ratio per exposure year ---
    # trended_dev_LR = (Incurred * LTI) / (Premium * PAI * Cum_Percentages)
    denominator = df["Premium"] * df["PAI"] * df["Cum_Percentages"]
    numerator = df["Gross_Incurred"] * df["LTI"]

    df["trended_dev_LR"] = np.where(denominator != 0, numerator / denominator, 0.0)

    # Clean NaN/Inf
    df["trended_dev_LR"] = df["trended_dev_LR"].fillna(0.0)
    df["trended_dev_LR"] = df["trended_dev_LR"].replace([np.inf, -np.inf], 0.0)

    # --- Step 3: Compute portfolio-wide weighted CC factor ---
    # Weighted average: sum(LR * Premium * Cum% * PAI * weight) / sum(Premium * Cum% * PAI * weight)
    weighted_num = (df["trended_dev_LR"] * df["Premium"] * df["Cum_Percentages"]
                    * df["PAI"] * df["CC_Exp_weight"]).sum()
    weighted_den = (df["Premium"] * df["Cum_Percentages"]
                    * df["PAI"] * df["CC_Exp_weight"]).sum()

    fact = weighted_num / weighted_den if weighted_den != 0 else 0.0

    # --- Step 4: Detrend back to each exposure year ---
    # CC_detrended_LR = fact * PAI / LTI
    # For the first development period (dev_len <= 12), use 'fact' directly.
    df["CC_detrended_LR"] = np.where(
        df["LTI"] != 0,
        fact * df["PAI"] / df["LTI"],
        0.0
    )
    df.loc[df["dev_len"] <= 12, "CC_detrended_LR"] = fact

    # Clean NaN
    df["CC_detrended_LR"] = df["CC_detrended_LR"].fillna(0.0)

    # --- Step 5: Compute CC Ultimate ---
    if use_prev_valuation:
        # Use prior valuation's detrended LR (for "method update flag" == 1)
        df["CC_Ultimate"] = (
            df["Gross_Incurred"]
            + (1 - df["Cum_Percentages"]) * df["Premium"] * df["Prev_Val_CC_Detrended_LR"]
        )
    else:
        df["CC_Ultimate"] = (
            df["Gross_Incurred"]
            + (1 - df["Cum_Percentages"]) * df["Premium"] * df["CC_detrended_LR"]
        )

    return df


# ---------------------------------------------------------------------------
# 4. Cape Cod — Ceded version
# ---------------------------------------------------------------------------
# R equivalent: calc_cc_IELR_ceded()
# Same as gross CC but computes the weighted factor per Ri_type (reinsurance
# type) separately, since different reinsurance contracts have different
# development patterns.
# ---------------------------------------------------------------------------

def compute_cc_ielr_ceded(df, config, use_prev_valuation=False):
    """
    Compute Cape Cod IELR and CC Ultimate for ceded (reinsurance) data.

    Identical to the gross version except the CC factor is computed
    separately per Ri_type group.

    Parameters
    ----------
    df : pd.DataFrame
        Same as compute_cc_ielr plus 'Ri_type' column.
    config : dict
        Same as compute_cc_ielr.
    use_prev_valuation : bool
        Same as compute_cc_ielr.

    Returns
    -------
    pd.DataFrame
        Input df with new columns: 'trended_dev_LR', 'CC_detrended_LR', 'CC_Ultimate'.
    """
    df = df.copy()
    analysis_year = config["analysis_year"]
    sml_flag = config["sml_flag"]

    # --- Step 1: Zero out CC weights outside lookback window ---
    if sml_flag == "S":
        lookback_years = config["years_analyzed_S_tailed"]
    elif sml_flag == "M":
        lookback_years = config["years_analyzed_M_tailed"]
    else:
        lookback_years = config["years_analyzed_L_tailed"]

    cutoff_year = analysis_year - lookback_years + 1
    df["CC_Exp_weight"] = np.where(df["exp_year"] < cutoff_year, 0, df["CC_Exp_weight"])

    # --- Step 2: Trended dev LR per row ---
    denominator = df["Premium"] * df["PAI"] * df["Cum_Percentages"]
    numerator = df["Gross_Incurred"] * df["LTI"]

    df["trended_dev_LR"] = np.where(denominator != 0, numerator / denominator, 0.0)
    df["trended_dev_LR"] = df["trended_dev_LR"].fillna(0.0)
    df["trended_dev_LR"] = df["trended_dev_LR"].replace([np.inf, -np.inf], 0.0)

    # --- Step 3: Compute weighted CC factor PER Ri_type ---
    # (In gross version this is a single scalar; in ceded it's per reinsurance type.)
    df["_num"] = (df["trended_dev_LR"] * df["Premium"] * df["Cum_Percentages"]
                  * df["PAI"] * df["CC_Exp_weight"])
    df["_den"] = (df["Premium"] * df["Cum_Percentages"]
                  * df["PAI"] * df["CC_Exp_weight"])

    fact_df = df.groupby("Ri_type").agg(
        _num_sum=("_num", "sum"),
        _den_sum=("_den", "sum")
    ).reset_index()
    fact_df["fact"] = np.where(fact_df["_den_sum"] != 0,
                               fact_df["_num_sum"] / fact_df["_den_sum"], 0.0)
    fact_df = fact_df[["Ri_type", "fact"]]

    # Merge the per-Ri_type factor back to main df
    df = df.merge(fact_df, on="Ri_type", how="left")

    # --- Step 4: Detrend ---
    df["CC_detrended_LR"] = np.where(
        df["LTI"] != 0,
        df["fact"] * df["PAI"] / df["LTI"],
        0.0
    )
    df.loc[df["dev_len"] <= 12, "CC_detrended_LR"] = df.loc[df["dev_len"] <= 12, "fact"]
    df["CC_detrended_LR"] = df["CC_detrended_LR"].fillna(0.0)

    # Clean up temp columns
    df = df.drop(columns=["_num", "_den", "fact"])

    # --- Step 5: CC Ultimate ---
    if use_prev_valuation:
        df["CC_Ultimate"] = (
            df["Gross_Incurred"]
            + (1 - df["Cum_Percentages"]) * df["Premium"] * df["Prev_Val_CC_Detrended_LR"]
        )
    else:
        df["CC_Ultimate"] = (
            df["Gross_Incurred"]
            + (1 - df["Cum_Percentages"]) * df["Premium"] * df["CC_detrended_LR"]
        )

    return df


# ---------------------------------------------------------------------------
# 5. Loss Ratio (LR)
# ---------------------------------------------------------------------------
# R equivalent: calc_LR_Ultimate()
# The simplest method: Ultimate = Premium × Selected_Loss_Ratio.
# Used for immature years where actual development data is unreliable.
#
# The "selected loss ratio" is chosen per exposure year from one of:
#   - BF IELR MBR (the MBR-computed BF loss ratio)
#   - Actuarial Loss (manually entered actuarial LR)
#   - Financial Budget Loss (budget LR)
#   - Detrended LR (from Cape Cod)
# ---------------------------------------------------------------------------

def compute_lr_ultimate(df, config):
    """
    Compute Loss Ratio ultimate for each exposure year.

    For the current year, picks between BF IELR MBR and Financial Budget.
    For prior years, defaults to BF IELR MBR.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain: 'exp_year', 'Premium', 'BF_IELR_modified',
        'Financial_Budget_LR', 'Actuarial_LR', 'CC_detrended_LR'.
    config : dict
        Must contain: 'analysis_year'.

    Returns
    -------
    pd.DataFrame
        Input df with new columns 'Selected_LR_Met_modified' and 'LR_Ultimate'.
    """
    df = df.copy()
    analysis_year = config["analysis_year"]

    # --- Step 1: Determine LR method name for current year ---
    # If BF IELR MBR is non-zero AND differs from budget LR → use BF IELR MBR
    # Otherwise → use Financial Budget Loss
    cy_mask = df["exp_year"] == analysis_year
    cy_bf_mod = df.loc[cy_mask, "BF_IELR_modified"].values
    cy_budget = df.loc[cy_mask, "Financial_Budget_LR"].values

    if len(cy_bf_mod) > 0 and cy_bf_mod[0] != 0 and cy_bf_mod[0] != cy_budget[0]:
        cy_method_name = "BF IELR MBR"
    else:
        cy_method_name = "Financial Budget Loss"

    # --- Step 2: Assign LR method per exposure year ---
    # Current year gets the method determined above; all other years get BF IELR MBR.
    df["Selected_LR_Met_modified"] = np.where(
        df["exp_year"] == analysis_year,
        cy_method_name,
        "BF IELR MBR"
    )

    # --- Step 3: Compute LR Ultimate based on selected method ---
    # Map method name → loss ratio column → multiply by premium
    method_map = {
        "BF IELR MBR":          "BF_IELR_modified",
        "Actuarial Loss":       "Actuarial_LR",
        "Financial Budget Loss": "Financial_Budget_LR",
        "Detrended LR (New)":   "CC_detrended_LR",
    }

    df["LR_Ultimate"] = 0.0
    for method_name, lr_column in method_map.items():
        mask = df["Selected_LR_Met_modified"] == method_name
        if lr_column in df.columns:
            df.loc[mask, "LR_Ultimate"] = df.loc[mask, lr_column] * df.loc[mask, "Premium"]

    return df


# ---------------------------------------------------------------------------
# 6. Recovery Ratio (RR) Ultimates — for ceded/reinsurance
# ---------------------------------------------------------------------------
# R equivalent: calc_RR_All_Ultimates()
# Computes ceded ultimates using three different recovery ratio approaches:
#   - Premium recovery ratio
#   - Incurred recovery ratio
#   - Paid recovery ratio
# Plus an LR ultimate for the ceded layer.
# ---------------------------------------------------------------------------

def compute_rr_ultimates(df, config):
    """
    Compute recovery-ratio-based ultimates for ceded reinsurance.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain: 'Gross_Incurred', 'ibnr', 'exp_year', 'Premium',
        'Premium_Recovery_Ratio', 'Incurred_Recovery_Ratio',
        'Paid_Recovery_Ratio', 'BF_IELR_modified', 'Financial_Budget_LR'.
    config : dict
        Must contain: 'analysis_year'.

    Returns
    -------
    pd.DataFrame
        Input df with new columns: 'premium_rr_ultimate', 'incurred_rr_ultimate',
        'paid_rr_ultimate', 'LR_Ultimate'.
    """
    df = df.copy()
    analysis_year = config["analysis_year"]

    # RR ultimates: Incurred + IBNR * Recovery_Ratio
    df["premium_rr_ultimate"] = df["Gross_Incurred"] + df["ibnr"] * df["Premium_Recovery_Ratio"]
    df["incurred_rr_ultimate"] = df["Gross_Incurred"] + df["ibnr"] * df["Incurred_Recovery_Ratio"]
    df["paid_rr_ultimate"] = df["Gross_Incurred"] + df["ibnr"] * df["Paid_Recovery_Ratio"]

    # LR Ultimate for ceded:
    # If current year AND BF_IELR_modified == Financial_Budget_LR → use budget
    # Otherwise → use BF IELR
    cy_mask = df["exp_year"] == analysis_year

    # Get current-year values for the condition check
    cy_bf_mod = df.loc[cy_mask, "BF_IELR_modified"].values
    cy_budget = df.loc[cy_mask, "Financial_Budget_LR"].values

    if len(cy_bf_mod) > 0:
        use_budget = (cy_bf_mod[0] == cy_budget[0])
    else:
        use_budget = True

    df["LR_Ultimate"] = np.where(
        cy_mask & use_budget,
        df["Gross_Incurred"] + df["Financial_Budget_LR"] * df["Premium"],
        df["Gross_Incurred"] + df["BF_IELR_modified"] * df["Premium"]
    )

    return df


# ---------------------------------------------------------------------------
# 7. Orchestrator — compute all methods
# ---------------------------------------------------------------------------

def compute_all_ultimates(state, config):
    """
    Run all four actuarial methods on the profile data.

    This is called from main.py after LDFs, tail factors, and Cum_Percentages
    have been computed. It adds DFM, BF, CC, and LR ultimate columns to the
    exposure-year data.

    Parameters
    ----------
    state : dict
        The profile state dictionary. Must contain a DataFrame at
        state["profile_data"] with all required columns for each method.
    config : dict
        Pipeline configuration.

    Returns
    -------
    pd.DataFrame
        The profile DataFrame with all ultimate columns added.
    """
    df = state["profile_data"].copy()

    # 1. DFM — always computed
    df = compute_dfm_ultimate(df)

    # 2. BF — needs BF_IELR and Premium
    df = compute_bf_ultimate(df, config)

    # 3. CC — needs CC weights and Premium
    use_prev = config.get("method_update_flag", 0) == 1
    df = compute_cc_ielr(df, config, use_prev_valuation=use_prev)

    # 4. LR — needs BF_IELR_modified (from BF step) and Premium
    df = compute_lr_ultimate(df, config)

    return df
