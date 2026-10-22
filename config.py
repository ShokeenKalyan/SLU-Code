"""
config.py — All configuration settings for the MBR/SLU pipeline.

R equivalent: Top section of SLU_main_code.R (lines 1–98), plus various
              threshold constants used throughout the codebase.

This module defines every tuneable parameter in one place.
Call load_config() to get a dictionary with all settings.
"""


def load_config():
    """
    Build and return the full configuration dictionary.

    In R, these values are scattered as global variables across the top of
    SLU_main_code.R. Here they are gathered into a single dictionary so
    every function can receive them explicitly instead of reading globals.

    Returns:
        dict: Configuration dictionary with all pipeline parameters.
    """

    config = {}

    # ── Analysis Period ──────────────────────────────────────────────────
    # UPDATE these each quarter before running the pipeline.
    # R equivalent: analysis_year, analysis_qtr, analysis_val_flag

    config["analysis_year"] = 2026
    config["analysis_qtr"] = 3
    config["analysis_val_flag"] = 1
    config["SLU_analysis_type"] = "Valuation"

    # ── Reinsurance Run Type ─────────────────────────────────────────────
    # 'Gross' = gross only; 'Both' = gross + ceded calculations
    # R equivalent: Ri_type_run

    config["ri_type_run"] = "Gross"

    # ── Years Analyzed (lookback windows by SML class) ───────────────────
    # How many years of history to include in the analysis.
    # Short-tailed lines use fewer years; Long-tailed use more.
    # R equivalent: years_analyzed, years_analyzed_S_tailed, etc.

    config["years_analyzed"] = 25
    config["years_analyzed_S"] = 10      # Short-tailed profiles
    config["years_analyzed_M"] = 14      # Medium-tailed profiles
    config["years_analyzed_L"] = 24      # Long-tailed profiles
    config["years_capped"] = 14          # Max years cap for S/M profiles

    # ── Volume-Weighted Average Periods (by SML class) ───────────────────
    # Which "best-N" windows to test for each SML class.
    # The best N (lowest RMSE) becomes the selected VW average.
    # R equivalent: VW_Averages_n assignments inside run_mbr()

    config["vw_periods_S"] = [3, 4, 5]
    config["vw_periods_M"] = [3, 4, 5, 6, 7, 8, 9, 10, 24]
    config["vw_periods_L"] = [5, 6, 7, 8, 9, 10, 24]

    # ── Iteration Algorithm Parameters ───────────────────────────────────
    # Controls the recursive tree-search that finds optimal LDF sequences.
    # R equivalent: iteration_num_threshold, default_last_index, default_first_index

    config["iteration_num_threshold"] = 11000   # Max iterations before stopping
    config["default_last_index"] = 20            # Default end index for algorithm
    config["default_first_index"] = 1            # Default start index for algorithm
    config["initial_curves_to_use"] = 2          # Start with top-2 curves; retry with 4 if no convergence
    config["total_curves_available"] = 4         # Total curve models (Exp, Weibull, Power, InvPower)
    config["r_squared_threshold"] = 0.6          # Minimum R² for a curve to be considered usable

    # ── Factor-One Index Parameters ──────────────────────────────────────
    # Determines when LDFs stabilize at 1.0 (no further development).
    # R equivalent: factor_1_index_threshold

    config["factor_1_index_threshold"] = 2       # % threshold for factor-one detection

    # ── Negative Development / Less-Than-One Factor Parameters ───────────
    # Controls how the pipeline handles LDFs that drop below 1.0.
    # R equivalent: consecutive_less_than_one_num, prop_less_than_one_factors_threshold, etc.

    config["consecutive_less_than_one_num"] = 5              # Consecutive sub-1.0 factors to trigger
    config["prop_less_than_one_factors_threshold"] = 0.4     # Proportion threshold (40%)
    config["incr_pct_change_threshold"] = 0.05               # Incremental % change threshold (5%)

    # ── Outlier Detection Parameters ─────────────────────────────────────
    # Minimum data points needed before outlier detection is applied.
    # R equivalent: outlier_detection_min_points

    config["outlier_detection_min_points"] = 4

    # ── Method Selection Thresholds ──────────────────────────────────────
    # Rules for which actuarial method to use based on development maturity.
    # R equivalent: thresholds used inside fn_select_ultimate_by_exp_year()

    config["method_dfm_threshold"] = 0.85        # >= 85% developed → use DFM
    config["method_lr_threshold"] = 0.40          # <= 40% developed → use LR
    config["pattern_threshold"] = 0.6             # Premium Recovery Ratio threshold for ceded

    # ── Database Connection ──────────────────────────────────────────────
    # Connection details for the Actuarial Datastore.
    # On Databricks, these are used to build a JDBC connection string.
    # R equivalent: dbConnect() call with server/database/UID/PWD
    #
    # NOTE: In production on Databricks, you would typically use
    #       Databricks secrets or environment variables instead of
    #       hardcoding credentials here.

    config["db_server"] = "z-xlc-0277-actu-pr-ue2-sql01-actuarialdatastore.database.windows.net"
    config["db_name"] = "z-xlc-0277-actu-pr-ue2-sdb01-actuarialdatastore"
    config["db_driver"] = "ODBC Driver 17 for SQL Server"
    config["db_schema_input"] = "vena_stage"         # Schema for input tables
    config["db_schema_output"] = "afr_analytics"     # Schema for output tables

    # ── SQL Table Names ──────────────────────────────────────────────────
    # All table names referenced in the pipeline.
    # R equivalent: table names in dbGetQuery() and sqlSave() calls

    config["table_incurred_paid"] = "t_f_vena_SLU_Inc_paid_sparta_grain"
    config["table_reserve_vectors"] = "t_f_vena_SLU_reserveclass_AY_vectors"
    config["table_incurred_patterns"] = "t_f_vena_SLU_Inc_paid_prem_patterns"
    config["table_profile_mapping"] = "MBR_profile_mapping"

    # ── Delta Table Checkpoints ──────────────────────────────────────────
    # When True, intermediate results are saved as Delta tables after each
    # pipeline step, so you can restart from any checkpoint.
    # When False, everything runs in memory (re-run from top if session dies).
    # Set to True once you have write access in Databricks.

    config["use_delta_checkpoints"] = False
    config["delta_schema"] = "mbr_dev"              # Schema for checkpoint tables

    # ── Output Paths ─────────────────────────────────────────────────────
    # File paths for Excel and CSV outputs.
    # R equivalent: file paths used in write.xlsx() and write.csv() calls

    config["output_excel_path"] = "/mnt/mbr/output/"
    config["output_vena_csv_path"] = "/mnt/mbr/vena/"
    config["error_log_path"] = "/mnt/mbr/logs/"

    # ── Miscellaneous ────────────────────────────────────────────────────

    config["seed_value"] = 123                      # Random seed for reproducibility
    config["parallel_workers"] = 10                  # Number of parallel workers (for Spark)

    # ── Derived Values ───────────────────────────────────────────────────
    # These are computed from the settings above. Do not edit directly.

    config["last_dev_month"] = (
        4 * config["years_analyzed"] - (4 - config["analysis_qtr"])
    )

    # Method name list used to separate method-name vectors from numeric vectors
    # R equivalent: method_name_list
    config["method_name_list"] = [
        "Selected LR Method",
        "Selected Premium Method Name",
        "Selected Ultimate Method",
        "Derived Ultimate Allocation Method",
        "Selected Ultimate Allocation Method",
        "Selected Recovery Ratio Method",
        "Basis for Recovery Ratio Ultimate (Ultimate/IBNR)",
    ]

    return config


def get_years_analyzed_for_sml(config, sml_flag):
    """
    Return the number of lookback years for a given SML class.

    R equivalent: years_analyzed_S_tailed / years_analyzed_M_tailed / years_analyzed_L_tailed

    Args:
        config (dict): Configuration dictionary from load_config().
        sml_flag (str): One of 'S', 'M', or 'L'.

    Returns:
        int: Number of years to analyze for this SML class.
    """
    lookup = {
        "S": config["years_analyzed_S"],
        "M": config["years_analyzed_M"],
        "L": config["years_analyzed_L"],
    }
    return lookup.get(sml_flag, config["years_analyzed"])


def get_vw_periods_for_sml(config, sml_flag):
    """
    Return the list of VW average periods to test for a given SML class.

    R equivalent: VW_Averages_n assignments inside run_mbr()

    Args:
        config (dict): Configuration dictionary from load_config().
        sml_flag (str): One of 'S', 'M', or 'L'.

    Returns:
        list[int]: Volume-weighted average period candidates.
    """
    lookup = {
        "S": config["vw_periods_S"],
        "M": config["vw_periods_M"],
        "L": config["vw_periods_L"],
    }
    return lookup.get(sml_flag, config["vw_periods_M"])


def get_last_dev_period_index(config, sml_flag):
    """
    Return the last development period index based on SML class.

    Long-tailed profiles use year-year (YY) triangles, so the index equals
    the number of years analyzed. Short/Medium use quarter-quarter (YQ),
    so the index is 4 * years_analyzed - (4 - analysis_qtr).

    R equivalent: last_dev_period_index assignments inside run_mbr()

    Args:
        config (dict): Configuration dictionary from load_config().
        sml_flag (str): One of 'S', 'M', or 'L'.

    Returns:
        int: Last development period index.
    """
    if sml_flag == "L":
        return config["years_analyzed"]
    else:
        return 4 * config["years_analyzed"] - (4 - config["analysis_qtr"])
