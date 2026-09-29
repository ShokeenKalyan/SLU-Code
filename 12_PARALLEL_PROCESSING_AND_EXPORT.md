# Parallel Processing and Data Export

## Parallel Processing Architecture

MBR processes each insurance profile independently, allowing parallel execution across multiple CPU cores.

### Setup
```r
cl <- makeCluster(10)  # Create 10 worker processes
```

### Workspace Distribution
Before parallel execution, the main process:
1. Saves the entire workspace to an `.RData` file
2. Each worker loads this file to get access to shared data (Vena inputs, profile lists, etc.)
3. Each worker sources all module files (curve fit, iteration algorithm, etc.)

```r
# In each worker:
load("workspace.RData")
source("MBR_curve_fit.R.txt")
source("MBR_iteration_algorithm_0.99_modified.R.txt")
# ... all other module files
```

### Execution
```r
results <- parLapply(cl, profiles_to_run, run_mbr)
```
- `profiles_to_run`: character vector of profile IDs
- `run_mbr`: the main per-profile function
- Each worker runs `run_mbr(profile_id)` for its assigned profiles
- Workers run independently — no shared state during execution
- Results are collected as a list of `result_list_All` objects

### The run_mbr() Function (lines ~587-3827 in SLU_main_code.R.txt)

Processes ONE profile end-to-end:

```
Input:  profile_id_analyzed (string)
Output: result_list_All (named list of ~25 dataframes)

Steps:
  1. SML Classification → determine triangle type (YQ/YY), year range
  2. Triangle Construction → build incremental and cumulative matrices
  3. Outlier Detection → adjusted boxplot on age-to-age factors
  4. VW Averages → compute for multiple n values, select best by RMSE
  5. Curve Fitting → 4 distributions with Cook's distance removal
  6. Iteration Algorithm → recursive tree-search for valid LDF sequences
  7. Best Iteration → select by minimum weighted RMSE
  8. Tail Factors → experience method, apply to best iteration
  9. Actuarial Methods → compute DFM, BF, CC, LR ultimates
  10. Method Selection → pick best method per exposure year
  11. Ceded Calculations → derive reinsurance results from gross
  12. Package Results → return list of all output dataframes
```

## Result Collection

After parallel execution, results from all profiles are combined:

```r
# For each output type, bind rows across all profiles
age_to_age_outliers_df = rbindlist(lapply(results, function(x) x$age_to_age_outliers_df))
curve_fit_df = rbindlist(lapply(results, function(x) x$CurvefitValues_df))
# ... ~25 similar bindings
```

## SQL Export

### Pattern: Delete-Then-Append
For each output table:
1. **DELETE** existing rows for the current analysis period
2. **APPEND** new results

```r
# Step 1: Delete
dbGetQuery(con, paste("DELETE FROM afr_analytics.MBR_curve_fit 
  WHERE profile_id IN (", profiles_list_to_remove, ")
  AND res_year=", analysis_year, 
  " AND res_qtr=", analysis_qtr,
  " AND val_flag=", analysis_val_flag,
  " AND SLU_Analysis_Type='", SLU_analysis_type, "'"))

# Step 2: Type conversion (R factor → character for SQL compatibility)
curve_fit_df$Ri_type = as.character(curve_fit_df$Ri_type)

# Step 3: Append
dbAppendTable(con, SQL("afr_analytics.MBR_curve_fit"), curve_fit_df, row.names=NULL)
```

### Column Order Matching
For some tables, column order must match the SQL schema:
```r
sql_cols <- dbGetQuery(con, "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS 
  WHERE TABLE_SCHEMA='afr_analytics' AND TABLE_NAME='MBR_vena_vectors'")$COLUMN_NAME
vena_vectors_ordered <- vena_vectors %>% select(all_of(sql_cols))
```

### All Output SQL Tables (~30 tables in afr_analytics schema)

**Triangle Data:** MBR_cumulative_incurred_loss, MBR_cumulative_incurred_loss_YY, MBR_YQ_incurred_triangles, MBR_YQ_paid_triangles

**Outlier & VW Data:** MBR_age_to_age_outliers, MBR_initial_selected_averages, MBR_initial_selected_averages_wo_outliers_removal

**Curve Fit Data:** MBR_curve_fit, MBR_curve_fit_r_squared, MBR_influential_points

**Algorithm Data:** MBR_iteration_weighted_RMSE, MBR_best_iteration, MBR_best_iteration_interpolated, MBR_algorithm_indexes, MBR_initial_selection_summary

**Development Analysis:** MBR_factor_one_index, MBR_dev_prop_incurred, MBR_all_origin, MBR_completion_of_triangle, MBR_exp_year_max_dev_len, MBR_tail_factor

**Ultimate Results:** MBR_actuarial_method_ultimates, MBR_ultimate_methods_to_use, MBR_summary_CoU

**Method Selection:** MBR_exp_year_selected_ultimate_rmse, MBR_exp_year_selected_ultimate_working

**Vena Data:** MBR_vena_vectors, MBR_vena_LDF_dev_period, MBR_vena_vectors_method_names, MBR_movement_vector_vena

## Excel Export

Results also written to Excel on a shared network drive:
```
/mnt_delfi0002_actuarial/Base Ultimate Calculation Template/MBR Development/
├── MBR_output.xlsx              (multiple sheets: LDFs, curves, ultimates, methods, etc.)
├── MBR_output_triangle.xlsx     (cumulative incurred triangles)
├── MBR_output_curve_fit.xlsx    (curve fit values)
└── Various .csv files           (summaries, RMSE checks)
```

## Phase 1 Ranking (Quality Assessment)

The code includes a section (lines ~2590-2870) that compares MBR results against the manual actuarial (AFR) selections:

1. Import AFR (manual actuary) selected patterns and IBNR from the production database
2. Import MBR selected patterns and IBNR from the QA database
3. Compute RMSE between MBR and AFR on:
   - Development patterns (LDF comparison)
   - Selected IBNR amounts
4. Rank profiles by average RMSE — lower RMSE means MBR closely matches the actuary
5. Also track whether MBR selected the same method as the actuary per exposure year

This ranking helps identify which profiles MBR handles well and which need attention.
