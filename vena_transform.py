"""
vena_transform.py — Vena Data Transformation Module

Converts raw Vena Excel/CSV exports into structured DataFrames
for the MBR pipeline.

R source: MBR_vena_data_transformation_adhoc.R.txt (467 lines)

Three main transformations:
  1. Incurred/Paid triangle data  → fn_to_transform_incurred_paid()
  2. Method selection data         → fn_to_transform_method_data()
  3. All Vena assumption vectors   → fn_to_transform_vena_all_data()
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional


# ────────────────────────────────────────────────────────────
# 1. Incurred / Paid triangle transformation
#    R equivalent: fn_to_transform_incurred_paid()
# ────────────────────────────────────────────────────────────

def transform_incurred_paid(
    incurred_raw: pd.DataFrame,
    res_year: int,
    res_qtr: int,
    val_flag: int,
    vector_name: str,
) -> pd.DataFrame:
    """
    Transform raw incurred/paid triangle data from a Vena extract table.

    R equivalent: fn_to_transform_incurred_paid(incurred_raw, res_year, res_qtr, val_flag, vector_name)

    Parameters
    ----------
    incurred_raw : pd.DataFrame
        Raw Vena extract with 12 columns (Reserving_Quarter, Product, Vector,
        Branch, Exposure_Year, AY/UY, Development_Period, Measure, Version,
        _PLOB, Type, value).
    res_year : int
        Reserving year (e.g. 2026).
    res_qtr : int
        Reserving quarter (1–4).
    val_flag : int
        Valuation flag (usually 1).
    vector_name : str
        Expected vector name (e.g. 'Incurred Loss' or 'Paid Loss').

    Returns
    -------
    pd.DataFrame
        Cleaned triangle data with columns:
        [res_year, res_qtr, val_flag, Product, Vector, Development Period,
         Exposure Year, Reserving Quarter, Version, Measure, Value]
    """
    df = incurred_raw.copy()

    # Rename columns to standardised names
    df.columns = [
        "Reserving_Quarter", "Product", "Vector", "Branch",
        "Exposure_Year", "AY / UY", "Development_Period",
        "Measure", "Version", "_PLOB", "Type", "value",
    ]

    # Drop _PLOB and Branch columns (not needed downstream)
    df = df.drop(columns=["_PLOB", "Branch"])

    # ── Validation checks ──
    reserving_qtrs = df["Reserving_Quarter"].unique()
    if len(reserving_qtrs) > 1:
        print("error: More than 1 quarter present in data")

    if df["Vector"].isna().any() or df["value"].isna().any():
        print("error: Null values found in Data")

    # Check that only the expected vector is present
    vectors_present = df["Vector"].unique()
    unexpected = [v for v in vectors_present if v != vector_name]
    if unexpected:
        print(f"error: Vector other than {vector_name} is present in data")

    # ── Filter rows ──
    # Keep only rows where Development_Period is not "Adj Period" and Type is "ATT"
    df = df[
        (df["Development_Period"] != "Adj Period") & (df["Type"] == "ATT")
    ].copy()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    # ── Aggregate: group by key columns and sum values ──
    group_cols = [
        "Product", "Vector", "Development_Period",
        "Exposure_Year", "Reserving_Quarter", "Version", "Measure",
    ]
    incurred_tri = (
        df.groupby(group_cols, as_index=False)["value"]
        .sum()
        .rename(columns={"value": "Value"})
    )

    # ── Add metadata columns ──
    incurred_tri["res_year"] = res_year
    incurred_tri["res_qtr"] = res_qtr
    incurred_tri["val_flag"] = val_flag

    # Rename Vector to include "(Att)" suffix
    incurred_tri["Vector"] = f"{vector_name} (Att)"

    # ── Rename and reorder columns to match expected output ──
    incurred_tri = incurred_tri.rename(columns={
        "Development_Period": "Development Period",
        "Exposure_Year": "Exposure Year",
        "Reserving_Quarter": "Reserving Quarter",
    })

    output_cols = [
        "res_year", "res_qtr", "val_flag", "Product", "Vector",
        "Development Period", "Exposure Year", "Reserving Quarter",
        "Version", "Measure", "Value",
    ]
    incurred_tri = incurred_tri[output_cols]

    return incurred_tri


# ────────────────────────────────────────────────────────────
# 2. Method selection data transformation
#    R equivalent: fn_to_transform_method_data()
# ────────────────────────────────────────────────────────────

def transform_method_data(
    method_raw: pd.DataFrame,
    res_year: int,
    res_qtr: int,
    val_flag: int,
    ri_type_run: str,
) -> pd.DataFrame:
    """
    Transform raw method selection data from a Vena extract table.

    R equivalent: fn_to_transform_method_data(method_raw, res_year, res_qtr, val_flag, Ri_type_run)

    Parameters
    ----------
    method_raw : pd.DataFrame
        Raw Vena extract with 12 columns.
    res_year : int
        Reserving year.
    res_qtr : int
        Reserving quarter.
    val_flag : int
        Valuation flag.
    ri_type_run : str
        'Both' if ceded processing is enabled, otherwise 'Gross'.

    Returns
    -------
    pd.DataFrame
        Method selection data pivoted wide, one row per Product × Exposure Year.
    """
    df = method_raw.copy()

    # Rename columns to standardised names
    df.columns = [
        "Reserving_Quarter", "Product", "Vector", "Branch",
        "Exposure_Year", "AY / UY", "Development_Period",
        "Ri_type", "Version", "_PLOB", "Type", "value",
    ]
    df = df.drop(columns=["_PLOB", "Branch", "AY / UY"])

    # ── Validation checks ──
    reserving_qtrs = df["Reserving_Quarter"].unique()
    if len(reserving_qtrs) > 1:
        print("error: More than 1 quarter present in data")

    # The 7 required method vectors
    vector_list = [
        "Selected LR Method",
        "Selected Premium Method Name",
        "Selected Ultimate Method",
        "Derived Ultimate Allocation Method",
        "Selected Ultimate Allocation Method",
        "Selected Recovery Ratio Method",
        "Basis for Recovery Ratio Ultimate (Ultimate/IBNR)",
    ]

    all_vectors = df["Vector"].unique().tolist()
    common_vectors = [v for v in vector_list if v in all_vectors]
    if len(common_vectors) != 7:
        print("error: Required vectors are missing in data")

    # ── Filter: keep only the 7 method vectors, non-numeric values, ATT type ──
    df = df[
        (df["Vector"].isin(vector_list))
        & (~df["value"].apply(_is_numeric))
        & (df["Type"] == "ATT")
    ].copy()

    # De-duplicate on key columns
    dedup_cols = [
        "Reserving_Quarter", "Product", "Vector", "Exposure_Year",
        "Development_Period", "Ri_type", "Version", "Type",
    ]
    df = df.drop_duplicates(subset=dedup_cols, keep="first")

    # ── Pivot: spread Vector column into separate columns ──
    pivot_index = [
        c for c in df.columns if c not in ("Vector", "value")
    ]
    method = df.pivot_table(
        index=pivot_index, columns="Vector", values="value", aggfunc="first"
    ).reset_index()
    # Flatten multi-level column names from pivot
    method.columns = [
        c if isinstance(c, str) else c[-1] if c[-1] else c[0]
        for c in method.columns
    ]

    # ── Handle Ri_type_run flag ──
    if ri_type_run != "Both":
        # If not running ceded, fill in placeholder values
        method["Selected Recovery Ratio Method"] = "NA"
        method["Basis for Recovery Ratio Ultimate (Ultimate/IBNR)"] = "NA"

    # ── Validation: check for nulls in critical columns ──
    if "Selected Premium Method Name" in method.columns and method["Selected Premium Method Name"].isna().all():
        print("error: Null values are present in Selected Premium Method Name")

    if "Selected Ultimate Method" in method.columns and method["Selected Ultimate Method"].isna().all():
        print("error: Null values are present in Selected Ultimate Method")

    # Check all products have the same number of rows
    count_check = method.groupby("Product").size()
    if count_check.min() != count_check.max():
        print("error: 25 rows are not present in data")

    # ── Add metadata columns ──
    method["res_year"] = res_year
    method["res_qtr"] = res_qtr
    method["val_flag"] = val_flag

    # Rename columns to match output schema
    rename_map = {
        "Reserving_Quarter": "Reserving Quarter",
        "Exposure_Year": "Exposure Year",
        "Development_Period": "Development Period",
        "Selected LR Method": "Selected LR Method (Att)",
        "Selected Ultimate Method": "Selected Ultimate Method (Att)",
    }
    method = method.rename(columns=rename_map)

    # Convert Exposure Year to numeric
    method["Exposure Year"] = pd.to_numeric(method["Exposure Year"], errors="coerce")

    # MBR Ultimate Selected Flag — hardcoded to "No" in R
    method["MBR Ultimate Selected Flag"] = "No"

    # ── Select and reorder output columns ──
    output_cols = [
        "res_year", "res_qtr", "val_flag", "Reserving Quarter", "Version",
        "Product", "Exposure Year", "Development Period", "Ri_type",
        "Selected LR Method (Att)", "Selected Premium Method Name",
        "Selected Ultimate Method (Att)", "Derived Ultimate Allocation Method",
        "Selected Ultimate Allocation Method", "MBR Ultimate Selected Flag",
        "Selected Recovery Ratio Method",
        "Basis for Recovery Ratio Ultimate (Ultimate/IBNR)",
    ]
    # Only keep columns that exist (handles 'Both' vs non-'Both' paths)
    output_cols = [c for c in output_cols if c in method.columns]
    method = method[output_cols]

    return method


# ────────────────────────────────────────────────────────────
# 3. Main Vena data transformation (all assumption vectors)
#    R equivalent: fn_to_transform_vena_all_data()
# ────────────────────────────────────────────────────────────

def transform_vena_all_data(
    vena_data: pd.DataFrame,
    incurred_pattern_raw: pd.DataFrame,
    old_new_vector_map: pd.DataFrame,
    analysis_year: int,
    analysis_qtr: int,
    analysis_val_flag: int,
    years_analyzed: int,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Transform all Vena assumption vectors into a wide-format DataFrame
    for the MBR pipeline.

    R equivalent: fn_to_transform_vena_all_data(vena_data, res_year, analysis_qtr,
                  analysis_val_flag, years_analyzed)

    Parameters
    ----------
    vena_data : pd.DataFrame
        Raw Vena data extract with 12 columns.
    incurred_pattern_raw : pd.DataFrame
        Raw incurred percentage developed pattern data from Vena.
    old_new_vector_map : pd.DataFrame
        Mapping table between old and new (ATP) vector names.
        Must have columns: Existing_Vector, ATP_Vector, Vena_data_level,
        Vector_remove_from_R_testing.
    analysis_year : int
        Analysis year (e.g. 2026).
    analysis_qtr : int
        Analysis quarter (1–4).
    analysis_val_flag : int
        Valuation flag (usually 1).
    years_analyzed : int
        Number of years in the analysis window (e.g. 25).

    Returns
    -------
    tuple of (pd.DataFrame, pd.DataFrame)
        [0] vena_data_final — wide-format assumption vectors by profile/exposure year
        [1] vena_data_ldf   — LDF (incurred percentage developed) by profile/dev period
    """
    # ── Prepare the old/new vector mapping ──
    vec_map = old_new_vector_map.copy()
    for col in ["Existing_Vector", "ATP_Vector", "Vena_data_level", "Vector_remove_from_R_testing"]:
        if col in vec_map.columns:
            vec_map[col] = vec_map[col].astype(str)

    # Keep only vectors that are not flagged for removal
    vec_map = vec_map[vec_map["Vector_remove_from_R_testing"] == "No"].copy()
    vec_map = vec_map.drop(columns=["Vector_remove_from_R_testing"])

    # ── Standardise raw vena data column names ──
    df = vena_data.copy()
    df.columns = [
        "Reserving_Quarter", "Product", "Vector", "Branch",
        "Exposure_Year", "AY / UY", "Development_Period",
        "Measure", "Version", "_PLOB", "Type", "value",
    ]
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["Exposure_Year"] = pd.to_numeric(df["Exposure_Year"], errors="coerce")

    # ── Classify vectors by data level (Branch / Profile / Sparta) ──
    only_branch = vec_map.loc[vec_map["Vena_data_level"] == "Branch", "ATP_Vector"].tolist()
    only_profile = vec_map.loc[vec_map["Vena_data_level"] == "Profile", "ATP_Vector"].tolist()
    only_sparta = vec_map.loc[vec_map["Vena_data_level"] == "Sparta", "ATP_Vector"].tolist()

    # ── Aggregate Branch-level vectors to Profile level ──
    # Filter: vectors in Branch list, Branch != "No Branch", _PLOB == "No PLOB"
    branch_df = df[
        (df["Vector"].isin(only_branch))
        & (df["Branch"] != "No Branch")
        & (df["_PLOB"] == "No PLOB")
    ].copy()
    branch_agg = (
        branch_df.groupby(["Product", "Vector", "Exposure_Year", "Measure"], as_index=False)["value"]
        .sum()
    )

    # ── Aggregate Sparta-level vectors to Profile level ──
    # Filter: vectors in Sparta list, Branch != "No Branch", _PLOB != "No PLOB"
    sparta_df = df[
        (df["Vector"].isin(only_sparta))
        & (df["Branch"] != "No Branch")
        & (df["_PLOB"] != "No PLOB")
    ].copy()
    sparta_agg = (
        sparta_df.groupby(["Product", "Vector", "Exposure_Year", "Measure"], as_index=False)["value"]
        .sum()
    )
    sparta_agg = sparta_agg[["Product", "Vector", "Exposure_Year", "Measure", "value"]]

    # ── Filter Profile-level vectors (already at profile level) ──
    profile_df = df[
        (df["Vector"].isin(only_profile))
        & (~df["Vector"].eq("Incurred Percentage Developed"))
        & (df["Branch"] == "No Branch")
        & (df["_PLOB"] == "No PLOB")
    ].copy()
    profile_agg = (
        profile_df.groupby(["Product", "Vector", "Exposure_Year", "Measure"], as_index=False)["value"]
        .sum()
    )

    # ── Combine all three levels into one DataFrame ──
    vena_all_profile = pd.concat([branch_agg, sparta_agg, profile_agg], ignore_index=True)

    # ── Validation checks ──
    # Check reserving quarter matches analysis quarter
    reserving_qtrs = df["Reserving_Quarter"].unique()
    for rq in reserving_qtrs:
        rq_str = str(rq)
        if len(rq_str) > 1 and rq_str[1] != str(analysis_qtr):
            print(f"error: Reserving quarter is not {analysis_qtr}")

    if len(reserving_qtrs) > 1:
        print("error: More than 1 quarter present in data")

    # Check all required vectors are present
    required_vectors = vec_map["ATP_Vector"].tolist()
    all_vectors = vena_all_profile["Vector"].unique().tolist()
    common = [v for v in required_vectors if v in all_vectors]
    if len(common) != len(required_vectors):
        print("error: Required vectors are missing in data")

    # ── Process LDF data (incurred percentage developed pattern) ──
    ldf_df = incurred_pattern_raw.copy()

    # Filter: Branch == "No Branch" and PLOB == "No PLOB"
    # Handle different possible column name formats
    branch_col = _find_column(ldf_df, ["Branch"])
    plob_col = _find_column(ldf_df, ["PLOB", "_PLOB"])
    if branch_col and plob_col:
        ldf_df = ldf_df[(ldf_df[branch_col] == "No Branch") & (ldf_df[plob_col] == "No PLOB")].copy()

    # Select and rename relevant columns
    ldf_cols_map = {
        "Version": "Version",
        "Reserving Quarter": "Reserving_Quarter",
        "Reserve Class": "Product",
        "Branch": "Branch",
        "Exposure Year": "Exposure_Year",
        "Development Period": "Development_Period",
        "RI Type": "Measure",
        "Vector": "Vector",
        "value": "value",
    }
    # Only rename columns that exist
    existing_renames = {k: v for k, v in ldf_cols_map.items() if k in ldf_df.columns}
    ldf_df = ldf_df[list(existing_renames.keys())].rename(columns=existing_renames)

    # Remove non-numeric Development_Period rows (like DFM_Name, ResQ Project, etc.)
    dummy_list = ["DFM_Name", "ResQ Project", "ResQ Class", "No Development Period"]
    ldf_df = ldf_df[~ldf_df["Development_Period"].isin(dummy_list)].copy()
    ldf_df["Development_Period"] = pd.to_numeric(ldf_df["Development_Period"], errors="coerce")

    # Keep a copy of the original LDF data for later reuse
    ldf_original = ldf_df.copy()

    # ── Build exposure-year-to-development-period mapping ──
    exp_years = list(range(analysis_year, analysis_year - years_analyzed, -1))
    dev_periods = list(range(analysis_qtr * 3, 12 * years_analyzed + 1, 12))
    # Truncate to same length (in case of mismatch)
    min_len = min(len(exp_years), len(dev_periods))
    exp_year_dev_month = pd.DataFrame({
        "Exposure_Year": exp_years[:min_len],
        "Development_Period": dev_periods[:min_len],
    })

    # ── Map exposure years to LDF data using development period ──
    ldf_df = ldf_df.merge(exp_year_dev_month, on="Development_Period", how="left", suffixes=("_orig", ""))

    # Drop original Exposure_Year if it was kept, and use the mapped one
    if "Exposure_Year_orig" in ldf_df.columns:
        ldf_df = ldf_df.drop(columns=["Exposure_Year_orig"])

    # Remove rows where Exposure_Year could not be mapped (set to -10, then filter)
    ldf_df["Exposure_Year"] = ldf_df["Exposure_Year"].fillna(-10)
    ldf_df = ldf_df[ldf_df["Exposure_Year"] != -10].copy()

    # ── Build the full cross-join combination grid ──
    # (Product × Vector × Exposure_Year × Measure) with default value = 0
    products = df["Product"].unique().tolist()
    vectors = vec_map["ATP_Vector"].unique().tolist()
    ri_types = vena_all_profile["Measure"].unique().tolist()

    exp_year_comb = _cross_join(
        pd.DataFrame({"Product": products}),
        pd.DataFrame({"Vector": vectors}),
        pd.DataFrame({"Exposure_Year": exp_years}),
        pd.DataFrame({"Measure": ri_types}),
    )
    exp_year_comb["value"] = 0
    exp_year_comb = exp_year_comb.drop_duplicates()

    # ── Left-join actual vena data onto the grid ──
    vena_dummy = vena_all_profile[["Product", "Vector", "Exposure_Year", "Measure", "value"]].copy()
    vena_dummy = vena_dummy.drop_duplicates(subset=["Product", "Vector", "Exposure_Year", "Measure"], keep="first")

    # Ensure consistent types for join
    for col in ["Product", "Vector", "Measure"]:
        exp_year_comb[col] = exp_year_comb[col].astype(str)
        vena_dummy[col] = vena_dummy[col].astype(str)

    exp_year_comb = exp_year_comb.merge(
        vena_dummy, on=["Product", "Vector", "Exposure_Year", "Measure"],
        how="left", suffixes=("_default", "_actual"),
    )

    # Use actual value where available, otherwise keep the default (0)
    exp_year_comb["value"] = np.where(
        exp_year_comb["value_actual"].notna(),
        exp_year_comb["value_actual"],
        exp_year_comb["value_default"],
    )
    exp_year_comb = exp_year_comb.drop(columns=["value_default", "value_actual"])

    # ── Apply old→new vector name mapping ──
    vec_name_map = vec_map[["ATP_Vector", "Existing_Vector"]].rename(columns={"ATP_Vector": "Vector"})
    exp_year_comb = exp_year_comb.merge(vec_name_map, on="Vector", how="left")

    # Add development period from the exposure-year mapping
    exp_year_comb = exp_year_comb.merge(exp_year_dev_month, on="Exposure_Year", how="left")

    # Filter out vectors not in the mapping
    exp_year_comb = exp_year_comb[exp_year_comb["Existing_Vector"].notna()].copy()
    exp_year_comb = exp_year_comb[exp_year_comb["Existing_Vector"] != "NA"].copy()

    # Apply old→new mapping to LDF data too
    ldf_df = ldf_df.merge(vec_name_map, on="Vector", how="left")
    ldf_df = ldf_df.drop(columns=["Vector"]).rename(columns={"Existing_Vector": "Vector"})

    # Replace Vector column in exp_year_comb with the mapped (old) name
    exp_year_comb = exp_year_comb.drop(columns=["Vector"]).rename(columns={"Existing_Vector": "Vector"})

    # ── Add metadata columns ──
    reserving_quarter_value = df["Reserving_Quarter"].unique()[0] if len(df["Reserving_Quarter"].unique()) > 0 else ""
    version_value = "Baseline-H1"

    for target_df in [exp_year_comb, ldf_df]:
        target_df["res_year"] = analysis_year
        target_df["res_qtr"] = analysis_qtr
        target_df["val_flag"] = analysis_val_flag
        target_df["Reserving Quarter"] = reserving_quarter_value
        target_df["Version"] = version_value

    # ── Format the final output DataFrames ──
    common_cols = [
        "res_year", "res_qtr", "val_flag", "Vector", "Reserving Quarter",
        "Version", "Product", "Exposure_Year", "Development_Period", "Measure", "value",
    ]

    # Rename to output schema
    out_rename = {
        "Exposure_Year": "Exposure Year",
        "Development_Period": "Development Period",
        "Measure": "Ri_type",
    }

    vena_final = exp_year_comb[[c for c in common_cols if c in exp_year_comb.columns]].copy()
    vena_final = vena_final.rename(columns=out_rename)
    ldf_out = ldf_df[[c for c in common_cols if c in ldf_df.columns]].copy()
    ldf_out = ldf_out.rename(columns=out_rename)

    # ── Pivot both DataFrames from long to wide (Vector → columns) ──
    # Remove "Incurred Percentage Developed (Att)" from the main frame before pivoting
    vena_final = vena_final[vena_final["Vector"] != "Incurred Percentage Developed (Att)"].copy()

    # De-duplicate before pivot
    pivot_index = [c for c in vena_final.columns if c not in ("Vector", "value")]
    vena_final = vena_final.drop_duplicates(subset=pivot_index + ["Vector"], keep="first")

    vena_data_final = vena_final.pivot_table(
        index=pivot_index, columns="Vector", values="value", aggfunc="first"
    ).reset_index()
    vena_data_final.columns = [c if isinstance(c, str) else c for c in vena_data_final.columns]
    # Replace NaN with 0 in the pivoted assumption columns
    vena_data_final = vena_data_final.fillna(0)

    # Pivot LDF data
    ldf_pivot_index = [c for c in ldf_out.columns if c not in ("Vector", "value")]
    ldf_out = ldf_out.drop_duplicates(subset=ldf_pivot_index + ["Vector"], keep="first")
    vena_data_ldf = ldf_out.pivot_table(
        index=ldf_pivot_index, columns="Vector", values="value", aggfunc="first"
    ).reset_index()
    vena_data_ldf.columns = [c if isinstance(c, str) else c for c in vena_data_ldf.columns]

    # ── Join LDF column back into the main data ──
    ipd_col = "Incurred Percentage Developed (Att)"
    if ipd_col in vena_data_ldf.columns:
        ldf_join = vena_data_ldf[["Product", "Exposure Year", "Ri_type", ipd_col]].copy()
        # De-duplicate before joining
        ldf_join = ldf_join.drop_duplicates(subset=["Product", "Exposure Year", "Ri_type"], keep="first")

        vena_data_final = vena_data_final.merge(
            ldf_join, on=["Product", "Exposure Year", "Ri_type"], how="left"
        )
        # Default to 1.0 where no LDF was matched
        vena_data_final[ipd_col] = vena_data_final[ipd_col].fillna(1.0)

    # ── Validation: check row counts per product ──
    if "Product" in vena_data_final.columns:
        count_check = vena_data_final.groupby("Product").size()
        if count_check.min() != count_check.max():
            print("error: 25 rows are not present in Vena data")

    # ── Build the separate LDF output (by development period, not exposure year) ──
    ldf_dev_period = ldf_original.copy()
    ldf_dev_period["Exposure_Year"] = 0

    ldf_dev_period["res_year"] = analysis_year
    ldf_dev_period["res_qtr"] = analysis_qtr
    ldf_dev_period["val_flag"] = analysis_val_flag
    ldf_dev_period["Reserving Quarter"] = reserving_quarter_value
    ldf_dev_period["Version"] = version_value

    ldf_dev_cols = [
        "res_year", "res_qtr", "val_flag", "Reserving Quarter", "Version",
        "Product", "Exposure_Year", "Development_Period", "Measure", "value",
    ]
    ldf_dev_period = ldf_dev_period[[c for c in ldf_dev_cols if c in ldf_dev_period.columns]].copy()
    ldf_dev_period = ldf_dev_period.rename(columns={
        "Exposure_Year": "Exposure Year",
        "Development_Period": "Development Period",
        "Measure": "Ri_type",
        "value": "Incurred Percentage Developed (Att)",
    })

    # Remove rows with NA in Development Period
    ldf_dev_period = ldf_dev_period[ldf_dev_period["Development Period"].notna()].copy()

    return vena_data_final, ldf_dev_period


# ────────────────────────────────────────────────────────────
# Public interface functions
# ────────────────────────────────────────────────────────────

def process_vena_data(config: dict) -> dict:
    """
    Main entry point — reads and transforms all Vena data.

    Orchestrates all three transformations and returns a dict
    containing the cleaned DataFrames.

    Parameters
    ----------
    config : dict
        Must contain keys:
          - vena_data_extract_raw (pd.DataFrame): raw Vena MBR data
          - incurred_pattern_raw (pd.DataFrame): raw incurred pattern data
          - old_new_vector_map (pd.DataFrame): vector name mapping
          - method_raw_extract (pd.DataFrame): raw method selection data
          - incurred_raw (pd.DataFrame or None): raw incurred triangle data
          - paid_raw (pd.DataFrame or None): raw paid triangle data
          - analysis_year (int)
          - analysis_qtr (int)
          - analysis_val_flag (int)
          - years_analyzed (int)
          - ri_type_run (str): 'Both' or 'Gross'

    Returns
    -------
    dict with keys:
        'vena_vectors'    : wide-format assumption vectors (pd.DataFrame)
        'vena_ldf'        : LDF data by development period (pd.DataFrame)
        'method_data'     : method selection data (pd.DataFrame)
        'incurred_tri'    : transformed incurred triangle (pd.DataFrame or None)
        'paid_tri'        : transformed paid triangle (pd.DataFrame or None)
    """
    result = {}

    # 1. Transform all Vena assumption vectors
    vena_vectors, vena_ldf = transform_vena_all_data(
        vena_data=config["vena_data_extract_raw"],
        incurred_pattern_raw=config["incurred_pattern_raw"],
        old_new_vector_map=config["old_new_vector_map"],
        analysis_year=config["analysis_year"],
        analysis_qtr=config["analysis_qtr"],
        analysis_val_flag=config["analysis_val_flag"],
        years_analyzed=config["years_analyzed"],
    )
    result["vena_vectors"] = vena_vectors
    result["vena_ldf"] = vena_ldf

    # 2. Transform method selection data
    if config.get("method_raw_extract") is not None:
        result["method_data"] = transform_method_data(
            method_raw=config["method_raw_extract"],
            res_year=config["analysis_year"],
            res_qtr=config["analysis_qtr"],
            val_flag=config["analysis_val_flag"],
            ri_type_run=config.get("ri_type_run", "Both"),
        )
    else:
        result["method_data"] = None

    # 3. Transform incurred triangle data (if provided)
    if config.get("incurred_raw") is not None:
        result["incurred_tri"] = transform_incurred_paid(
            incurred_raw=config["incurred_raw"],
            res_year=config["analysis_year"],
            res_qtr=config["analysis_qtr"],
            val_flag=config["analysis_val_flag"],
            vector_name="Incurred Loss",
        )
    else:
        result["incurred_tri"] = None

    # 4. Transform paid triangle data (if provided)
    if config.get("paid_raw") is not None:
        result["paid_tri"] = transform_incurred_paid(
            incurred_raw=config["paid_raw"],
            res_year=config["analysis_year"],
            res_qtr=config["analysis_qtr"],
            val_flag=config["analysis_val_flag"],
            vector_name="Paid Loss",
        )
    else:
        result["paid_tri"] = None

    return result


def get_profile_overrides(profile_id: str, vena_data: dict) -> dict:
    """
    Extract Vena overrides for a single profile.

    Parameters
    ----------
    profile_id : str
        The profile identifier (Product column value).
    vena_data : dict
        Output from process_vena_data().

    Returns
    -------
    dict with keys:
        'vectors' : assumption vectors for this profile (pd.DataFrame)
        'ldf'     : LDF data for this profile (pd.DataFrame)
        'methods' : method selections for this profile (pd.DataFrame or None)
    """
    overrides = {}

    # Filter vena vectors to this profile
    vv = vena_data.get("vena_vectors")
    if vv is not None and "Product" in vv.columns:
        overrides["vectors"] = vv[vv["Product"] == profile_id].copy()
    else:
        overrides["vectors"] = pd.DataFrame()

    # Filter LDF data to this profile
    ldf = vena_data.get("vena_ldf")
    if ldf is not None and "Product" in ldf.columns:
        overrides["ldf"] = ldf[ldf["Product"] == profile_id].copy()
    else:
        overrides["ldf"] = pd.DataFrame()

    # Filter method selections to this profile
    md = vena_data.get("method_data")
    if md is not None and "Product" in md.columns:
        overrides["methods"] = md[md["Product"] == profile_id].copy()
    else:
        overrides["methods"] = None

    return overrides


# ────────────────────────────────────────────────────────────
# Private helper functions
# ────────────────────────────────────────────────────────────

def _is_numeric(val) -> bool:
    """Check if a value is numeric (used to filter non-numeric method names)."""
    try:
        float(val)
        return True
    except (ValueError, TypeError):
        return False


def _find_column(df: pd.DataFrame, candidates: list) -> Optional[str]:
    """Return the first matching column name from a list of candidates."""
    for name in candidates:
        if name in df.columns:
            return name
    return None


def _cross_join(*dataframes: pd.DataFrame) -> pd.DataFrame:
    """
    Compute the cross product (cartesian join) of multiple DataFrames.
    R equivalent: merge(df1, df2, by = NULL)
    """
    result = dataframes[0].copy()
    result["_cross_key"] = 1
    for other_df in dataframes[1:]:
        other = other_df.copy()
        other["_cross_key"] = 1
        result = result.merge(other, on="_cross_key")
    result = result.drop(columns=["_cross_key"])
    return result
