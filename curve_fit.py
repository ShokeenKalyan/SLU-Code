"""
curve_fit.py — Parametric Curve Fitting for LDF Patterns

Fits four parametric distributions to the empirical Loss Development
Factor (LDF) pattern produced by the volume-weighted-average step.

R source: MBR_curve_fit.R.txt (575 lines)

Distributions:
  1. Exponential Decay   (R: exponentialfunc)
  2. Weibull              (R: weibullfunc)
  3. Power / Sherman      (R: powerfunc)
  4. Inverse Power Curve  (R: IPCfunc)

Each distribution is linearized and fit via OLS (ordinary least squares).
Leave-one-out diagnostics (R², RMSE, Cook's distance) identify influential
points, which are removed before a final refit.  The best-fitting curve
(ranked by R²) is used by the iteration algorithm and tail-factor steps.
"""

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
#  Internal helpers
# ---------------------------------------------------------------------------

def _compute_rmse(actual, predicted):
    """
    Root Mean Squared Error between two equal-length arrays.
    R equivalent: Metrics::rmse()
    """
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    return np.sqrt(np.mean((actual - predicted) ** 2))


def _compute_rmse_r_style(actual_short, predicted_long):
    """
    RMSE matching R's recycling behavior when vectors have different lengths.

    In R's leave-one-out loop: rmse(df_1$y, y_2_cap) where df_1$y has n-1
    elements and y_2_cap has n elements. R recycles df_1$y to length n
    (the first element wraps around to fill the gap). We replicate that here.
    """
    a = np.asarray(actual_short, dtype=float)
    p = np.asarray(predicted_long, dtype=float)
    if len(a) == len(p):
        return np.sqrt(np.mean((a - p) ** 2))
    # Tile/repeat 'a' to match length of 'p' (R's recycling)
    n_long = len(p)
    a_recycled = np.resize(a, n_long)
    return np.sqrt(np.mean((a_recycled - p) ** 2))


def _build_dev_periods(sml_flag, years_analyzed, analysis_qtr):
    """
    Build the development-period vector (in months).

    For short/medium ('S'/'M'): quarterly from 3 to the last observed quarter.
    For long ('L'):              annual from 12, 24, ... , years_analyzed*12.

    Returns
    -------
    x : np.ndarray   — development period values (in months)
    """
    if sml_flag == "L":
        # Annual: 12, 24, 36, ..., years_analyzed * 12
        x = np.arange(12, years_analyzed * 12 + 1, 12)
    else:
        # Quarterly: 3, 6, 9, ..., up to the last available quarter
        last = 3 * 4 * years_analyzed - (4 - analysis_qtr) * 3
        x = np.arange(3, last + 1, 3)
    return x


def _prepare_ldf_series(y_input, sml_flag, years_analyzed):
    """
    Ensure y is a 1-D numpy array, trimmed to years_analyzed for long-tailed.

    Returns
    -------
    y : np.ndarray of LDF values
    """
    y = np.asarray(y_input, dtype=float).flatten()
    if sml_flag == "L":
        y = y[:years_analyzed]
    return y


def _ols_fit(x_trans, y_trans):
    """
    Manual OLS regression on transformed (x, y) pairs.

    This mirrors the R code exactly — it computes the slope (b) and
    intercept (a) from sums, sxx, sxy rather than calling a library.

    Returns  (a, b, ss_res, ss_total, r_squared)
    """
    n = len(x_trans)
    sum_x = np.sum(x_trans)
    sum_y = np.sum(y_trans)
    sum_xx = np.sum(x_trans ** 2)
    sum_xy = np.sum(x_trans * y_trans)
    sxx = sum_xx - (sum_x ** 2) / n
    sxy = sum_xy - sum_x * sum_y / n

    # Slope (b) — guard against zero sxx
    b = sxy / sxx if sxx != 0 else 1.0

    # Intercept (a)
    a = sum_y / n - b * sum_x / n

    # R²
    ss_res = np.sum((y_trans - (a + b * x_trans)) ** 2)
    ss_total = np.sum((y_trans - sum_y / n) ** 2)
    r_squared = 1.0 - (ss_res / ss_total if ss_total != 0 else 1.0)

    return a, b, ss_res, ss_total, r_squared


def _leave_one_out_diagnostics(x_vals, y_vals, x_trans_func, y_trans_func,
                                predict_func, full_ycap):
    """
    Leave-one-out loop that computes R², RMSE, and Cook's distance for
    each data point.

    Parameters
    ----------
    x_vals      : np.ndarray — raw x values (dev periods) for points with LDF > 1
    y_vals      : np.ndarray — raw y values (LDFs) for points with LDF > 1
    x_trans_func: callable(x) → transformed x for OLS
    y_trans_func: callable(y) → transformed y for OLS
    predict_func: callable(a, b, x) → predicted y on the original scale
    full_ycap   : np.ndarray — predicted y from the full-data fit (for Cook's D)

    Returns
    -------
    diag_df : pd.DataFrame with columns [x, y, rsq, rmse, dcook, to_remove]
    """
    n = len(x_vals)
    records = []

    for i in range(n):
        # Leave out point i
        mask = np.ones(n, dtype=bool)
        mask[i] = False
        x_loo = x_vals[mask]
        y_loo = y_vals[mask]

        # Transform and fit OLS on the reduced set
        xt = x_trans_func(x_loo)
        yt = y_trans_func(y_loo)

        a, b, _, _, rsq = _ols_fit(xt, yt)

        # Predicted values on the FULL set (all n points, including the removed one)
        y_pred_full = predict_func(a, b, x_vals)

        # RMSE: R computes rmse(df_1$y, y_2_cap) where df_1$y has n-1 values
        # and y_2_cap has n values (predicted on ALL m_1 points). R silently
        # recycles the shorter vector. We replicate that behavior here.
        rmse_val = _compute_rmse_r_style(y_loo, y_pred_full)

        # Cook's distance: sum of squared differences between full-fit and LOO-fit
        # predictions, divided by 2 * RMSE²
        if rmse_val > 0:
            cook_d = np.sum((full_ycap - y_pred_full) ** 2) / (2 * rmse_val ** 2)
        else:
            cook_d = 0.0

        records.append({
            "x": x_vals[i],
            "y": y_vals[i],
            "rsq": rsq,
            "rmse": rmse_val,
            "dcook": cook_d,
        })

    diag_df = pd.DataFrame(records)

    # Flag influential points for removal
    # Removed if: has the min RMSE, or the max R², or Cook's D > 1
    min_rmse = diag_df["rmse"].min()
    max_rsq = diag_df["rsq"].max()
    diag_df["to_remove"] = np.where(
        (diag_df["rmse"] == min_rmse) |
        (diag_df["rsq"] == max_rsq) |
        (diag_df["dcook"] > 1),
        "Y", "N"
    )
    return diag_df


def _relabel_dev_periods_long(x_all, x_diag, sml_flag, analysis_qtr, years_analyzed):
    """
    For long-tailed profiles the internal dev periods are 12, 24, 36 ...
    but downstream code expects them labelled starting at 3*analysis_qtr.
    This mirrors the R adjustment at the end of each function.
    """
    if sml_flag == "L":
        x_all_new = np.arange(3 * analysis_qtr,
                               years_analyzed * 12 + 1,
                               12)
        x_diag_new = x_diag - 9 / analysis_qtr
        return x_all_new, x_diag_new
    return x_all, x_diag


# ---------------------------------------------------------------------------
#  Public: Exponential Decay
# ---------------------------------------------------------------------------

def fit_exponential_decay(y_input, sml_flag, years_analyzed, analysis_qtr):
    """
    Exponential Decay curve fit.

    Linearization:  ln(y - 1) = a + b * x
    Prediction:     ŷ = 1 + exp(a) * exp(b * x)

    R equivalent: exponentialfunc(y1, sml_flag)

    Parameters
    ----------
    y_input        : array-like — LDF values (one per dev period)
    sml_flag       : str — 'S', 'M', or 'L'
    years_analyzed : int — number of exposure years in the analysis
    analysis_qtr   : int — the quarter being analyzed (1-4)

    Returns
    -------
    dict with keys:
        'fitted_df'   : pd.DataFrame with columns [x, y, ycap] — all dev periods
        'r_squared'   : float — R² of the post-removal fit
        'diagnostics' : pd.DataFrame — leave-one-out diagnostics (influential points info)
    """
    # --- Build dev periods and prepare LDFs ---
    x_all = _build_dev_periods(sml_flag, years_analyzed, analysis_qtr)
    y = _prepare_ldf_series(y_input, sml_flag, years_analyzed)

    # Combine and filter to LDFs > 1
    n_pts = min(len(x_all), len(y))
    x_all = x_all[:n_pts]
    y = y[:n_pts]
    mask_gt1 = y > 1.0
    x_gt1 = x_all[mask_gt1]
    y_gt1 = y[mask_gt1]

    # --- Edge case: no points with LDF > 1 ---
    if len(x_gt1) == 0:
        fitted_df = pd.DataFrame({"x": x_all, "y": y, "ycap": 1.0})
        diag_df = pd.DataFrame({
            "x": x_all, "y": y,
            "rsq": 0.0, "rmse": 1.0, "dcook": 1.0, "to_remove": pd.NA
        })
        x_all, diag_df["x"] = _relabel_dev_periods_long(
            x_all, diag_df["x"].values, sml_flag, analysis_qtr, years_analyzed
        )
        fitted_df["x"] = x_all
        return {"fitted_df": fitted_df, "r_squared": 0.0, "diagnostics": diag_df}

    # --- Transformation functions for exponential ---
    def x_trans(x):
        return x  # no transform on x

    def y_trans(yv):
        return np.log(yv - 1)

    def predict(a, b, x):
        return 1 + np.exp(a) * np.exp(b * x)

    # --- Full-data OLS fit (before removing influential points) ---
    a_full, b_full, _, _, rsq_full = _ols_fit(x_trans(x_gt1), y_trans(y_gt1))
    ycap_full = predict(a_full, b_full, x_gt1)

    # --- Leave-one-out diagnostics ---
    diag_df = _leave_one_out_diagnostics(
        x_gt1, y_gt1, x_trans, y_trans, predict, ycap_full
    )

    # --- Remove influential points and refit ---
    clean = diag_df[diag_df["to_remove"] == "N"]

    if len(clean) <= 2:
        # Too few points remaining — default all fitted values to 1
        ycap_all = np.ones(len(x_all))
        rsq_final = rsq_full if len(clean) > 0 else 0.0
    else:
        x_clean = clean["x"].values
        y_clean = clean["y"].values
        a_clean, b_clean, _, _, rsq_final = _ols_fit(x_trans(x_clean), y_trans(y_clean))
        ycap_all = predict(a_clean, b_clean, x_all)

    # --- Build output ---
    fitted_df = pd.DataFrame({"x": x_all, "y": y, "ycap": ycap_all})

    # Relabel dev periods for long-tailed profiles
    x_all_new, diag_x_new = _relabel_dev_periods_long(
        x_all, diag_df["x"].values, sml_flag, analysis_qtr, years_analyzed
    )
    fitted_df["x"] = x_all_new
    diag_df = diag_df.copy()
    diag_df["x"] = diag_x_new

    return {"fitted_df": fitted_df, "r_squared": rsq_final, "diagnostics": diag_df}


# ---------------------------------------------------------------------------
#  Public: Weibull
# ---------------------------------------------------------------------------

def fit_weibull(y_input, sml_flag, years_analyzed, analysis_qtr):
    """
    Weibull curve fit.

    Linearization:  ln(ln(y / (y - 1))) = a + b * ln(x)
    Prediction:     ŷ = 1 / (1 - exp(-exp(a + b * ln(x))))

    R equivalent: weibullfunc(y1, sml_flag)

    Parameters / Returns: same structure as fit_exponential_decay.
    """
    x_all = _build_dev_periods(sml_flag, years_analyzed, analysis_qtr)
    y = _prepare_ldf_series(y_input, sml_flag, years_analyzed)

    n_pts = min(len(x_all), len(y))
    x_all = x_all[:n_pts]
    y = y[:n_pts]
    mask_gt1 = y > 1.0
    x_gt1 = x_all[mask_gt1]
    y_gt1 = y[mask_gt1]

    if len(x_gt1) == 0:
        fitted_df = pd.DataFrame({"x": x_all, "y": y, "ycap": 1.0})
        diag_df = pd.DataFrame({
            "x": x_all, "y": y,
            "rsq": 0.0, "rmse": 1.0, "dcook": 1.0, "to_remove": pd.NA
        })
        x_all, diag_df["x"] = _relabel_dev_periods_long(
            x_all, diag_df["x"].values, sml_flag, analysis_qtr, years_analyzed
        )
        fitted_df["x"] = x_all
        return {"fitted_df": fitted_df, "r_squared": 0.0, "diagnostics": diag_df}

    # --- Weibull linearization ---
    #   Transform y:  ln(ln( y / (y-1) ))
    #   Transform x:  ln(x)
    #   Back-transform: ŷ = 1 / (1 - exp(-exp(a + b*ln(x))))

    def x_trans(x):
        return np.log(x)

    def y_trans(yv):
        return np.log(np.log(yv / (yv - 1)))

    def predict(a, b, x):
        return 1.0 / (1.0 - np.exp(-np.exp(a + b * np.log(x))))

    # Full-data fit
    a_full, b_full, _, _, rsq_full = _ols_fit(x_trans(x_gt1), y_trans(y_gt1))
    ycap_full = predict(a_full, b_full, x_gt1)

    # Leave-one-out diagnostics
    diag_df = _leave_one_out_diagnostics(
        x_gt1, y_gt1, x_trans, y_trans, predict, ycap_full
    )

    # Remove influential points and refit
    clean = diag_df[diag_df["to_remove"] == "N"]

    if len(clean) <= 2:
        ycap_all = np.ones(len(x_all))
        rsq_final = rsq_full if len(clean) > 0 else 0.0
    else:
        x_clean = clean["x"].values
        y_clean = clean["y"].values
        a_clean, b_clean, _, _, rsq_final = _ols_fit(x_trans(x_clean), y_trans(y_clean))
        ycap_all = predict(a_clean, b_clean, x_all)

    fitted_df = pd.DataFrame({"x": x_all, "y": y, "ycap": ycap_all})

    x_all_new, diag_x_new = _relabel_dev_periods_long(
        x_all, diag_df["x"].values, sml_flag, analysis_qtr, years_analyzed
    )
    fitted_df["x"] = x_all_new
    diag_df = diag_df.copy()
    diag_df["x"] = diag_x_new

    return {"fitted_df": fitted_df, "r_squared": rsq_final, "diagnostics": diag_df}


# ---------------------------------------------------------------------------
#  Public: Power (Sherman curve)
# ---------------------------------------------------------------------------

def fit_power(y_input, sml_flag, years_analyzed, analysis_qtr):
    """
    Power / Sherman curve fit.

    Linearization:  ln(ln(y)) = a + b * x
    Prediction:     ŷ = exp(exp(a + b * x))

    R equivalent: powerfunc(y1, sml_flag)

    NOTE: The Power curve can produce extremely large values for large x.
    If any predicted value exceeds 999 999, all predictions default to 1.0
    (matching the R behaviour).

    Parameters / Returns: same structure as fit_exponential_decay.
    """
    x_all = _build_dev_periods(sml_flag, years_analyzed, analysis_qtr)
    y = _prepare_ldf_series(y_input, sml_flag, years_analyzed)

    n_pts = min(len(x_all), len(y))
    x_all = x_all[:n_pts]
    y = y[:n_pts]
    mask_gt1 = y > 1.0
    x_gt1 = x_all[mask_gt1]
    y_gt1 = y[mask_gt1]

    if len(x_gt1) == 0:
        fitted_df = pd.DataFrame({"x": x_all, "y": y, "ycap": 1.0})
        diag_df = pd.DataFrame({
            "x": x_all, "y": y,
            "rsq": 0.0, "rmse": 1.0, "dcook": 1.0, "to_remove": pd.NA
        })
        x_all, diag_df["x"] = _relabel_dev_periods_long(
            x_all, diag_df["x"].values, sml_flag, analysis_qtr, years_analyzed
        )
        fitted_df["x"] = x_all
        return {"fitted_df": fitted_df, "r_squared": 0.0, "diagnostics": diag_df}

    # --- Power linearization ---
    #   Transform y:  ln(ln(y))      (only valid for y > 1, so ln(y) > 0)
    #   Transform x:  x  (no transform)
    #   Back-transform: ŷ = exp(exp(a + b*x))

    def x_trans(x):
        return x

    def y_trans(yv):
        return np.log(np.log(yv))

    def predict(a, b, x):
        # Guard against overflow: exp(exp(...)) can be enormous
        inner = a + b * x
        # Clamp to avoid inf
        inner = np.clip(inner, -50, 50)
        return np.exp(np.exp(inner))

    # Full-data fit
    a_full, b_full, _, _, rsq_full = _ols_fit(x_trans(x_gt1), y_trans(y_gt1))
    ycap_full = predict(a_full, b_full, x_gt1)

    # Leave-one-out diagnostics
    diag_df = _leave_one_out_diagnostics(
        x_gt1, y_gt1, x_trans, y_trans, predict, ycap_full
    )

    # Remove influential points and refit
    clean = diag_df[diag_df["to_remove"] == "N"]

    if len(clean) <= 2:
        ycap_all = np.ones(len(x_all))
        rsq_final = rsq_full if len(clean) > 0 else 0.0
    else:
        x_clean = clean["x"].values
        y_clean = clean["y"].values
        a_clean, b_clean, _, _, rsq_final = _ols_fit(x_trans(x_clean), y_trans(y_clean))
        ycap_all = predict(a_clean, b_clean, x_all)

        # R check: if any fitted value > 999999, default to 1
        if np.any(ycap_all > 999999):
            ycap_all = np.ones(len(x_all))

    fitted_df = pd.DataFrame({"x": x_all, "y": y, "ycap": ycap_all})

    x_all_new, diag_x_new = _relabel_dev_periods_long(
        x_all, diag_df["x"].values, sml_flag, analysis_qtr, years_analyzed
    )
    fitted_df["x"] = x_all_new
    diag_df = diag_df.copy()
    diag_df["x"] = diag_x_new

    return {"fitted_df": fitted_df, "r_squared": rsq_final, "diagnostics": diag_df}


# ---------------------------------------------------------------------------
#  Public: Inverse Power Curve (IPC)
# ---------------------------------------------------------------------------

# Candidate shift values for the IPC's extra 'c' parameter.
# These are base values — they get multiplied by 12 for long-tailed
# and by 3 for short/medium-tailed.
_C_POSSIBLE_BASE = np.array([-0.5, 0, 1, 3, 5])


def fit_inverse_power(y_input, sml_flag, years_analyzed, analysis_qtr):
    """
    Inverse Power Curve (IPC) fit.

    Linearization:  ln(y - 1) = a + b * ln(c + x)
    Prediction:     ŷ = 1 + exp(a + b * ln(c + x))

    The shift parameter 'c' is optimized over 5 candidate values
    by picking the one that maximises R² on the full dataset.

    R equivalent: IPCfunc(y1, sml_flag)

    Parameters / Returns: same structure as fit_exponential_decay.
    """
    x_all = _build_dev_periods(sml_flag, years_analyzed, analysis_qtr)
    y = _prepare_ldf_series(y_input, sml_flag, years_analyzed)

    # Scale candidate c values by the period multiplier
    if sml_flag == "L":
        c_candidates = _C_POSSIBLE_BASE * 12
    else:
        c_candidates = _C_POSSIBLE_BASE * 3

    n_pts = min(len(x_all), len(y))
    x_all = x_all[:n_pts]
    y = y[:n_pts]
    mask_gt1 = y > 1.0
    x_gt1 = x_all[mask_gt1]
    y_gt1 = y[mask_gt1]

    if len(x_gt1) == 0:
        fitted_df = pd.DataFrame({"x": x_all, "y": y, "ycap": 1.0})
        diag_df = pd.DataFrame({
            "x": x_all, "y": y,
            "rsq": 0.0, "rmse": 1.0, "dcook": 1.0, "to_remove": pd.NA
        })
        x_all, diag_df["x"] = _relabel_dev_periods_long(
            x_all, diag_df["x"].values, sml_flag, analysis_qtr, years_analyzed
        )
        fitted_df["x"] = x_all
        return {"fitted_df": fitted_df, "r_squared": 0.0, "diagnostics": diag_df}

    # --- Step 1: Find the best 'c' value by maximising R² ---
    best_c = c_candidates[0]
    best_c_rsq = -np.inf

    for c_val in c_candidates:
        # Guard: c + x must be positive for log
        if np.any(c_val + x_gt1 <= 0):
            continue
        xt = np.log(c_val + x_gt1)
        yt = np.log(y_gt1 - 1)
        _, _, _, _, rsq = _ols_fit(xt, yt)
        if rsq > best_c_rsq:
            best_c_rsq = rsq
            best_c = c_val

    c_final = best_c

    # --- Build transform / predict functions using the selected c ---
    def x_trans(x):
        return np.log(c_final + x)

    def y_trans(yv):
        return np.log(yv - 1)

    def predict(a, b, x):
        return 1 + np.exp(a + b * np.log(x + c_final))

    # --- Full-data OLS fit with the selected c ---
    a_full, b_full, _, _, rsq_full = _ols_fit(x_trans(x_gt1), y_trans(y_gt1))
    ycap_full = predict(a_full, b_full, x_gt1)

    # --- Leave-one-out diagnostics ---
    # NOTE: The R code has a subtle quirk in the IPC LOO loop — it uses
    # IPC_sxx_noexcl (the full-data sxx) in the denominator for b in the
    # leave-one-out fit.  We replicate that behaviour here for fidelity.
    n = len(x_gt1)
    records = []
    for i in range(n):
        mask = np.ones(n, dtype=bool)
        mask[i] = False
        x_loo = x_gt1[mask]
        y_loo = y_gt1[mask]

        # Transform
        xt_loo = np.log(c_final + x_loo)
        yt_loo = np.log(y_loo - 1)

        # Full-data Sxx (reused as in R)
        xt_full = np.log(c_final + x_gt1)
        sxx_full = np.sum(xt_full ** 2) - (np.sum(xt_full) ** 2) / len(xt_full)

        # LOO OLS — using sxx_full for b (matching R quirk)
        sum_x = np.sum(xt_loo)
        sum_y = np.sum(yt_loo)
        sum_xy = np.sum(xt_loo * yt_loo)
        n_loo = len(xt_loo)
        sxy = sum_xy - sum_x * sum_y / n_loo
        b = sxy / sxx_full if sxx_full != 0 else 1.0
        a = sum_y / n_loo - b * sum_x / n_loo

        ss_res = np.sum((yt_loo - (a + b * xt_loo)) ** 2)
        ss_total = np.sum((yt_loo - sum_y / n_loo) ** 2)
        rsq = 1.0 - (ss_res / ss_total if ss_total != 0 else 1.0)

        y_pred_full = 1 + np.exp(a + b * np.log(x_gt1 + c_final))
        # Match R's recycling: rmse(df_1$y, y_2_cap) where lengths differ (n-1 vs n)
        rmse_val = _compute_rmse_r_style(y_loo, y_pred_full)

        if rmse_val > 0:
            cook_d = np.sum((ycap_full - y_pred_full) ** 2) / (2 * rmse_val ** 2)
        else:
            cook_d = 0.0

        records.append({
            "c_val": c_final,
            "x": x_gt1[i],
            "y": y_gt1[i],
            "rsq": rsq,
            "rmse": rmse_val,
            "dcook": cook_d,
        })

    diag_df = pd.DataFrame(records)

    # Flag influential points
    min_rmse = diag_df["rmse"].min()
    max_rsq = diag_df["rsq"].max()
    diag_df["to_remove"] = np.where(
        (diag_df["rmse"] == min_rmse) |
        (diag_df["rsq"] == max_rsq) |
        (diag_df["dcook"] > 1),
        "Y", "N"
    )

    # --- Remove influential points and refit ---
    clean = diag_df[diag_df["to_remove"] == "N"]

    if len(clean) <= 2:
        ycap_all = np.ones(len(x_all))
        rsq_final = rsq_full if len(clean) > 0 else 0.0
    else:
        x_clean = clean["x"].values
        y_clean = clean["y"].values
        a_clean, b_clean, _, _, rsq_final = _ols_fit(x_trans(x_clean), y_trans(y_clean))
        ycap_all = predict(a_clean, b_clean, x_all)

    fitted_df = pd.DataFrame({"x": x_all, "y": y, "ycap": ycap_all})

    x_all_new, diag_x_new = _relabel_dev_periods_long(
        x_all, diag_df["x"].values, sml_flag, analysis_qtr, years_analyzed
    )
    fitted_df["x"] = x_all_new
    diag_df = diag_df.copy()
    diag_df["x"] = diag_x_new

    return {"fitted_df": fitted_df, "r_squared": rsq_final, "diagnostics": diag_df}


# ---------------------------------------------------------------------------
#  Public: Fit all four curves and rank by R²
# ---------------------------------------------------------------------------

def fit_all_curves(y_input, sml_flag, years_analyzed, analysis_qtr,
                    analysis_year=None, analysis_val_flag=None, profile_id=None):
    """
    Fit all four parametric distributions and return 3 flat DataFrames
    matching the R output structure.

    R equivalent: Lines 844-890 of SLU_main_code.R.txt

    Parameters
    ----------
    y_input          : array-like — LDF values (one per dev period)
    sml_flag         : str — 'S', 'M', or 'L'
    years_analyzed   : int — number of exposure years
    analysis_qtr     : int — quarter being analyzed (1-4)
    analysis_year    : int — analysis year (for identifier columns)
    analysis_val_flag: int — valuation flag (for identifier columns)
    profile_id       : str — profile ID (for identifier columns)

    Returns
    -------
    dict with 3 flat DataFrames:
        'curve_values'       : pd.DataFrame — R's "data" (line 851)
            One row per dev period. Columns: dev_qtr, dev_len,
            Initial_Selection, Exponential_Decay, Inverse_Power, Power, Weibull
        'r_squared'          : pd.DataFrame — R's "r_sq_data" (line 868)
            One row per curve, sorted by R² descending. Columns: Distribution, R_Squared
        'influential_points' : pd.DataFrame — R's "influential_points_data" (line 871)
            One row per dev period. Columns: dev_len, Initial_Selection,
            influential_point_exp_fit, influential_point_weibull_fit,
            influential_point_power_fit, influential_point_ipc_fit
    """
    # Each curve: (name, fit function, influential_points column name)
    curves = [
        ("Exponential_Decay", fit_exponential_decay, "influential_point_exp_fit"),
        ("Weibull",           fit_weibull,            "influential_point_weibull_fit"),
        ("Power",             fit_power,              "influential_point_power_fit"),
        ("Inverse_Power",     fit_inverse_power,      "influential_point_ipc_fit"),
    ]

    # Fit each curve independently
    fit_results = {}
    for name, fit_func, _ in curves:
        try:
            fit_results[name] = fit_func(y_input, sml_flag, years_analyzed, analysis_qtr)
        except Exception:
            fit_results[name] = {
                "fitted_df": pd.DataFrame(),
                "r_squared": 0.0,
                "diagnostics": pd.DataFrame(),
            }

    # ── Build flat DataFrame 1: curve_values (R's "data", line 851) ─────
    # Use Exponential as the base (all curves share the same x and y)
    base = fit_results["Exponential_Decay"]["fitted_df"]
    if base.empty:
        # Fallback: try any non-empty curve
        for name, _, _ in curves:
            if not fit_results[name]["fitted_df"].empty:
                base = fit_results[name]["fitted_df"]
                break

    if not base.empty:
        curve_values = pd.DataFrame()
        curve_values["dev_qtr"] = base["x"] / 3
        curve_values["dev_len"] = base["x"]
        curve_values["Initial_Selection"] = base["y"]
        # Add each curve's fitted values as a column
        for name, _, _ in curves:
            if not fit_results[name]["fitted_df"].empty:
                curve_values[name] = fit_results[name]["fitted_df"]["ycap"].values
            else:
                curve_values[name] = 1.0
        # Replace NaN with 1 (R lines 858-863)
        for name, _, _ in curves:
            curve_values[name] = curve_values[name].fillna(1.0)
    else:
        curve_values = pd.DataFrame()

    # Add identifier columns if provided
    if analysis_year is not None and not curve_values.empty:
        curve_values.insert(0, "res_year", analysis_year)
        curve_values.insert(1, "res_qtr", analysis_qtr)
        curve_values.insert(2, "val_flag", analysis_val_flag)
        curve_values.insert(3, "profile_id", profile_id)

    # ── Build flat DataFrame 2: r_squared (R's "r_sq_data", line 868) ───
    rsq_rows = []
    for name, _, _ in curves:
        rsq_rows.append({
            "Distribution": name,
            "R_Squared": fit_results[name]["r_squared"],
        })
    r_squared = pd.DataFrame(rsq_rows)
    # Sort by R² descending (R line 905)
    r_squared = r_squared.sort_values("R_Squared", ascending=False).reset_index(drop=True)

    # Add identifier columns if provided
    if analysis_year is not None:
        r_squared.insert(0, "res_year", analysis_year)
        r_squared.insert(1, "res_qtr", analysis_qtr)
        r_squared.insert(2, "val_flag", analysis_val_flag)
        r_squared.insert(3, "profile_id", profile_id)

    # ── Build flat DataFrame 3: influential_points (R lines 871-890) ────
    # Start from curve_values base (dev_len + Initial_Selection)
    if not curve_values.empty:
        influential_points = curve_values[["dev_len", "Initial_Selection"]].copy()
        if analysis_year is not None:
            influential_points.insert(0, "res_year", analysis_year)
            influential_points.insert(1, "res_qtr", analysis_qtr)
            influential_points.insert(2, "val_flag", analysis_val_flag)
            influential_points.insert(3, "profile_id", profile_id)

        # Left join each curve's diagnostics to_remove column
        for name, _, col_name in curves:
            diag = fit_results[name].get("diagnostics", pd.DataFrame())
            if not diag.empty and "to_remove" in diag.columns:
                diag_slim = diag[["x", "to_remove"]].rename(
                    columns={"x": "dev_len", "to_remove": col_name}
                )
                influential_points = influential_points.merge(
                    diag_slim, on="dev_len", how="left"
                )
            else:
                influential_points[col_name] = pd.NA
            # Fill NAs with "Not used in curve fit" (R line 886-889)
            influential_points[col_name] = influential_points[col_name].fillna(
                "Not used in curve fit"
            )
    else:
        influential_points = pd.DataFrame()

    return {
        "curve_values": curve_values,
        "r_squared": r_squared,
        "influential_points": influential_points,
    }
