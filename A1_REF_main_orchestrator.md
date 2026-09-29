# Exhaustive Analysis: SLU_main_code.R.txt & MBR_vena_data_transformation_adhoc.R.txt

---

## FILE 1: SLU_main_code.R.txt (3,924 lines)

This is an R Notebook that serves as the **main orchestrator** for the entire Machine Based Reserves (MBR) / Selected Loss Ultimate (SLU) system. It is structured as a series of R Markdown chunks that run sequentially.

---

### CHUNK 1 (Lines 9–463): Setup, Data Import, and Triangle Construction

#### 1A. Environment & Configuration (Lines 9–97)

| Variable | Value / Purpose | Line |
|---|---|---|
| `start.time` | Records wall-clock start | 12 |
| `wd_path` | Working directory on RStudio Server | 13 |
| `analysis_year` | **2026** — the reserving year | 69 |
| `analysis_qtr` | **3** — Q3 | 70 |
| `analysis_val_flag` | **1** — valuation flag | 71 |
| `SLU_analysis_type` | **"Valuation"** | 72 |
| `Ri_type_run` | **'Gross'** — options are `'Gross'` or `'Both'` (Gross+Ceded) | 74 |
| `pattern_threshold` | **0.6** — Premium Recovery Ratio threshold for ceded method selection | 75 |
| `years_analyzed` | **25** — total lookback window in years | 76 |
| `years_analyzed_S_tailed` | **10** — lookback for Short-tailed lines | 77 |
| `years_analyzed_M_tailed` | **14** — lookback for Medium-tailed lines | 78 |
| `years_analyzed_L_tailed` | **24** — lookback for Long-tailed lines | 79 |
| `years_capped` | **14** — caps how far back we look for oldest year | 80 |
| `default_last_index` | **20** — upper bound for iteration algorithm's replacement zone | 82 |
| `default_first_index` | **1** — lower bound for iteration algorithm's replacement zone | 83 |
| `iteration_num_threshold` | **11000** — max iterations before stopping | 85 |
| `factor_1_index_threshold` | **2** — threshold used in factor=1 index computation | 86 |
| `consecutive_less_than_one_num` | **5** — consecutive <1 factors trigger negative development | 89 |
| `prop_less_than_one_factors_threshold` | **0.4** (40%) — proportion of <1 factors trigger | 90 |
| `incr_pct_change_threshold` | **0.05** (5%) — incremental percentage change threshold | 91 |
| `last_dev_month` | Computed: `4*25-(4-3) = 99` — last development quarter index | 94 |
| `outlier_detection_min_points` | **4** — minimum data points for outlier detection | 95 |
| `seed_value` | **123** — for reproducibility | 60 |

**Libraries sourced (Lines 24–41):**
1. `MBR_curve_fit.R` — 4 curve-fitting functions (Exponential, Weibull, Power, IPC)
2. `MBR_weighted_average.R` — volume-weighted average LDF calculations
3. `MBR_factor_one_index.R` — end-of-triangle index where LDF converges to 1
4. `MBR_iteration_algorithm_0.99_modified.R` — recursive iteration-building algorithm
5. `MBR_actuarial_method_ultimates.R` — BF, CC, LR ultimate computations
6. `MBR_threshold_ultimate_weighted_RMSE.R` — weighted RMSE for iteration evaluation
7. `MBR_factors_less_than_one_index.R` — handles negative development
8. `MBR_tail_factor_methods.R` — tail factor computation
9. `MBR_ceded_all_calculations.R` — ceded-specific calculations (recovery ratios)
10. `MBR_method_selection_by_exposure_year_cc_change.R` — method selection per exposure year
11. `MBR_iteration_weighted_RMSE_SML_change.R` — RMSE computation with SML differentiation
12. `MBR_vena_data_tranformation_adhoc_new.R` — data transformation (see File 2 analysis)
13. `MBR_interpolation.R` — interpolation for Long-tailed profiles (YY→YQ conversion)

**R Libraries (Lines 46–56):**
- `ChainLadder` — triangle manipulation, `as.triangle()`, `incr2cum()`
- `DBI` / `odbc` — SQL Server connectivity
- `fitdistrplus` — distribution fitting
- `dplyr` — data manipulation
- `Metrics` — `rmse()` function
- `openxlsx` / `xlsx` — Excel I/O
- `mrfDepth` — `medcouple()` for adjusted boxplot outlier detection
- `moments` — statistical moments
- `tidyr` — pivot/reshape operations

#### 1B. SQL Data Import (Lines 99–154)

Connects to Azure SQL Server (`z-xlc-0277-actu-pr-ue2-sql01-actuarialdatastore.database.windows.net`) with interactive password prompt.

**Tables queried (conditional on `Ri_type_run`):**

| Variable | SQL Table | Filter |
|---|---|---|
| `incurred_raw` | `vena_stage.t_f_vena_SLU_Inc_paid_sparta_grain` | `Vector = 'Incurred Loss'` (+ RI Type if Gross) |
| `method_raw_extract` | `vena_stage.t_f_vena_SLU_reserveclass_AY_vectors` | (+ RI Type if Gross) |
| `vena_data_extract_raw` | `vena_stage.t_f_vena_SLU_reserveclass_AY_vectors` | (+ RI Type if Gross) |
| `paid_raw` | `vena_stage.t_f_vena_SLU_Inc_paid_sparta_grain` | `Vector = 'Paid Loss'` (+ RI Type if Gross) |
| `incurred_pattern_raw` | `vena_stage.t_f_vena_SLU_Inc_paid_prem_patterns` | `Vector = 'Incurred Percentage Developed'` |
| `profile_mapping` | `afr_analytics.MBR_profile_mapping` | Filtered by year/qtr/val_flag AND `run_flag==1` |

**Common columns selected (Line 138):** `Reserving Quarter`, `Reserve Class`, `Vector`, `Branch`, `Exposure Year`, `AY_UY`, `Development Period`, `RI Type`, `Version`, `PLOB`, `Type`, `value`

**Method name filtering (Lines 140–141):** The `method_raw_extract` is filtered to only these 7 method name vectors:
1. Selected LR Method
2. Selected Premium Method Name
3. Selected Ultimate Method
4. Derived Ultimate Allocation Method
5. Selected Ultimate Allocation Method
6. Selected Recovery Ratio Method
7. Basis for Recovery Ratio Ultimate (Ultimate/IBNR)

The `vena_data_extract_raw` is filtered to everything **except** these 7 (i.e., numeric vectors only).

#### 1C. Incurred Triangle Transformation (Lines 156–167)

Calls `fn_to_transform_incurred_paid()` (from File 2) on `incurred_raw`. Result: `incurred_tri_data` with columns `(Product, Vector, Development Period, Exposure Year, Reserving Quarter, Version, Measure, Value, res_year, res_qtr, val_flag)`.

Then inner-joins with `profile_mapping` to keep only active profiles, renames columns to `(profile_id, exp_year, dev_len, Ri_type, Gross_Incurred)`, and filters to relevant years.

#### 1D. Vena All-Vector Data Transformation (Lines 181–228)

Calls `fn_to_transform_vena_all_data()` (from File 2). Returns a list of 2 data frames:
1. `inputs_vena_all_profiles_1` — pivoted Vena vectors at profile/exposure-year level. A computed column `Financial Budget LR (Att)` = `Financial Budget Loss / Budget EP FY` is added. Then inner-joined with `profile_mapping`.
2. `vena_ldf` — LDF data by development period.

#### 1E. Method Name Data Transformation (Lines 222–228)

Calls `fn_to_transform_method_data()` (from File 2). Returns method names per profile/exposure-year. Inner-joined with `profile_mapping`.

#### 1F. Paid Triangle Transformation (Lines 296–308)

Same process as incurred: calls `fn_to_transform_incurred_paid()` on `paid_raw`, joins with `profile_mapping`, renames columns.

#### 1G. Upper Triangle Construction (Lines 343–401)

**Purpose:** Create a complete rectangle of (profile_id × exp_year × dev_len × Ri_type), fill missing combinations with 0, and identify which cells belong to the "lower triangle" (future, unobserved data).

Key steps:
1. Generate all exposure years: `seq(2026, 2002)` (Lines 350–351)
2. Generate all development periods: `seq(3, 297, by=3)` — i.e., quarterly from 3 months to `3*4*25-3*(4-3)=297` months (Line 354)
3. Cross-join profile × exp_year × dev_len × Ri_type (Lines 367–368)
4. Create `exp_year_dev_len` mapping: each exposure year has a `max_dev_len` (the diagonal — how much data is available for that year). For 2026: `3*3=9`, for 2025: `9+12=21`, etc. (Line 365)
5. Flag `lower_tri_cmbn = 1` where `dev_len > max_dev_len` (Line 374)
6. Find missing upper-triangle combinations and fill with 0 (Lines 379–394)
7. Remove any incorrect lower-triangle entries from actuals (Lines 384–388)
8. Sort by `(profile_id, exp_year, Ri_type, dev_len)` and compute **cumulative** incurred via `cumsum()` (Lines 399–401)

#### 1H. Year-to-Year (YY) Triangle Conversion (Lines 411–426)

For **Long-tailed** lines, analysis is done yearly (YY) rather than quarterly (YQ). This block converts YQ incremental data to YY by:
1. Mapping each quarterly dev_len to a yearly dev_len using the formula:
   - If `analysis_qtr==1`: `analysis_qtr*3 + ceiling((dev_len-3)/12)*12`
   - Otherwise: `analysis_qtr*3 + as.integer(dev_len/12)*12`
2. Aggregating (summing) incremental losses within each yearly bucket
3. Recomputing cumulative sums

#### 1I. Paid Triangle — Same Treatment (Lines 429–461)

Identical logic to incurred: creates missing combinations, computes cumulative, and converts to YY.

---

### CHUNK 2 (Lines 467–531): SML Classification (Average Duration)

**Purpose:** Classify each profile as **S**hort, **M**edium, or **L**ong-tailed based on average payment duration.

**Current implementation (Line 493):** Reads SML mapping from a pre-computed CSV file (`SML_Mapping_File_2026_Q3.csv`) rather than computing from payment patterns (the commented-out code at Lines 469–489 shows the original calculation based on paid LDF payment patterns).

**Conceptual approach (from comments):**
1. Take paid LDF patterns, compute incremental paid LDFs
2. Adjust the last development period so incremental sums to 1
3. Compute `duration_years = (sum(dev_qtr * incr_paid_ldf) - 0.5) / 4`
4. Classify: `S` if < 3 years, `L` if > 5 years, `M` otherwise

**Vena export (Lines 508–529):** Creates a Vena-formatted dataframe (`MBR_SML_Vena_df`) with the SML flag per profile, mapping S→"Short", M→"Medium", L→"Long", formatted with Vena dimension columns.

---

### CHUNK 3 (Lines 535–548): Profile Filtering

**Purpose:** Remove profiles with insufficient data.

1. Summarize total incurred by (profile_id, exp_year, Ri_type)
2. Join with SML flag
3. Filter to relevant years based on SML:
   - S: only keep `exp_year >= analysis_year - years_analyzed_S_tailed + 1` (2017+)
   - M: only keep `exp_year >= analysis_year - years_analyzed_M_tailed + 1` (2013+)
4. Remove exposure years with zero total incurred
5. Count non-zero years per profile; keep profiles with **≥ 5 years** of non-zero data

---

### CHUNK 4 (Lines 551–582): Max Non-Zero Incurred Year

**Purpose:** For each profile, find the latest exposure year that has non-zero incurred data.

Logic:
- If all profiles have at least one non-zero year: simply `max(exp_year)` where `is_zero==1`
- If some profiles have ALL zero incurred: use `analysis_year` as default

Output: `Latest_Ay` dataframe with `(profile_id, Ri_type, max_non_zero_inc_year)`

---

### CHUNK 5 (Lines 586–1571): THE MAIN `run_mbr()` FUNCTION

This is the core function, called once per profile. It takes `profile_id_analyzed` and returns a list of ~25 result dataframes.

#### Step 0: Setup (Lines 588–648)

- Retrieves `max_non_zero_inc_year` and `sml_flag` for this profile
- Selects the appropriate triangle data:
  - **Long-tailed (L):** uses YY data (`actuals_yy`), lookback = `years_analyzed_L_tailed` (24), `last_dev_period_index = years_analyzed` (25)
  - **Short-tailed (S):** uses YQ data, lookback = `years_analyzed_S_tailed` (10), capped at `years_capped` (14), `last_dev_period_index = 4*25-(4-3) = 97`
  - **Medium-tailed (M):** uses YQ data, lookback = `years_analyzed_M_tailed` (14), capped at 14, same `last_dev_period_index`
- Zeros out data for exposure years older than `oldest_year`

#### Step 1: Triangle Creation (Lines 654–700)

1. Build `development_index_df`: maps sequential index → actual development month
2. Compute `inc_by_ay`: total incurred per exposure year (for RMSE weighting)
3. Convert to R triangle objects using `ChainLadder::as.triangle()` — both incremental and cumulative
4. Remove exposure years with **negative cumulative incurred** from the triangle (for initial selections only)

#### Step 2: Outlier Detection (Lines 722–731)

Calls `fn_get_age_to_age_outliers()` which:
1. Computes age-to-age factors for each (exp_year, dev_len) pair
2. Uses **adjusted boxplot** method (IQR with medcouple skewness adjustment) to detect outlier age-to-age factors
3. Returns the outlier-flagged dataframe and `outlier_detection_last_dev_period_index`

#### Step 3: Volume-Weighted (VW) Average Selection (Lines 736–788)

**Purpose:** Determine the optimal number of years (n) for volume-weighted average LDFs.

1. The candidate n values depend on SML:
   - S: `c(3, 4, 5)`
   - M: `c(3, 4, 5, 6, 7, 8, 9, 10, 24)`
   - L: `c(5, 6, 7, 8, 9, 10, 24)`
2. For each n, calls `calc_weighted_average()` with outlier removal
3. For each n, computes weighted RMSE via `calc_VW_Averages_weighted_RMSE()` — this back-tests the LDFs against actual data
4. Also computes RMSE excluding 1, 2, 3, and 4 development periods
5. **The best n** is chosen as the one with minimum RMSE when excluding the first development period (`VW_Averages_wRMSE_excl1_df`)
6. The selected VW averages are then computed both WITH and WITHOUT outlier removal

#### Step 4: CDF & Incurred % Developed (Lines 803–829)

From the selected VW average LDFs:
1. **CDF** = reverse cumulative product of LDFs (from the end): `cdf[i] = prod(ldf[i], ldf[i+1], ..., ldf[n])`
2. **Incurred % Developed** = `100 / CDF` — represents what percentage of ultimate has been observed

#### Step 5: Curve Fitting (Lines 833–906)

Fits **4 parametric curves** to the initial-selection LDF vector `y1`:
1. **Exponential Decay** — `exponentialfunc(y1, sml_flag)`
2. **Weibull** — `weibullfunc(y1, sml_flag)`
3. **Power** — `powerfunc(y1, sml_flag)`
4. **Inverse Power Curve (IPC)** — `IPCfunc(y1, sml_flag)`

Each returns: fitted values, R², and influential points (outliers in the curve fit).

NaN values from failed fits are replaced with 1. R² values are sorted descending. Curves with R² ≥ 0.6 are tracked separately.

#### Step 6: Factor-One Index (Lines 920–924)

Calls `fn_get_end_triangle_index()` to determine at which development period the LDFs have essentially converged to 1.0 (i.e., the loss is fully developed). Beyond this index, all factors are set to 1.

Also returns `dev_prop_inc_df` — proportional development incurred data used in the computation.

#### Step 7: Less-Than-One Factor Analysis (Lines 936–967)

Determines whether **negative development** (factors < 1) should be incorporated:
1. `consecutive_less_than_one_index` — first index where ≥5 consecutive factors are <1
2. `prop_less_than_one_factors` — proportion of factors <1 in the range
3. `incr_pct_change_grt_than_threshold_index` — where incremental % change exceeds 5%

**Decision logic (Line 950):** Include <1 factors if ANY of:
- Consecutive <1 index exists and is before factor-one index
- Proportion of <1 factors ≥ 40%
- Incremental % change exceeds threshold

If including <1 factors, `default_last_index` is updated to be the minimum of original and `index_less_than_one_factors - 1`.

#### Step 8: Iteration Algorithm (Lines 970–1086)

This is the **core MBR algorithm**. It generates multiple candidate LDF selection vectors ("iterations") using curve-fit replacement.

**First attempt:** Uses top-2 curves (by R²)
1. Calls `validate_iteration()` — a **recursive** function that:
   - Takes initial-selection LDFs
   - Tries replacing subsets of LDF values with curve-fitted values
   - Validates that each replacement maintains monotonically decreasing factors ≥ 1
   - If converged (all constraints met), stores the iteration
   - If not, recursively tries different replacement strategies
   - Stops at `iteration_num_threshold` (11,000) calls
2. After the algorithm zone, factors beyond `default_last_index` are replaced with the **best R² curve** values (`best_rsq_replace()`)
3. After `index_cons_1`, all factors are set to 1.0

**Fallback (Lines 1029–1086):** If no iteration converges with 2 curves, re-runs using all 4 curves.

**Final safety net (Lines 1108–1112):** The first iteration (initial selections) is always marked as converged.

#### Step 9: Best Iteration Selection via RMSE (Lines 1146–1190)

1. Filters to converged iterations only
2. For each converged iteration, calls `calc_weighted_RMSE()` which:
   - Projects ultimates for each exposure year using the iteration's LDFs
   - Compares projected vs actual cumulative incurred
   - Computes weighted RMSE (weighted by absolute incurred amount)
3. If any curve has R² ≥ 0.6: selects the iteration with **minimum weighted RMSE**
4. If no curve has R² ≥ 0.6: forces selection of iteration #1 (initial selections)

Output: `best_iteration_factors_df` (the winning LDF vector), `best_iter_res_df` (exposure-year-level results), `all_origin_df` (RMSE check data)

#### Step 10: Tail Factor (Lines 1201–1245)

Calls `fn_tail_factor_experience_method()` to compute a tail factor — an extrapolation beyond the observed triangle.

Constraints:
- If <1 factors are not included AND tail < 1 → set to 1
- Tail factor is always capped at ≥ 1 (Line 1215)

The tail factor is applied by replacing the LDF at `factor_1_dev_month` with the tail factor, then recomputing all cumulative factors and percentages developed.

#### Step 11: Actuarial Method Ultimates (Lines 1269–1299)

Pulls Vena assumptions for this profile and joins with the best iteration results. Then computes:

1. **BF (Bornhuetter-Ferguson) Ultimate** — `calc_BF_Inc_Loss()`:
   - `BF_Ultimate = Gross_Incurred + (1 - Cum_Percentages) * Premium * BF_IELR_modified`
   - IELR is modified using PAI/LTI trend adjustments
2. **CC (Cape Cod) Ultimate** — `calc_cc_IELR()`:
   - Computes a `trended_dev_LR` and weighted CC detrended LR
   - `CC_Ultimate = Gross_Incurred + (1 - Cum_Percentages) * Premium * CC_detrended_LR`
3. **LR (Loss Ratio) Ultimate** — `calc_LR_Ultimate()`:
   - Uses the selected LR method and applies the appropriate LR to compute ultimate
4. **DFM (Development Factor Method) Ultimate** — already computed as `Cum_Factors * Gross_Incurred`

#### Step 12: Method Selection by Exposure Year (Lines 1307–1335)

1. First checks which methods are **valid** (have non-zero inputs): `get_valid_methods()`
2. Calls `fn_select_ultimate_by_exp_year()` which:
   - For each exposure year, simulates which method would produce the lowest RMSE
   - Uses a threshold-based approach — immature years typically use LR or BF, mature years use DFM
   - Returns selected method and ultimate per exposure year

#### Step 13: Summary & Result Assembly (Lines 1329–1372)

Assembles `summary_CoU_df` (Change of Ultimate summary) and a comprehensive `result_list` containing 25+ dataframes covering every intermediate and final result.

#### Step 14: Ceded Calculations (Lines 1377–1562)

**Only runs if `Ri_type_run == 'Both'`.**

1. Replicates gross results for all RI types
2. Computes ceded age-to-age factors separately
3. Computes ceded ultimates using:
   - BF, CC, LR methods (same as gross)
   - **Recovery Ratio methods** — unique to ceded:
     - `Paid_RR_Ultimate` — based on paid recovery ratio
     - `Incurred_RR_Ultimate` — based on incurred recovery ratio
     - `Premium_RR_Ultimate` — based on premium recovery ratio
4. **Ceded method selection logic (Lines 1525–1534):**
   - If `Cum_Percentages > pattern_threshold (0.6)`: use `Incurred_RR_Ultimate`
   - If `0.4 < Cum_Percentages ≤ 0.6`: use `Premium_RR_Ultimate`
   - If `Cum_Percentages ≤ 0.4` or current year: use `LR_Ultimate`

---

### CHUNK 6 (Lines 1574–1675): Parallel Execution

#### Profile List & Global Variables (Lines 1576–1621)

Creates global tracking variables for all profiles:

| Variable | Purpose |
|---|---|
| `profiles_list` | List of all profile IDs to run |
| `function_counter` | Tracks recursive call count per profile |
| `index_replacement_tracker` | Matrix tracking which indices were replaced per profile |
| `iterations_list` | Stores all generated iterations per profile |
| `profile_run_time` | Wall-clock time per profile |
| `profile_run_success_flag` | Success/failure per profile |
| `profile_iteration_converged` | Whether at least 1 iteration converged per profile |
| `profile_iter_algo_curves_use_num` | Number of curves to use (starts at 2, can increase to 4) |

#### Error Handling & Parallel Execution (Lines 1630–1675)

1. `final_run_MBR()` wraps `run_mbr()` in `tryCatch()`, writing errors to a log CSV
2. Uses `parallel::makeCluster(10)` — creates 10 parallel R processes
3. Saves entire workspace to `2026_Q3.RData`, loads it into each cluster node
4. Runs `parLapply(clust, profiles_list, final_run_MBR)` — parallel execution
5. After completion: stops cluster, records total time, saves workspace again

---

### CHUNK 7 (Lines 1680–2019): Diagnostics Data Preparation

Extracts all result dataframes from `mbr_results` (the list of per-profile results) into combined dataframes using `bind_rows(lapply(...))`. 25+ dataframes are extracted.

Key post-processing:
1. **Factor-to-character conversions** for SQL compatibility (Lines 1714–1725)
2. **IBNR calculation**: `sum(SelectedUltimate - Gross_Incurred)` (Line 1733)
3. **All-years incurred backfill** (Lines 1737–1756): For exposure years excluded from MBR analysis (zeroed out), replaces 0 values with actual incurred data
4. **Completion-of-Triangle (CoT)** calculation (Lines 1761–1813):
   - For lower-triangle cells (future), distributes IBNR across development periods
   - `ibnr_runoff = ibnr * (cum_pct[dev] - cum_pct[prev_dev]) / (1 - cum_pct[max_dev])`
   - Separate handling for Long-tailed (YY level, step=12) vs S/M (YQ level, step=3)
5. **LDF unpivot transformation** (Lines 1827–1871): Converts wide-format LDF matrices to long format for SQL export, handling L vs S/M differently for development period mapping
6. **Interpolation for Long-tailed profiles** (Lines 1984–2007): Converts YY cumulative percentages to YQ via interpolation using `calc_interpolation()` and `func_convert_after_first_one()`
7. **SLU_Analysis_Type** column added to all dataframes (Lines 1937–1965)

---

### CHUNK 8 (Lines 2023–2203): MBR Output for Vena

Formats MBR results for upload back to Vena:
1. **MBR Cumulative Percentages** — formatted with Vena dimension columns (`_Reserving Quarter`, `_Reserve Class`, `_Vector`, etc.)
2. **MBR Available Flag** — indicator that MBR ran successfully for this profile
3. **Extra development period record** — adds one more record per profile: dev_len=294 (if Q1) or 300 (if Q3) with value=1
4. **SML Flag Map for Vena** — S→"Short", M→"Medium", formatted for Vena upload
5. **Previous patterns comparison** — reads previous patterns CSV and computes differences to verify consistency

---

### CHUNK 9 (Lines 2208–2457): SQL Export

1. Reconnects to Azure SQL
2. **Deletes** existing data for the current run's profiles/year/quarter from ~25 SQL tables in `afr_analytics` schema
3. **Appends** fresh results using `dbAppendTable()` to each table
4. Special handling for `MBR_vena_vectors`: reads SQL column order and reorders the dataframe to match
5. Movement vectors are extracted and exported separately

**SQL tables written (afr_analytics schema):**
- `MBR_age_to_age_outliers`
- `MBR_cumulative_incurred_loss`
- `MBR_influential_points`
- `MBR_curve_fit`
- `MBR_curve_fit_r_squared`
- `MBR_dev_prop_incurred`
- `MBR_factor_one_index`
- `MBR_iteration_weighted_RMSE`
- `MBR_all_origin`
- `MBR_actuarial_method_ultimates`
- `MBR_ultimate_methods_to_use`
- `MBR_best_iteration`
- `MBR_exp_year_selected_ultimate_rmse`
- `MBR_exp_year_selected_ultimate_working`
- `MBR_summary_CoU`
- `MBR_algorithm_indexes`
- `MBR_completion_of_triangle`
- `MBR_exp_year_max_dev_len`
- `MBR_tail_factor`
- `MBR_cumulative_incurred_loss_YY`
- `MBR_initial_selected_averages`
- `MBR_initial_selected_averages_wo_outliers_removal`
- `MBR_initial_selection_summary`
- `MBR_best_iteration_interpolated`
- `MBR_YQ_incurred_triangles`
- `MBR_vena_vectors`
- `MBR_vena_LDF_dev_period`
- `MBR_vena_vectors_method_names`
- `MBR_YQ_paid_triangles`
- `MBR_movement_vector_vena`

---

### CHUNK 10 (Lines 2460–2514): Excel Export

Writes key result dataframes to Excel files at `/mnt_delfi0002_actuarial/Base Ultimate Calculation Template/MBR Development/`.

---

### CHUNK 11 (Lines 2518–2586): SQL Table Creation (One-Time)

Contains `dbCreateTable()` statements for initial table creation in `dbo` schema. Run once only.

---

### CHUNKS 12–13 (Lines 2592–2870): MBR Phase-1 Ranking (Legacy)

**Purpose:** Compare MBR results against AFR (Actuarial Financial Reporting) manual selections to score how well MBR replicates human selections.

Two RMSE metrics:
1. **Pattern RMSE** — compares MBR vs AFR cumulative percentage developed across all development periods
2. **IBNR RMSE** — compares MBR vs AFR selected IBNR per exposure year, weighted by IBNR magnitude

Also tracks method selection agreement (same ultimate method selected by MBR and valuation).

---

### Lines 2896–3924: Duplicate `run_mbr()` for Ceded Development

A copy of `run_mbr()` with a hardcoded profile (`AH_Wholesale_ROW_UY`) used for ceded development/testing. Not part of the production flow.

---

---

## FILE 2: MBR_vena_data_transformation_adhoc.R.txt (467 lines)

This file defines **3 data transformation functions** that reshape raw Vena extract data into the format required by the MBR algorithm.

---

### Function 1: `fn_to_transform_incurred_paid()` (Lines 12–66)

**Purpose:** Transform raw incurred or paid loss triangle data from Vena extract format to MBR input format.

**Parameters:**
| Parameter | Description |
|---|---|
| `incurred_raw` | Raw data from `vena_stage.t_f_vena_SLU_Inc_paid_sparta_grain` |
| `res_year` | Analysis year (2026) |
| `res_qtr` | Analysis quarter (3) |
| `val_flag` | Valuation flag (1) |
| `vector_name` | Either `'Incurred Loss'` or `'Paid Loss'` |

**Steps:**
1. **Rename columns** (Line 15): Maps SQL column names to working names
2. **Drop columns** `_PLOB` and `Branch` (Line 16)
3. **Validation checks:**
   - Only 1 reserving quarter in data (Line 23)
   - No null values in Vector or value (Line 28)
   - Only the expected vector name present (Line 33)
4. **Filter** (Line 41): Remove `Development_Period == "Adj Period"` and keep only `Type == "ATT"` (Attritional)
5. **Aggregate** (Lines 43–44): `sum(value)` grouped by `(Product, Vector, Development_Period, Exposure_Year, Reserving_Quarter, Version, Measure)` — collapses branch-level data to profile level
6. **Add metadata columns:** `Res_Year`, `Res_Qtr`, `Val_flag`
7. **Rename Vector** to include `(Att)` suffix
8. **Reorder and return** with columns: `(res_year, res_qtr, val_flag, Product, Vector, Development Period, Exposure Year, Reserving Quarter, Version, Measure, Value)`

---

### Function 2: `fn_to_transform_method_data()` (Lines 76–188)

**Purpose:** Transform method-selection string data from Vena into a wide-format dataframe with one column per method vector.

**Parameters:**
| Parameter | Description |
|---|---|
| `method_raw` | Raw data from `vena_stage.t_f_vena_SLU_reserveclass_AY_vectors` (method name vectors only) |
| `res_year`, `res_qtr`, `val_flag` | Analysis period identifiers |
| `Ri_type_run` | `'Gross'` or `'Both'` |

**Steps:**
1. **Rename columns** (Line 78)
2. **Drop columns** `_PLOB`, `Branch`, `AY / UY` (Line 79)
3. **Validation:**
   - Only 1 quarter in data (Line 86)
   - All 7 required method vectors present (Lines 91–98)
4. **Filter** (Line 101): Keep only the 7 method vectors, non-numeric values, and `Type == "ATT"`
5. **Deduplicate** (Line 103): Keep distinct rows by key columns
6. **Pivot wide** (Line 104): `spread(key=Vector, value=value)` — creates one column per method vector
7. **Conditional column selection** based on `Ri_type_run`:
   - If `'Both'`: includes all method columns including Recovery Ratio
   - If `'Gross'`: sets Recovery Ratio methods to "NA"
8. **Add metadata** and `MBR Ultimate Selected Flag = "No"` (Line 180)
9. **Return** wide-format method dataframe

---

### Function 3: `fn_to_transform_vena_all_data()` (Lines 197–455)

**Purpose:** Transform all Vena numeric vectors (everything except LDFs and method names) into a wide-format dataframe, plus prepare a separate LDF dataframe.

**Parameters:**
| Parameter | Description |
|---|---|
| `vena_data` | Raw data from `vena_stage.t_f_vena_SLU_reserveclass_AY_vectors` (numeric vectors) |
| `res_year`, `analysis_qtr`, `analysis_val_flag` | Analysis period |
| `years_analyzed` | Lookback years (25) |

**Steps:**

1. **Load vector mapping** (Line 200): Reads `Old_New_vector_mapping_ceded_new.csv` — maps between old/new vector names and identifies data granularity level (Branch, Profile, or Sparta)
2. **Categorize vectors by granularity** (Lines 228–233):
   - `Only_Branch` — vectors that exist at branch level and need aggregation to profile
   - `Only_Profile` — vectors already at profile level
   - `Only_Sparta` — vectors at Sparta (branch + PLOB) level needing aggregation
3. **Aggregate branch → profile** (Lines 236–241): Filter to `Branch != 'No Branch'` and `PLOB == 'No PLOB'`, then sum by `(Product, Vector, Exposure_Year, Measure)`
4. **Aggregate Sparta → profile** (Lines 244–249): Filter to `Branch != 'No Branch'` and `PLOB != 'No PLOB'`, then sum
5. **Filter profile-level** (Lines 251–256): Keep `Branch == 'No Branch'` and `PLOB == 'No PLOB'`, exclude `Incurred Percentage Developed`
6. **Combine** all three levels (Lines 259–260)
7. **Validation:** Check required vectors present, check reserving quarter matches
8. **LDF handling** (Lines 285–312):
   - Filter `incurred_pattern_raw` (global variable, loaded in main code) for `Branch == 'No Branch'` and `PLOB == 'No PLOB'`
   - Create `exp_year_dev_month` mapping: maps each development period to its corresponding exposure year
   - Join LDF data with this mapping to assign exposure years
   - Remove LDFs that don't map to a valid exposure year
9. **Create complete grid** (Lines 319–337): Cross-join of `(Product × Vector × Exposure_Year × Measure)`, filled with value=0
10. **Fill actuals** (Lines 349–352): Left-join actual values onto the grid, replacing 0 with actual where available
11. **Apply old→new vector mapping** (Lines 355–370)
12. **Pivot wide** (Lines 409–413): `spread(key=Vector, value=value)` — one column per vector
13. **Add LDF column** (Lines 416–418): Join `Incurred Percentage Developed` from LDF dataframe. Missing values default to 1 (fully developed).
14. **Prepare LDF export format** (Lines 433–446)
15. **Return** a list of 2 elements:
    - `[[1]]` — wide-format Vena data (all vectors as columns)
    - `[[2]]` — LDF data by development period

---

## KEY DATA FLOW SUMMARY

```
SQL/Vena Extract
    │
    ├── incurred_raw ──→ fn_to_transform_incurred_paid() ──→ actuals_all_profiles
    ├── paid_raw ──→ fn_to_transform_incurred_paid() ──→ paid_yq_all_profiles
    ├── vena_data_extract_raw ──→ fn_to_transform_vena_all_data() ──→ inputs_vena_all_profiles + vena_ldf
    ├── method_raw_extract ──→ fn_to_transform_method_data() ──→ inputs_vena_method_names_all_profiles
    └── profile_mapping (filter: run_flag==1)
          │
          ▼
    Triangle Construction (fill missing, compute cumulative, YQ→YY)
          │
          ▼
    SML Classification (S/M/L per profile)
          │
          ▼
    Profile Filtering (≥5 years of non-zero data)
          │
          ▼
    ┌─────────────── FOR EACH PROFILE (parallelized, 10 cores) ───────────────┐
    │                                                                          │
    │  1. Outlier Detection (adjusted boxplot on age-to-age factors)           │
    │  2. VW Average Selection (best n by RMSE)                                │
    │  3. CDF & Incurred % Developed                                           │
    │  4. Curve Fitting (4 distributions)                                       │
    │  5. Factor-One Index (where LDF → 1)                                     │
    │  6. <1 Factor Analysis                                                    │
    │  7. Iteration Algorithm (recursive, constraint-based)                     │
    │  8. Best Iteration Selection (minimum weighted RMSE)                      │
    │  9. Tail Factor                                                           │
    │  10. Actuarial Method Ultimates (DFM, BF, CC, LR)                        │
    │  11. Method Selection by Exposure Year                                    │
    │  12. Ceded Calculations (if Ri_type_run == 'Both')                       │
    │                                                                          │
    └──────────────────────────────────────────────────────────────────────────┘
          │
          ▼
    Post-Processing (CoT, interpolation, Vena formatting)
          │
          ▼
    Export to SQL (afr_analytics schema, ~30 tables)
    Export to Excel
    Export to Vena CSV
```
