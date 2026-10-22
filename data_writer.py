"""
data_writer.py — Writes pipeline results to SQL, Excel, and Vena CSV.

Replaces the SQL export block from SLU_main_code.R (lines ~2207–2449).
In R these were: dbGetQuery("DELETE ...") followed by dbAppendTable() for ~30 tables,
plus write.xlsx() and write.csv() for Excel and Vena outputs.

Supports two modes controlled by USE_DELTA_CHECKPOINTS:
  - False (default): writes to SQL via Spark JDBC or pyodbc
  - True: writes to Delta tables in Databricks (persistent, survives cluster restarts)
"""

import os
import logging
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Complete list of output tables (from R lines 2233–2422)
# ---------------------------------------------------------------------------
# Each entry maps: SQL table name → the key in the results dictionary that
# holds the DataFrame to write.
#
# The R code follows a "delete-then-append" pattern for each table:
#   DELETE FROM afr_analytics.MBR_xxx WHERE profile_id IN (...) AND res_year=... AND res_qtr=...
#   dbAppendTable(con, "afr_analytics.MBR_xxx", df)
#
# In Python, this becomes an overwrite-by-partition or a delete+insert.

OUTPUT_TABLE_MAP = {
    # --- Per-profile tables (deleted by profile_id list) ---
    "afr_analytics.MBR_age_to_age_outliers":                     "age_to_age_outliers_df",
    "afr_analytics.MBR_cumulative_incurred_loss":                "actuals_cum_df",
    "afr_analytics.MBR_influential_points":                      "influential_points_df",
    "afr_analytics.MBR_curve_fit":                               "curve_fit_df",
    "afr_analytics.MBR_curve_fit_r_squared":                     "r_sq_data_df",
    "afr_analytics.MBR_dev_prop_incurred":                       "dev_prop_inc_df",
    "afr_analytics.MBR_factor_one_index":                        "index_cons_1_df",
    "afr_analytics.MBR_iteration_weighted_RMSE":                 "iteration_weighted_rmse_df",
    "afr_analytics.MBR_all_origin":                              "all_origin_df",
    "afr_analytics.MBR_actuarial_method_ultimates":              "ultimates_calculated_modified_df",
    "afr_analytics.MBR_ultimate_methods_to_use":                 "ultimate_methods_to_use_df",
    "afr_analytics.MBR_best_iteration":                          "best_iteration_factors_df",
    "afr_analytics.MBR_exp_year_selected_ultimate_rmse":         "exp_year_selected_ultimate_rmse_df",
    "afr_analytics.MBR_exp_year_selected_ultimate_working":      "exp_year_selected_ultimate_working_df",
    "afr_analytics.MBR_summary_CoU":                             "summary_CoU_modified_df",
    "afr_analytics.MBR_algorithm_indexes":                       "mbr_indexes_df",
    "afr_analytics.MBR_completion_of_triangle":                  "cot_combined_df",
    "afr_analytics.MBR_exp_year_max_dev_len":                    "exp_year_dev_len_df",
    "afr_analytics.MBR_tail_factor":                             "tail_factors_df",
    "afr_analytics.MBR_cumulative_incurred_loss_YY":             "actuals_yy_df",
    "afr_analytics.MBR_initial_selected_averages":               "weighted_avg_ldf_df",
    "afr_analytics.MBR_initial_selected_averages_wo_outliers_removal": "weighted_avg_ldf_wo_outliers_df",
    "afr_analytics.MBR_initial_selection_summary":               "iterations_summary_table_df",
    "afr_analytics.MBR_best_iteration_interpolated":             "best_iter_final",
    "afr_analytics.MBR_movement_vector_vena":                    "movement_vector_ordered",

    # --- Global tables (deleted by res_year/res_qtr only, not by profile_id) ---
    "afr_analytics.MBR_YQ_incurred_triangles":                   "incurred_tri_data",
    "afr_analytics.MBR_vena_vectors":                            "vena_vectors_ordered",
    "afr_analytics.MBR_vena_LDF_dev_period":                     "vena_ldf",
    "afr_analytics.MBR_vena_vectors_method_names":               "vena_method_data",
    "afr_analytics.MBR_YQ_paid_triangles":                       "paid_tri_data",
}

# Tables that are deleted by res_year/qtr/val_flag only (no profile_id filter).
# All other tables use the per-profile delete pattern.
GLOBAL_TABLES = {
    "afr_analytics.MBR_exp_year_max_dev_len",
    "afr_analytics.MBR_YQ_incurred_triangles",
    "afr_analytics.MBR_vena_vectors",
    "afr_analytics.MBR_vena_LDF_dev_period",
    "afr_analytics.MBR_vena_vectors_method_names",
    "afr_analytics.MBR_YQ_paid_triangles",
}


# ---------------------------------------------------------------------------
# SQL delete + append (the R pattern, in Python)
# ---------------------------------------------------------------------------

def _build_delete_query(table_name, config, profiles_list):
    """
    Build a DELETE query matching the R code's pattern.

    R pattern for per-profile tables:
        DELETE FROM afr_analytics.MBR_xxx
        WHERE profile_id IN ('P1','P2',...)
          AND res_year = 2026
          AND res_qtr = 3
          AND val_flag = 1
          AND SLU_Analysis_Type = 'Valuation'

    R pattern for global tables:
        DELETE FROM afr_analytics.MBR_xxx
        WHERE res_year = 2026
          AND res_qtr = 3
          AND val_flag = 1
          AND SLU_Analysis_Type = 'Valuation'
    """
    year = config["analysis_year"]
    qtr = config["analysis_qtr"]
    val_flag = config["analysis_val_flag"]
    analysis_type = config.get("slu_analysis_type", "Valuation")

    if table_name in GLOBAL_TABLES:
        # No profile_id filter
        return (
            f"DELETE FROM {table_name} "
            f"WHERE res_year = {year} "
            f"AND res_qtr = {qtr} "
            f"AND val_flag = {val_flag} "
            f"AND SLU_Analysis_Type = '{analysis_type}'"
        )
    else:
        # Per-profile delete
        quoted = ", ".join(f"'{p}'" for p in profiles_list)
        return (
            f"DELETE FROM {table_name} "
            f"WHERE profile_id IN ({quoted}) "
            f"AND res_year = {year} "
            f"AND res_qtr = {qtr} "
            f"AND val_flag = {val_flag} "
            f"AND SLU_Analysis_Type = '{analysis_type}'"
        )


def _execute_sql(query, config):
    """Execute a non-SELECT SQL statement (DELETE, INSERT, etc.)."""
    if "spark" in config and config["spark"] is not None:
        # On Databricks: use the spark session to run JDBC statements
        spark = config["spark"]
        jdbc_url = config["jdbc_url"]
        props = config["jdbc_properties"]
        # For DELETE statements, we need a direct JDBC connection
        driver_manager = spark._jvm.java.sql.DriverManager
        conn = driver_manager.getConnection(
            jdbc_url, props.get("user", ""), props.get("password", "")
        )
        try:
            stmt = conn.createStatement()
            stmt.executeUpdate(query)
            stmt.close()
        finally:
            conn.close()
    else:
        import pyodbc
        conn = pyodbc.connect(config["connection_string"])
        try:
            cursor = conn.cursor()
            cursor.execute(query)
            conn.commit()
        finally:
            conn.close()


def _append_table_sql(df, table_name, config):
    """
    Append a pandas DataFrame to a SQL table.

    R equivalent: dbAppendTable(con, SQL("afr_analytics.MBR_xxx"), df)
    """
    if df is None or len(df) == 0:
        logger.info(f"  Skipping {table_name} — empty DataFrame")
        return

    if "spark" in config and config["spark"] is not None:
        spark = config["spark"]
        spark_df = spark.createDataFrame(df)
        spark_df.write.jdbc(
            url=config["jdbc_url"],
            table=table_name,
            mode="append",
            properties=config["jdbc_properties"],
        )
    else:
        from sqlalchemy import create_engine
        engine = create_engine(
            f"mssql+pyodbc:///?odbc_connect={config['connection_string']}"
        )
        # Split schema.table for to_sql
        parts = table_name.split(".")
        schema = parts[0] if len(parts) > 1 else None
        tbl = parts[-1]
        df.to_sql(tbl, engine, schema=schema, if_exists="append", index=False)


def _write_delta_table(df, table_name, config):
    """
    Write a DataFrame as a Delta table (Databricks only).

    This replaces both the DELETE and APPEND steps — Delta's overwrite mode
    handles it atomically.
    """
    if df is None or len(df) == 0:
        logger.info(f"  Skipping Delta {table_name} — empty DataFrame")
        return

    spark = config["spark"]
    # Convert schema.table → catalog-compatible name for Delta
    # e.g. "afr_analytics.MBR_curve_fit" → "mbr_dev.MBR_curve_fit"
    delta_schema = config.get("delta_schema", "mbr_dev")
    clean_table = table_name.split(".")[-1]
    delta_name = f"{delta_schema}.{clean_table}"

    spark_df = spark.createDataFrame(df)
    spark_df.write.format("delta").mode("overwrite").saveAsTable(delta_name)
    logger.info(f"  Wrote Delta table: {delta_name} ({len(df)} rows)")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def write_to_sql(all_results, config):
    """
    Write all pipeline results to SQL tables.

    Follows the R pattern: for each table, DELETE matching rows first,
    then APPEND the new data.

    Parameters
    ----------
    all_results : dict
        Combined results dictionary. Keys match the values in OUTPUT_TABLE_MAP.
    config : dict
        Pipeline configuration with DB connection details.
    """
    use_delta = config.get("use_delta_checkpoints", False)
    profiles_list = config.get("profiles_list", [])

    logger.info("Starting SQL export...")

    for table_name, result_key in OUTPUT_TABLE_MAP.items():
        df = all_results.get(result_key)
        if df is None:
            logger.warning(f"  Result key '{result_key}' not found — skipping {table_name}")
            continue

        try:
            if use_delta:
                # Delta mode: atomic overwrite, no manual delete needed
                _write_delta_table(df, table_name, config)
            else:
                # SQL mode: delete then append (R pattern)
                delete_query = _build_delete_query(table_name, config, profiles_list)
                logger.info(f"  Deleting from {table_name}...")
                _execute_sql(delete_query, config)
                logger.info(f"  Appending to {table_name} ({len(df)} rows)...")
                _append_table_sql(df, table_name, config)
        except Exception as e:
            logger.error(f"  FAILED writing {table_name}: {e}")
            # Continue with other tables — one failure should not stop the batch
            # (same as R's tryCatch behavior)


def save_checkpoint(df, step_name, config):
    """
    Save an intermediate result as a Delta table (checkpoint).

    Use this during development to avoid re-running earlier steps
    after a cluster restart.

    Parameters
    ----------
    df : pd.DataFrame
        The intermediate result to save.
    step_name : str
        Name for the checkpoint (e.g. "triangles", "outliers", "curves").
    config : dict
        Must contain 'spark' and optionally 'delta_schema'.
    """
    if not config.get("use_delta_checkpoints", False):
        return  # Checkpoints disabled — skip silently

    spark = config["spark"]
    delta_schema = config.get("delta_schema", "mbr_dev")
    delta_name = f"{delta_schema}.checkpoint_{step_name}"

    spark_df = spark.createDataFrame(df)
    spark_df.write.format("delta").mode("overwrite").saveAsTable(delta_name)
    logger.info(f"  Checkpoint saved: {delta_name} ({len(df)} rows)")


def load_checkpoint(step_name, config):
    """
    Load an intermediate result from a Delta table checkpoint.

    Parameters
    ----------
    step_name : str
        Name of the checkpoint (e.g. "triangles", "outliers", "curves").
    config : dict
        Must contain 'spark' and optionally 'delta_schema'.

    Returns
    -------
    pd.DataFrame or None
        The checkpoint data, or None if it does not exist.
    """
    if not config.get("use_delta_checkpoints", False):
        return None

    spark = config["spark"]
    delta_schema = config.get("delta_schema", "mbr_dev")
    delta_name = f"{delta_schema}.checkpoint_{step_name}"

    try:
        spark_df = spark.table(delta_name)
        return spark_df.toPandas()
    except Exception:
        logger.info(f"  No checkpoint found for '{step_name}'")
        return None


def write_to_excel(all_results, config):
    """
    Write results to Excel workbooks.

    R equivalent: write.xlsx() calls that produce per-profile workbooks
    on a shared network drive.

    Parameters
    ----------
    all_results : dict
        Combined results dictionary.
    config : dict
        Must contain 'excel_output_path' (directory for output files).
    """
    output_path = config.get("excel_output_path", "")
    if not output_path:
        logger.info("No excel_output_path configured — skipping Excel export")
        return

    os.makedirs(output_path, exist_ok=True)

    try:
        # Main output workbook with multiple sheets
        main_wb_path = os.path.join(output_path, "MBR_output.xlsx")
        with pd.ExcelWriter(main_wb_path, engine="openpyxl") as writer:
            for key, df in all_results.items():
                if isinstance(df, pd.DataFrame) and len(df) > 0:
                    # Truncate sheet name to 31 chars (Excel limit)
                    sheet_name = key[:31]
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
        logger.info(f"  Excel workbook written: {main_wb_path}")
    except Exception as e:
        logger.error(f"  FAILED writing Excel: {e}")


def write_to_vena_csv(all_results, config):
    """
    Write Vena-formatted CSVs for upload to the Vena financial planning platform.

    R equivalent: write.csv() calls that produce:
      - vena_2026Q3_Valuation_Updated_patterns_extract.csv
      - vena_2026Q3_Valuation_Updated_sml_flag_extract.csv

    Parameters
    ----------
    all_results : dict
        Combined results. Must contain 'vena_patterns_df' and 'vena_sml_df'.
    config : dict
        Must contain 'vena_output_path' (directory for CSV files).
    """
    output_path = config.get("vena_output_path", "")
    if not output_path:
        logger.info("No vena_output_path configured — skipping Vena CSV export")
        return

    os.makedirs(output_path, exist_ok=True)
    year = config["analysis_year"]
    qtr = config["analysis_qtr"]
    analysis_type = config.get("slu_analysis_type", "Valuation")

    # Patterns file
    patterns_df = all_results.get("vena_patterns_df")
    if patterns_df is not None and len(patterns_df) > 0:
        fname = f"vena_{year}Q{qtr}_{analysis_type}_Updated_patterns_extract.csv"
        fpath = os.path.join(output_path, fname)
        patterns_df.to_csv(fpath, index=False)
        logger.info(f"  Vena patterns CSV written: {fpath}")

    # SML mapping file
    sml_df = all_results.get("vena_sml_df")
    if sml_df is not None and len(sml_df) > 0:
        fname = f"vena_{year}Q{qtr}_{analysis_type}_Updated_sml_flag_extract.csv"
        fpath = os.path.join(output_path, fname)
        sml_df.to_csv(fpath, index=False)
        logger.info(f"  Vena SML CSV written: {fpath}")
