"""
data_reader.py — Reads all input data from SQL database (Azure SQL Server).

Replaces the SQL read operations from SLU_main_code.R (lines ~104–330).
In R these were: dbConnect() + dbGetQuery() calls against vena_stage and afr_analytics schemas.

Supports two modes:
  - Spark JDBC (for Databricks — uses spark.read.format("jdbc"))
  - pandas + pyodbc (for local development / testing)
"""

import pandas as pd


# ---------------------------------------------------------------------------
# SQL query templates
# ---------------------------------------------------------------------------
# Each query below is lifted directly from the R code's dbGetQuery() calls.
# Parameterised with {analysis_year}, {analysis_qtr}, {analysis_val_flag}, etc.

# Incurred loss triangles — all RI types
QUERY_INCURRED_ALL = """
SELECT *
FROM vena_stage.[t_f_vena_SLU_Inc_paid_sparta_grain]
WHERE Vector = 'Incurred Loss'
"""

# Incurred loss triangles — filtered to a single RI type (e.g. 'Gross')
QUERY_INCURRED_BY_RI = """
SELECT *
FROM vena_stage.[t_f_vena_SLU_Inc_paid_sparta_grain]
WHERE [RI Type] = '{ri_type}'
  AND Vector = 'Incurred Loss'
"""

# Paid loss triangles — all RI types
QUERY_PAID_ALL = """
SELECT *
FROM vena_stage.[t_f_vena_SLU_Inc_paid_sparta_grain]
WHERE Vector = 'Paid Loss'
"""

# Paid loss triangles — filtered to a single RI type
QUERY_PAID_BY_RI = """
SELECT *
FROM vena_stage.[t_f_vena_SLU_Inc_paid_sparta_grain]
WHERE [RI Type] = '{ri_type}'
  AND Vector = 'Paid Loss'
"""

# Vena assumption vectors (premiums, loss ratios, recovery ratios, trend indexes)
QUERY_VENA_VECTORS_ALL = """
SELECT *
FROM vena_stage.[t_f_vena_SLU_reserveclass_AY_vectors]
"""

QUERY_VENA_VECTORS_BY_RI = """
SELECT *
FROM vena_stage.[t_f_vena_SLU_reserveclass_AY_vectors]
WHERE [RI Type] = '{ri_type}'
"""

# Incurred percentage developed patterns (used for SML classification)
QUERY_INCURRED_PATTERNS_ALL = """
SELECT *
FROM vena_stage.[t_f_vena_SLU_Inc_paid_prem_patterns]
WHERE Vector = 'Incurred Percentage Developed'
"""

QUERY_INCURRED_PATTERNS_BY_RI = """
SELECT *
FROM vena_stage.[t_f_vena_SLU_Inc_paid_prem_patterns]
WHERE [RI Type] = '{ri_type}'
  AND Vector = 'Incurred Percentage Developed'
"""

# Profile mapping — which profiles to run
QUERY_PROFILE_MAPPING = """
SELECT *
FROM afr_analytics.MBR_profile_mapping
WHERE res_year = {analysis_year}
  AND res_qtr  = {analysis_qtr}
  AND val_flag  = {analysis_val_flag}
  AND SLU_Analysis_Type = 'Valuation'
"""

# Standard columns to keep from the raw Vena extracts
# (R code: select(incurred_raw, c("Reserving Quarter", ...)))
STANDARD_COLUMNS = [
    "Reserving Quarter", "Reserve Class", "Vector", "Branch",
    "Exposure Year", "AY_UY", "Development Period", "RI Type",
    "Version", "PLOB", "Type", "value"
]

# Method name list — used to split vena vectors into method-name rows vs. numeric rows
METHOD_NAME_LIST = [
    "Selected LR Method",
    "Selected Premium Method Name",
    "Selected Ultimate Method",
    "Derived Ultimate Allocation Method",
    "Selected Ultimate Allocation Method",
    "Selected Recovery Ratio Method",
    "Basis for Recovery Ratio Ultimate (Ultimate/IBNR)",
]


# ---------------------------------------------------------------------------
# Core read functions
# ---------------------------------------------------------------------------

def _run_query_spark(spark, query, jdbc_url, jdbc_properties):
    """
    Execute a SQL query using Spark JDBC and return a pandas DataFrame.

    Parameters
    ----------
    spark : SparkSession
        Active Spark session (available in Databricks as `spark`).
    query : str
        SQL query string.
    jdbc_url : str
        JDBC connection URL.
    jdbc_properties : dict
        JDBC connection properties (user, password, driver, etc.).

    Returns
    -------
    pd.DataFrame
    """
    # Spark JDBC reads require wrapping the query as a subquery
    spark_df = spark.read.jdbc(
        url=jdbc_url,
        table=f"({query}) AS subq",
        properties=jdbc_properties
    )
    return spark_df.toPandas()


def _run_query_pyodbc(query, connection_string):
    """
    Execute a SQL query using pyodbc + pandas and return a DataFrame.

    Parameters
    ----------
    query : str
        SQL query string.
    connection_string : str
        ODBC connection string.

    Returns
    -------
    pd.DataFrame
    """
    import pyodbc
    conn = pyodbc.connect(connection_string)
    try:
        df = pd.read_sql(query, conn)
    finally:
        conn.close()
    return df


def run_query(query, config):
    """
    Execute a SQL query using whichever mode is configured (Spark or pyodbc).

    Parameters
    ----------
    query : str
        SQL query to execute.
    config : dict
        Must contain either:
          - 'spark', 'jdbc_url', 'jdbc_properties'  (for Spark mode)
          - 'connection_string'                       (for pyodbc mode)

    Returns
    -------
    pd.DataFrame
    """
    if "spark" in config and config["spark"] is not None:
        return _run_query_spark(
            config["spark"], query, config["jdbc_url"], config["jdbc_properties"]
        )
    else:
        return _run_query_pyodbc(query, config["connection_string"])


# ---------------------------------------------------------------------------
# High-level data loading
# ---------------------------------------------------------------------------

def load_all_data(config):
    """
    Read all base tables from SQL needed by the MBR pipeline.

    This is the Python equivalent of R lines ~114–228 in SLU_main_code.R.
    It reads incurred triangles, paid triangles, vena vectors, vena method names,
    incurred patterns, and the profile mapping.

    Parameters
    ----------
    config : dict
        Pipeline configuration. Must contain:
          - 'ri_type_run': str — 'Gross' or 'Both'
          - 'analysis_year': int
          - 'analysis_qtr': int
          - 'analysis_val_flag': int
          - DB connection keys (see run_query)

    Returns
    -------
    dict with keys:
        'incurred_raw', 'paid_raw', 'vena_data_extract_raw',
        'method_raw_extract', 'incurred_pattern_raw', 'profile_mapping'
    """
    ri_type_run = config["ri_type_run"]
    analysis_year = config["analysis_year"]
    analysis_qtr = config["analysis_qtr"]
    analysis_val_flag = config["analysis_val_flag"]

    # --- Incurred triangles ---
    if ri_type_run == "Both":
        incurred_raw = run_query(QUERY_INCURRED_ALL, config)
    else:
        incurred_raw = run_query(
            QUERY_INCURRED_BY_RI.format(ri_type=ri_type_run), config
        )

    # --- Paid triangles ---
    if ri_type_run == "Both":
        paid_raw = run_query(QUERY_PAID_ALL, config)
    else:
        paid_raw = run_query(
            QUERY_PAID_BY_RI.format(ri_type=ri_type_run), config
        )

    # --- Vena assumption vectors (numeric data) ---
    if ri_type_run == "Both":
        vena_all = run_query(QUERY_VENA_VECTORS_ALL, config)
    else:
        vena_all = run_query(
            QUERY_VENA_VECTORS_BY_RI.format(ri_type=ri_type_run), config
        )

    # Split vena vectors into method-name rows and numeric-data rows
    # R code: method_raw_extract = filter(vena_all, Vector %in% method_name_list)
    #         vena_data_extract_raw = filter(vena_all, !Vector %in% method_name_list)
    method_raw_extract = vena_all[vena_all["Vector"].isin(METHOD_NAME_LIST)].copy()
    vena_data_extract_raw = vena_all[~vena_all["Vector"].isin(METHOD_NAME_LIST)].copy()

    # --- Incurred patterns ---
    if ri_type_run == "Both":
        incurred_pattern_raw = run_query(QUERY_INCURRED_PATTERNS_ALL, config)
    else:
        incurred_pattern_raw = run_query(
            QUERY_INCURRED_PATTERNS_BY_RI.format(ri_type=ri_type_run), config
        )

    # --- Profile mapping (which profiles to process) ---
    profile_mapping = run_query(
        QUERY_PROFILE_MAPPING.format(
            analysis_year=analysis_year,
            analysis_qtr=analysis_qtr,
            analysis_val_flag=analysis_val_flag,
        ),
        config,
    )
    # R code: profile_mapping = filter(profile_mapping, run_flag==1)
    profile_mapping = profile_mapping[profile_mapping["run_flag"] == 1].copy()

    # --- Trim to standard columns (R: select(incurred_raw, c(...))) ---
    for name, df in [
        ("incurred_raw", incurred_raw),
        ("paid_raw", paid_raw),
        ("method_raw_extract", method_raw_extract),
        ("vena_data_extract_raw", vena_data_extract_raw),
        ("incurred_pattern_raw", incurred_pattern_raw),
    ]:
        available = [c for c in STANDARD_COLUMNS if c in df.columns]
        if name == "incurred_raw":
            incurred_raw = df[available].copy()
        elif name == "paid_raw":
            paid_raw = df[available].copy()
        elif name == "method_raw_extract":
            method_raw_extract = df[available].copy()
        elif name == "vena_data_extract_raw":
            vena_data_extract_raw = df[available].copy()
        elif name == "incurred_pattern_raw":
            incurred_pattern_raw = df[available].copy()

    return {
        "incurred_raw": incurred_raw,
        "paid_raw": paid_raw,
        "vena_data_extract_raw": vena_data_extract_raw,
        "method_raw_extract": method_raw_extract,
        "incurred_pattern_raw": incurred_pattern_raw,
        "profile_mapping": profile_mapping,
    }


def get_profile_list(raw_data):
    """
    Return sorted list of unique profile IDs to process.

    R equivalent: sort(unique(profile_mapping$profile_id))

    Parameters
    ----------
    raw_data : dict
        Output of load_all_data(). Must contain 'profile_mapping'.

    Returns
    -------
    list of str
    """
    profile_mapping = raw_data["profile_mapping"]
    # The profile_id column may be named 'profile_id' or 'Profile_ID'
    id_col = "profile_id" if "profile_id" in profile_mapping.columns else "Profile_ID"
    profiles = sorted(profile_mapping[id_col].unique().tolist())
    return profiles


def get_profile_data(profile_id, raw_data, config):
    """
    Filter the pre-loaded raw data down to one specific profile.

    R equivalent: filtering actuals_all_profiles, inputs_vena_all_profiles, etc.
    to profile_id == profile_id_analyzed inside run_mbr().

    Parameters
    ----------
    profile_id : str
        The profile to extract.
    raw_data : dict
        Output of load_all_data().
    config : dict
        Pipeline configuration.

    Returns
    -------
    dict with profile-specific data:
        'incurred_raw', 'paid_raw', 'vena_data', 'vena_methods',
        'incurred_pattern', 'profile_info'
    """
    profile_mapping = raw_data["profile_mapping"]
    id_col = "profile_id" if "profile_id" in profile_mapping.columns else "Profile_ID"

    # Get the profile's row from the mapping table
    profile_info = profile_mapping[profile_mapping[id_col] == profile_id]

    # Filter each raw dataset to this profile
    # R code filters on "Reserve Class" or "Product" matching the profile_id
    def _filter_by_profile(df, profile_col="Reserve Class"):
        if profile_col in df.columns:
            return df[df[profile_col] == profile_id].copy()
        return df.copy()

    incurred = _filter_by_profile(raw_data["incurred_raw"])
    paid = _filter_by_profile(raw_data["paid_raw"])
    vena_data = _filter_by_profile(raw_data["vena_data_extract_raw"])
    vena_methods = _filter_by_profile(raw_data["method_raw_extract"])
    incurred_pattern = _filter_by_profile(raw_data["incurred_pattern_raw"])

    return {
        "incurred_raw": incurred,
        "paid_raw": paid,
        "vena_data": vena_data,
        "vena_methods": vena_methods,
        "incurred_pattern": incurred_pattern,
        "profile_info": profile_info,
    }


def load_sml_mapping(config):
    """
    Load the SML (Short/Medium/Long) classification mapping.

    In R, this is read from a CSV file:
      average_duration_new_profiles = read.csv("SML_Mapping_File_2026_Q3.csv")

    Parameters
    ----------
    config : dict
        Must contain 'sml_mapping_path': path to the SML CSV file.

    Returns
    -------
    pd.DataFrame
        Columns: profile_id, duration_qtrs, duration_years, SML_flag
    """
    sml_path = config.get("sml_mapping_path", "")
    if sml_path:
        average_duration = pd.read_csv(sml_path)
    else:
        # If no path provided, return empty frame with expected columns
        average_duration = pd.DataFrame(
            columns=["profile_id", "duration_qtrs", "duration_years", "SML_flag"]
        )
    # Ensure standard columns exist
    expected_cols = ["profile_id", "duration_qtrs", "duration_years", "SML_flag"]
    for col in expected_cols:
        if col not in average_duration.columns:
            average_duration[col] = None
    return average_duration[expected_cols].copy()
