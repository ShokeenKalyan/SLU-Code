"""
ceded.py — Ceded / reinsurance utility functions.

R source: MBR_ceded_all_calculations.R

These are helper functions used during the ceded/reinsurance stage of the
pipeline. The main ceded calculations (ceded age-to-age factors, ceded
ultimates, ceded method selection) are orchestrated in main.py using the
same actuarial_methods and method_selection modules applied to ceded data.
These helpers handle data preparation: replicating gross data across
reinsurance types and filtering to valid ceded combinations.
"""

import pandas as pd


# =============================================================================
# Replicate Reinsurance Types
# R source: fn_replicate_ri_type_df()
# =============================================================================

def replicate_ri_type(gross_df, ri_type_df):
    """
    Cross-join a gross DataFrame with all reinsurance types.

    This creates one copy of the gross data for each Ri_type (reinsurance type),
    so that downstream ceded calculations can be performed per reinsurance type.

    R equivalent: fn_replicate_ri_type_df()

    Parameters
    ----------
    gross_df : pd.DataFrame
        Gross-side data (any structure — ultimates, triangles, etc.).
    ri_type_df : pd.DataFrame
        DataFrame with a column 'Ri_type' listing all reinsurance types
        and a column 'temp' = 1 for cross-join.

    Returns
    -------
    pd.DataFrame
        The gross data replicated for each reinsurance type, with 'Ri_type' column added.
    """
    # Add a temporary join key for cross-join
    gross_copy = gross_df.copy()
    gross_copy["_temp_join"] = 1

    ri_copy = ri_type_df.copy()
    ri_copy["_temp_join"] = 1

    # Cross-join: every row of gross × every Ri_type
    result = gross_copy.merge(ri_copy, on="_temp_join", how="inner")
    result = result.drop(columns=["_temp_join"])

    return result


# =============================================================================
# Change Ri_type to String
# R source: fn_change_to_character()
# =============================================================================

def change_ri_type_to_string(df):
    """
    Ensure the Ri_type column is of string type.

    R equivalent: fn_change_to_character()

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with an 'Ri_type' column.

    Returns
    -------
    pd.DataFrame
        Same DataFrame with Ri_type cast to str.
    """
    result = df.copy()
    result["Ri_type"] = result["Ri_type"].astype(str)
    return result


# =============================================================================
# Apply Valid-Ceded Mapping (profile_id-based join)
# R source: fn_apply_non_val_ceded_map()
# =============================================================================

def apply_ceded_mapping(df, ceded_profile_mapping):
    """
    Filter a DataFrame to keep only valid ceded (profile_id × Ri_type) combinations.

    Joins on profile_id == Product and Ri_type, then keeps only rows where
    is_valid_ceded == 1. This removes invalid reinsurance type / product
    pairs from export outputs.

    R equivalent: fn_apply_non_val_ceded_map()

    Parameters
    ----------
    df : pd.DataFrame
        Data with columns 'profile_id' and 'Ri_type'.
    ceded_profile_mapping : pd.DataFrame
        Mapping table with columns ['Product', 'Ri_type', 'is_valid_ceded'].

    Returns
    -------
    pd.DataFrame
        Filtered to valid ceded combinations only. 'is_valid_ceded' column removed.
    """
    mapping_cols = ceded_profile_mapping[["Product", "Ri_type", "is_valid_ceded"]].copy()

    result = df.merge(
        mapping_cols,
        left_on=["profile_id", "Ri_type"],
        right_on=["Product", "Ri_type"],
        how="left",
    )

    # Keep only valid ceded rows
    result = result[result["is_valid_ceded"] == 1].copy()

    # Clean up: drop the mapping columns
    cols_to_drop = ["is_valid_ceded"]
    if "Product" in result.columns and "profile_id" in result.columns:
        cols_to_drop.append("Product")
    result = result.drop(columns=[c for c in cols_to_drop if c in result.columns])

    return result


# =============================================================================
# Apply Valid-Ceded Mapping (Product-based join)
# R source: fn_apply_non_val_ceded_map_1()
# =============================================================================

def apply_ceded_mapping_by_product(df, ceded_profile_mapping):
    """
    Same as apply_ceded_mapping(), but joins on 'Product' column instead of
    'profile_id'. Used when the DataFrame already has a 'Product' column
    rather than 'profile_id'.

    R equivalent: fn_apply_non_val_ceded_map_1()

    Parameters
    ----------
    df : pd.DataFrame
        Data with columns 'Product' and 'Ri_type'.
    ceded_profile_mapping : pd.DataFrame
        Mapping table with columns ['Product', 'Ri_type', 'is_valid_ceded'].

    Returns
    -------
    pd.DataFrame
        Filtered to valid ceded combinations only.
    """
    mapping_cols = ceded_profile_mapping[["Product", "Ri_type", "is_valid_ceded"]].copy()

    result = df.merge(
        mapping_cols,
        on=["Product", "Ri_type"],
        how="left",
    )

    result = result[result["is_valid_ceded"] == 1].copy()
    result = result.drop(columns=["is_valid_ceded"], errors="ignore")

    return result
