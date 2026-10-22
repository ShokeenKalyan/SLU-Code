"""
main.py — MBR/SLU Pipeline Orchestrator

R equivalent: SLU_main_code.R (the run_mbr() function and the parallel dispatch loop)

This is the file you run. It:
  1. Loads configuration
  2. Reads all data from SQL
  3. Transforms Vena overrides
  4. Loops over each insurance profile
  5. Runs the full actuarial pipeline for each profile
  6. Exports results to SQL, Excel, and Vena CSV

How to run:
  - On Databricks: Open this notebook and click "Run All"
  - For debugging: Run cells one at a time, or call run_single_profile()

How data flows:
  - Each profile gets a "state" dictionary that carries all intermediate results
  - Each pipeline step reads from state, does its work, and adds its results to state
  - This replaces the R code's global variables (<<- operator)
"""

import time
import traceback
import pandas as pd

# ── Import all helper modules ────────────────────────────────────────────────
# This is the Python equivalent of R's source() calls.
# Each import makes that file's functions available as module.function()

import config
import data_reader
import data_writer
import vena_transform
import triangles
import weighted_average
import curve_fit
import iteration
import rmse
import actuarial_methods
import method_selection
import factors
import ceded
import interpolation
import helpers


# =============================================================================
# SECTION 1: PIPELINE FOR A SINGLE PROFILE
# =============================================================================

def run_profile(profile_id, raw_data, vena_data, settings):
    """
    Run the full MBR pipeline for one insurance profile.

    R equivalent: run_mbr(profile_id_analyzed) in SLU_main_code.R (lines 587-1571)

    This is the heart of the system. It takes one profile through every step:
    triangle building → outliers → VW averages → curve fitting → iteration →
    factors → actuarial methods → method selection → ceded → interpolation.

    Args:
        profile_id (str): The profile identifier (e.g., "CompanyA_GL_Occ_Inc")
        raw_data (dict): All raw data loaded from SQL (shared across profiles)
        vena_data (dict): Transformed Vena override data (shared across profiles)
        settings (dict): Configuration from config.load_config()

    Returns:
        dict: The "state" dictionary containing all results for this profile,
              or None if the profile failed (error is logged).
    """

    # The state dictionary carries ALL data for this profile through the pipeline.
    # Each step reads what it needs and adds its results.
    # This replaces the ~50-80 global variables the R code uses via <<-.
    state = {
        "profile_id": profile_id,
        "start_time": time.time(),
    }

    try:
        # ── Step 1: Get this profile's data ──────────────────────────────
        # R equivalent: Lines 603-650 of SLU_main_code.R
        # Filters the shared raw_data to just this profile's rows.

        state["profile_data"] = data_reader.get_profile_data(
            profile_id, raw_data, settings
        )

        state["overrides"] = vena_transform.get_profile_overrides(
            profile_id, vena_data
        )

        # Determine SML classification for this profile
        # (Short/Medium/Long-tailed — controls many downstream decisions)
        state["sml_flag"] = state["profile_data"].get("sml_flag", "M")

        # Get SML-specific settings (lookback years, VW period candidates, etc.)
        state["years_analyzed"] = config.get_years_analyzed_for_sml(
            settings, state["sml_flag"]
        )
        state["vw_periods"] = config.get_vw_periods_for_sml(
            settings, state["sml_flag"]
        )

        print(f"  [{profile_id}] SML={state['sml_flag']}, "
              f"years_analyzed={state['years_analyzed']}")


        # ── Step 2: Build loss development triangle ──────────────────────
        # R equivalent: Lines 651-720 of SLU_main_code.R
        # Builds the cumulative incurred triangle (YQ for S/M, YY for L).

        state["triangle"] = triangles.build_triangle_for_profile(
            state["profile_data"], settings
        )

        # Compute age-to-age factors from the cumulative triangle
        state["age_to_age"] = triangles.compute_age_to_age_factors(
            state["triangle"]["cumulative"]
        )

        print(f"  [{profile_id}] Triangle built: "
              f"{state['triangle']['cumulative'].shape}")


        # ── Step 3: Detect outliers ──────────────────────────────────────
        # R equivalent: fn_get_age_to_age_outliers() call in SLU_main_code.R
        # Uses adjusted boxplot with medcouple to flag extreme LDFs.

        state["outliers"] = triangles.detect_outliers(
            state["age_to_age"], settings
        )


        # ── Step 4: Compute volume-weighted averages ─────────────────────
        # R equivalent: Lines ~740-780 of SLU_main_code.R
        # Computes VW average LDFs for multiple best-N windows.

        state["vw_averages"] = weighted_average.compute_all_vw_averages(
            state["triangle"], state["outliers"], settings
        )


        # ── Step 5: Score VW averages and pick best-N ────────────────────
        # R equivalent: calc_VW_Averages_weighted_RMSE() call
        # Uses weighted RMSE to determine which N gives the best fit.

        state["best_n_result"] = rmse.select_best_n(
            state["vw_averages"], state["triangle"], settings
        )
        state["initial_ldfs"] = state["best_n_result"]["selected_ldfs"]

        # Compute CDF chain and percent-developed from selected LDFs
        state["initial_cdfs"] = weighted_average.compute_cdf_chain(
            state["initial_ldfs"]
        )
        state["initial_cum_pct"] = weighted_average.compute_percent_developed(
            state["initial_cdfs"]
        )

        print(f"  [{profile_id}] Best-N selected: n={state['best_n_result'].get('best_n')}")


        # ── Step 6: Fit parametric curves ────────────────────────────────
        # R equivalent: exponentialfunc(), weibullfunc(), powerfunc(), IPCfunc()
        # Fits 4 mathematical curves to the LDF pattern, ranked by R².

        state["curves"] = curve_fit.fit_all_curves(
            state["initial_ldfs"],
            state["triangle"].get("dev_periods")
        )

        if state["curves"]:
            print(f"  [{profile_id}] Curves fit: {len(state['curves'])} succeeded, "
                  f"best R²={state['curves'][0].get('r_squared', 0):.4f}")


        # ── Step 7: Compute factor indexes ───────────────────────────────
        # R equivalent: fn_get_end_triangle_index(), fn_get_less_than_one_factors_index()
        # These indexes tell the iteration algorithm where development ends
        # and where anomalous sub-1.0 factors appear.

        state["factor_one_idx"] = factors.get_factor_one_index(
            state["initial_ldfs"], state["triangle"], settings
        )

        state["factor_lt_one_idx"] = factors.get_factor_less_than_one_index(
            state["initial_ldfs"], settings
        )

        state["prop_lt_one"] = factors.get_proportion_less_than_one(
            state["initial_ldfs"], state["factor_one_idx"]
        )

        state["default_last_lt_one"] = factors.get_default_last_index_lt_one(
            state["initial_ldfs"], settings
        )


        # ── Step 8: Run iteration algorithm ──────────────────────────────
        # R equivalent: validate_iteration() + best_rsq_replace()
        # THE CORE OF MBR. Finds the optimal LDF sequence by exploring a
        # tree of curve-fit substitutions, pruned by constraints.

        state["iterations"] = iteration.run_iteration(
            state["initial_ldfs"], state["curves"], settings
        )

        # Score all converged iterations by weighted RMSE and pick the best
        state["best_iteration"] = rmse.select_best_iteration(
            state["iterations"], state["triangle"], settings
        )

        # The selected LDFs from the best iteration
        state["selected_ldfs"] = state["best_iteration"]["ldfs"]

        print(f"  [{profile_id}] Iteration: {len(state['iterations'])} converged, "
              f"best RMSE={state['best_iteration'].get('rmse', 0):.6f}")


        # ── Step 9: Compute tail factor ──────────────────────────────────
        # R equivalent: fn_tail_factor_experience_method()
        # Extrapolates loss development beyond the observed triangle.

        state["tail_factor"] = factors.compute_tail_factor_experience(
            state["selected_ldfs"], state["factor_one_idx"]
        )

        # Recompute CDFs and percent-developed incorporating the tail
        state["selected_cdfs"] = weighted_average.compute_cdf_chain(
            state["selected_ldfs"]
        )
        state["cum_percentages"] = weighted_average.compute_percent_developed(
            state["selected_cdfs"]
        )

        print(f"  [{profile_id}] Tail factor: {state['tail_factor']:.6f}")


        # ── Step 10: Compute actuarial method ultimates ──────────────────
        # R equivalent: calc_BF_Inc_Loss(), calc_cc_IELR(), calc_LR_Ultimate()
        # Computes ultimate loss estimates using all 4 methods (DFM, BF, CC, LR).

        state["ultimates"] = actuarial_methods.compute_all_ultimates(
            state, settings
        )


        # ── Step 11: Select best method per exposure year ────────────────
        # R equivalent: fn_select_ultimate_by_exp_year()
        # Picks the best method per exposure year using rules + RMSE simulation.
        # Vena overrides take final precedence.

        state["method_selection"] = method_selection.select_method_by_exposure_year(
            state["ultimates"],
            state["cum_percentages"],
            state["triangle"],
            settings,
            vena_overrides=state.get("overrides")
        )

        print(f"  [{profile_id}] Methods selected for "
              f"{len(state['method_selection'])} exposure years")


        # ── Step 12: Ceded / reinsurance calculations ────────────────────
        # R equivalent: Ceded section of SLU_main_code.R
        # Splits gross losses into retained and reinsurer portions.

        ri_type_run = state["profile_data"].get("Ri_type_run", "Gross")

        if ri_type_run == "Both":
            state["ceded_results"] = ceded.compute_ceded_ultimates(
                state, state["profile_data"], settings
            )
        else:
            state["ceded_results"] = None


        # ── Step 13: Interpolation (long-tailed profiles only) ───────────
        # R equivalent: calc_interpolation() + func_convert_after_first_one()
        # Converts annual development patterns to quarterly using cubic splines.
        # Only applies to Long-tailed profiles (SML = "L").

        if state["sml_flag"] == "L":
            state["quarterly"] = interpolation.annual_to_quarterly(
                state["cum_percentages"],
                state["triangle"].get("dev_periods_annual"),
                settings
            )
            state["quarterly"] = interpolation.clamp_after_first_one(
                state["quarterly"]
            )
            print(f"  [{profile_id}] Interpolated to quarterly: "
                  f"{len(state['quarterly'])} periods")


        # ── Done ─────────────────────────────────────────────────────────

        state["elapsed_seconds"] = time.time() - state["start_time"]
        state["success"] = True

        print(f"  [{profile_id}] DONE in {state['elapsed_seconds']:.1f}s")

        return state

    except Exception as e:
        # R equivalent: tryCatch in final_run_MBR()
        # If any step fails, log the error and return None.
        # Other profiles continue processing (one failure doesn't crash the batch).
        state["success"] = False
        state["error"] = str(e)
        state["traceback"] = traceback.format_exc()
        state["elapsed_seconds"] = time.time() - state["start_time"]

        print(f"  [{profile_id}] FAILED: {e}")
        return state


# =============================================================================
# SECTION 2: COMBINE PER-PROFILE RESULTS INTO EXPORT-READY FORMAT
# =============================================================================

def combine_profile_results(successful_results):
    """
    Stack per-profile DataFrames into combined DataFrames for export.

    R equivalent: The bind_rows() / rbindlist() block after parLapply in
    SLU_main_code.R (lines 1880-2030). Each profile returns a list of
    DataFrames, and this function concatenates them row-wise.

    Args:
        successful_results: list of state dicts from run_profile() (successful only).

    Returns:
        dict: Combined DataFrames keyed by data_writer result_key names.
    """
    combined = {}

    # Map: (output result_key used by data_writer) → (state dict key, sub-key or None)
    # When sub-key is None, the state key itself is a DataFrame.
    # When sub-key is set, state[key] is a dict and we extract state[key][sub_key].
    keys_to_stack = [
        ("age_to_age_outliers_df",                  "outliers",          None),
        ("actuals_cum_df",                          "triangle",          "cumulative_df"),
        ("influential_points_df",                   "curves",            "influential_points"),
        ("curve_fit_df",                            "curves",            "curve_values"),
        ("r_sq_data_df",                            "curves",            "r_squared"),
        ("dev_prop_inc_df",                         "cum_percentages",   None),
        ("index_cons_1_df",                         "factor_one_idx",    None),
        ("iteration_weighted_rmse_df",              "best_iteration",    "rmse_details"),
        ("all_origin_df",                           "triangle",          "all_origin"),
        ("ultimates_calculated_modified_df",        "ultimates",         None),
        ("ultimate_methods_to_use_df",              "method_selection",  "methods_to_use"),
        ("best_iteration_factors_df",               "best_iteration",    "ldfs_df"),
        ("exp_year_selected_ultimate_rmse_df",      "method_selection",  "rmse_by_year"),
        ("exp_year_selected_ultimate_working_df",   "method_selection",  "working"),
        ("summary_CoU_modified_df",                 "method_selection",  "summary_cou"),
        ("mbr_indexes_df",                          "factor_one_idx",    None),
        ("tail_factors_df",                         "tail_factor",       None),
        ("best_iter_final",                         "selected_ldfs",     None),
    ]

    for result_key, state_key, sub_key in keys_to_stack:
        dfs = []
        for state in successful_results:
            val = state.get(state_key)
            if val is None:
                continue

            if sub_key is not None and isinstance(val, dict):
                df = val.get(sub_key)
            elif isinstance(val, pd.DataFrame):
                df = val
            else:
                continue

            if isinstance(df, pd.DataFrame) and len(df) > 0:
                if "profile_id" not in df.columns:
                    df = df.copy()
                    df["profile_id"] = state["profile_id"]
                dfs.append(df)

        if dfs:
            combined[result_key] = pd.concat(dfs, ignore_index=True)

    return combined


# =============================================================================
# SECTION 3: MAIN EXECUTION (runs when you click "Run All")
# =============================================================================

def run_pipeline():
    """
    Main entry point. Runs the full MBR pipeline for all profiles.

    R equivalent: The top-level execution section of SLU_main_code.R
    (lines 1572-3924 — profile loop, parallel dispatch, export).
    """

    pipeline_start = time.time()
    print("=" * 60)
    print("MBR/SLU Pipeline — Starting")
    print("=" * 60)


    # ── Step 1: Load configuration ───────────────────────────────────────
    print("\n[1/6] Loading configuration...")
    settings = config.load_config()
    print(f"  Evaluation: {settings['analysis_year']}Q{settings['analysis_qtr']}")


    # ── Step 2: Load data from SQL ───────────────────────────────────────
    print("\n[2/6] Loading data from SQL...")
    raw_data = data_reader.load_all_data(settings)
    print(f"  Loaded {len(raw_data)} data tables")


    # ── Step 3: Transform Vena overrides ─────────────────────────────────
    print("\n[3/6] Processing Vena overrides...")
    try:
        vena_data = vena_transform.process_vena_data(settings)
        print(f"  Vena data processed successfully")
    except Exception as e:
        print(f"  WARNING: Vena transform failed ({e}). Continuing without overrides.")
        vena_data = {}


    # ── Step 4: Get profile list ─────────────────────────────────────────
    print("\n[4/6] Building profile list...")
    profile_list = data_reader.get_profile_list(raw_data)
    print(f"  {len(profile_list)} profiles to process")


    # ── Step 5: Process each profile ─────────────────────────────────────
    # Using a simple for-loop for now (Mode 1: In-Memory).
    # For production, this can be replaced with Spark parallel execution.
    #
    # R equivalent: parLapply(clust, profiles_list, final_run_MBR)

    print(f"\n[5/6] Processing profiles...")
    all_results = []
    success_count = 0
    fail_count = 0

    for i, profile_id in enumerate(profile_list):
        print(f"\n--- Profile {i+1}/{len(profile_list)}: {profile_id} ---")

        result = run_profile(profile_id, raw_data, vena_data, settings)

        if result and result.get("success"):
            success_count += 1
        else:
            fail_count += 1

        all_results.append(result)

        # Optional: save checkpoint after each profile (when Delta access is available)
        if settings.get("use_delta_checkpoints") and result and result.get("success"):
            data_writer.save_checkpoint(result, profile_id, settings)


    # ── Step 6: Combine and export results ─────────────────────────────
    print(f"\n[6/6] Exporting results...")

    # Filter to successful results only
    successful_results = [r for r in all_results if r and r.get("success")]

    if successful_results:
        # Combine per-profile state dicts into one dict of DataFrames
        # keyed by the names data_writer expects (matching OUTPUT_TABLE_MAP).
        # R equivalent: bind_rows() / rbindlist() after parLapply
        combined = combine_profile_results(successful_results)
        settings["profiles_list"] = [r["profile_id"] for r in successful_results]

        try:
            data_writer.write_to_sql(combined, settings)
            print(f"  SQL export complete")
        except Exception as e:
            print(f"  SQL export failed: {e}")

        try:
            data_writer.write_to_excel(combined, settings)
            print(f"  Excel export complete")
        except Exception as e:
            print(f"  Excel export failed: {e}")

        try:
            data_writer.write_to_vena_csv(combined, settings)
            print(f"  Vena CSV export complete")
        except Exception as e:
            print(f"  Vena CSV export failed: {e}")


    # ── Summary ──────────────────────────────────────────────────────────

    elapsed = time.time() - pipeline_start
    print("\n" + "=" * 60)
    print(f"MBR/SLU Pipeline — Complete")
    print(f"  Total time:  {elapsed:.1f}s ({elapsed/60:.1f} minutes)")
    print(f"  Succeeded:   {success_count}/{len(profile_list)}")
    print(f"  Failed:      {fail_count}/{len(profile_list)}")
    print("=" * 60)

    # Log failed profiles for investigation
    if fail_count > 0:
        print("\nFailed profiles:")
        for r in all_results:
            if r and not r.get("success"):
                print(f"  - {r['profile_id']}: {r.get('error', 'unknown')}")

    return all_results


# =============================================================================
# SECTION 4: SINGLE-PROFILE DEBUG MODE
# =============================================================================

def run_single_profile(profile_id, settings=None):
    """
    Run the pipeline for a single profile. Useful for debugging.

    Usage (in a Databricks notebook cell):
        result = run_single_profile("MyCompany_GL_Occ_Inc")

    After running, you can inspect any intermediate result:
        result["triangle"]           # the loss triangle
        result["outliers"]           # which LDFs were flagged
        result["selected_ldfs"]      # the final selected LDFs
        result["ultimates"]          # all 4 method ultimates
        result["method_selection"]   # which method was picked per year
    """

    if settings is None:
        settings = config.load_config()

    print(f"Loading data for single profile: {profile_id}")
    raw_data = data_reader.load_all_data(settings)

    try:
        vena_data = vena_transform.process_vena_data(settings)
    except Exception:
        vena_data = {}

    result = run_profile(profile_id, raw_data, vena_data, settings)
    return result


# =============================================================================
# SECTION 5: RUN
# =============================================================================

# When you click "Run All" in Databricks, this section executes.
# Comment it out if you want to import this file without running the pipeline.

if __name__ == "__main__":
    # Full pipeline
    results = run_pipeline()

    # Or for debugging, run a single profile:
    # result = run_single_profile("YourCompany_LOB_Coverage_ClaimType")
