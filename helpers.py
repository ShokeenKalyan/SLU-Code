"""
helpers.py — Small shared utility functions used across the MBR/SLU pipeline.

These are common operations that multiple modules need:
date/quarter math, safe type conversions, development period mappings, etc.

R equivalent: Various helper snippets scattered throughout SLU_main_code.R
              (e.g., dev period index building, YQ-to-YY conversion, etc.)
"""

import numpy as np
import pandas as pd


# ═══════════════════════════════════════════════════════════════════════════
# DATE AND QUARTER HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def get_reserving_quarter_label(year, qtr):
    """
    Build the reserving quarter label string (e.g., 'Q3 2026').

    R equivalent: paste0('Q', analysis_qtr, ' ', analysis_year)

    Args:
        year (int): Analysis year.
        qtr (int): Analysis quarter (1-4).

    Returns:
        str: Formatted quarter label.
    """
    return f"Q{qtr} {year}"


def get_exposure_year_range(analysis_year, years_analyzed):
    """
    Return the list of exposure years to include in the analysis.

    R equivalent: (analysis_year - years_analyzed + 1) : analysis_year

    Args:
        analysis_year (int): The current analysis year.
        years_analyzed (int): How many years of history to include.

    Returns:
        list[int]: List of exposure years from oldest to newest.
    """
    oldest = analysis_year - years_analyzed + 1
    return list(range(oldest, analysis_year + 1))


def get_dev_period_sequence_yq(analysis_year, analysis_qtr, years_analyzed):
    """
    Generate the sequence of YQ (quarterly) development periods in months.

    R equivalent: seq(3, 3*4*years_analyzed - 3*(4-analysis_qtr), by=3)

    The sequence starts at 3 months and increments by 3 (quarterly).
    For example, with years_analyzed=25, analysis_qtr=3:
    [3, 6, 9, 12, 15, ..., 297]

    Args:
        analysis_year (int): The current analysis year.
        analysis_qtr (int): Analysis quarter (1-4).
        years_analyzed (int): Number of years analyzed.

    Returns:
        list[int]: Development period sequence in months.
    """
    end = 3 * 4 * years_analyzed - 3 * (4 - analysis_qtr)
    return list(range(3, end + 1, 3))


def get_dev_period_sequence_yy(analysis_year, analysis_qtr, years_analyzed):
    """
    Generate the sequence of YY (annual) development periods in months.

    R equivalent: Derived from the YQ-to-YY conversion logic in SLU_main_code.R
                  (lines 413-421)

    Args:
        analysis_year (int): The current analysis year.
        analysis_qtr (int): Analysis quarter (1-4).
        years_analyzed (int): Number of years analyzed.

    Returns:
        list[int]: Development period sequence in months (annual spacing).
    """
    first = analysis_qtr * 3
    return list(range(first, first + 12 * years_analyzed, 12))


def get_exp_year_max_dev_len(analysis_year, analysis_qtr, years_analyzed):
    """
    Build a DataFrame mapping each exposure year to its maximum development
    period (the diagonal of the triangle).

    R equivalent:
        exp_year_dev_len = cbind(exp_year,
                                max_dev_len=seq(3*analysis_qtr,
                                                3*analysis_qtr + 12*(years_analyzed-1),
                                                12))

    Args:
        analysis_year (int): The current analysis year.
        analysis_qtr (int): Analysis quarter (1-4).
        years_analyzed (int): Number of years analyzed.

    Returns:
        pd.DataFrame: Columns ['exp_year', 'max_dev_len'].
    """
    exp_years = list(range(analysis_year, analysis_year - years_analyzed, -1))
    max_dev_lens = list(range(
        3 * analysis_qtr,
        3 * analysis_qtr + 12 * years_analyzed,
        12
    ))
    return pd.DataFrame({
        "exp_year": exp_years,
        "max_dev_len": max_dev_lens[:len(exp_years)]
    })


# ═══════════════════════════════════════════════════════════════════════════
# DEVELOPMENT INDEX MAPPING
# ═══════════════════════════════════════════════════════════════════════════

def build_development_index_df(dev_periods):
    """
    Create a mapping from sequential index (1-based) to actual development
    month values.

    R equivalent:
        development_index_df = data.frame(
            development_index = seq(1:length(unique(actuals_cum$dev_len))),
            development_month = unique(actuals_cum$dev_len)
        )

    Args:
        dev_periods (array-like): Unique development period values (sorted).

    Returns:
        pd.DataFrame: Columns ['development_index', 'development_month'].
    """
    sorted_periods = sorted(set(dev_periods))
    return pd.DataFrame({
        "development_index": list(range(1, len(sorted_periods) + 1)),
        "development_month": sorted_periods
    })


def dev_month_to_index(dev_month, development_index_df):
    """
    Convert a development month value to its 1-based index.

    Args:
        dev_month (int): The development month value (e.g., 3, 6, 9, ...).
        development_index_df (pd.DataFrame): Mapping from build_development_index_df().

    Returns:
        int: 1-based development index, or -1 if not found.
    """
    match = development_index_df.loc[
        development_index_df["development_month"] == dev_month,
        "development_index"
    ]
    if len(match) > 0:
        return int(match.iloc[0])
    return -1


def index_to_dev_month(index, development_index_df):
    """
    Convert a 1-based development index back to its month value.

    Args:
        index (int): 1-based development index.
        development_index_df (pd.DataFrame): Mapping from build_development_index_df().

    Returns:
        int: Development month value, or -1 if not found.
    """
    match = development_index_df.loc[
        development_index_df["development_index"] == index,
        "development_month"
    ]
    if len(match) > 0:
        return int(match.iloc[0])
    return -1


# ═══════════════════════════════════════════════════════════════════════════
# SAFE TYPE CONVERSIONS
# ═══════════════════════════════════════════════════════════════════════════

def safe_to_numeric(series):
    """
    Convert a pandas Series to numeric, coercing errors to NaN.

    R equivalent: as.numeric() which returns NA for non-numeric values.

    Args:
        series (pd.Series): Input series with potentially mixed types.

    Returns:
        pd.Series: Numeric series with NaN for non-convertible values.
    """
    return pd.to_numeric(series, errors="coerce")


def safe_divide(numerator, denominator, default=0.0):
    """
    Divide two values (or arrays), returning a default when the denominator
    is zero or NaN.

    R equivalent: Handles the many cases in the R code where division by zero
                  produces Inf or NaN that are then replaced with 0 or 1.

    Args:
        numerator: Numerator value(s) — scalar, array, or Series.
        denominator: Denominator value(s) — scalar, array, or Series.
        default: Value to return where division is invalid.

    Returns:
        Same type as numerator: Division result with defaults applied.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        result = np.where(
            (denominator == 0) | np.isnan(denominator),
            default,
            np.true_divide(numerator, denominator)
        )
    # Replace any remaining inf/nan
    result = np.where(np.isfinite(result), result, default)
    return result


def replace_na(value, replacement=0.0):
    """
    Replace NaN/None with a default value.

    R equivalent: ifelse(is.na(x), replacement, x)

    Args:
        value: Scalar, array, or pandas Series.
        replacement: Value to substitute for NaN/None.

    Returns:
        Same type as input with NaN/None replaced.
    """
    if isinstance(value, pd.Series):
        return value.fillna(replacement)
    elif isinstance(value, np.ndarray):
        return np.nan_to_num(value, nan=replacement)
    elif value is None or (isinstance(value, float) and np.isnan(value)):
        return replacement
    return value


# ═══════════════════════════════════════════════════════════════════════════
# YQ TO YY CONVERSION
# ═══════════════════════════════════════════════════════════════════════════

def convert_yq_to_yy_dev_period(dev_len, analysis_qtr):
    """
    Convert a quarterly (YQ) development period to its annual (YY) equivalent.

    R equivalent (SLU_main_code.R lines 413-416):
        dev_year_month = ifelse(analysis_qtr==1,
                                analysis_qtr*3 + ceiling((dev_len-3)/12)*12,
                                analysis_qtr*3 + as.integer(dev_len/12)*12)

    Args:
        dev_len (int or array): YQ development period(s) in months.
        analysis_qtr (int): Analysis quarter (1-4).

    Returns:
        int or array: YY development period(s) in months.
    """
    dev_len = np.asarray(dev_len)
    if analysis_qtr == 1:
        return analysis_qtr * 3 + np.ceil((dev_len - 3) / 12).astype(int) * 12
    else:
        return analysis_qtr * 3 + (dev_len // 12) * 12


# ═══════════════════════════════════════════════════════════════════════════
# CDF / LDF CHAIN HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def compute_cdf_from_ldfs(ldfs):
    """
    Compute Cumulative Development Factors (CDFs) from a sequence of LDFs.

    The CDF at position i is the product of all LDFs from position i to the end.
    This is computed as: reverse the LDFs, take cumulative product, reverse back.

    R equivalent:
        cdf_matrix = rev(cumprod(rev(as.vector(wa_matrix))))

    Args:
        ldfs (array-like): Loss Development Factors, one per development period.

    Returns:
        np.ndarray: Cumulative Development Factors.
    """
    ldfs = np.asarray(ldfs, dtype=float)
    return np.flip(np.cumprod(np.flip(ldfs)))


def compute_percent_developed(cdfs):
    """
    Convert CDFs to incurred percentage developed.

    R equivalent: inc_perc_dev_matrix = 100 / cdf_matrix

    Args:
        cdfs (array-like): Cumulative Development Factors.

    Returns:
        np.ndarray: Percentage developed values (0-100 scale).
    """
    cdfs = np.asarray(cdfs, dtype=float)
    return safe_divide(100.0, cdfs, default=100.0)


def compute_cum_percentages(cdfs):
    """
    Convert CDFs to cumulative percentages (0-1 scale).

    This is the fraction form of percent_developed: 1/CDF instead of 100/CDF.

    Args:
        cdfs (array-like): Cumulative Development Factors.

    Returns:
        np.ndarray: Cumulative percentages (0 to 1 scale).
    """
    cdfs = np.asarray(cdfs, dtype=float)
    return safe_divide(1.0, cdfs, default=1.0)


# ═══════════════════════════════════════════════════════════════════════════
# LOGGING / PRINT HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def log_step(profile_id, step_number, message):
    """
    Print a progress message for a pipeline step.

    R equivalent: print(paste('MBR for', profile_id_analyzed, ': ...'))

    Args:
        profile_id (str): The profile being processed.
        step_number (int): Step number in the pipeline.
        message (str): Description of what just completed.
    """
    print(f"MBR for {profile_id} : {step_number}. {message}")
