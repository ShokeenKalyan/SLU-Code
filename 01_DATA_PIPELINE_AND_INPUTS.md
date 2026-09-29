# Data Pipeline and Inputs

## SQL Server Connection
- Uses R's `DBI` + `odbc` packages
- Connection string: `Driver={ODBC Driver 17 for SQL Server};server=...;database=...;uid=...;pwd=...`
- `con` object used throughout for `dbGetQuery()` (read) and `dbAppendTable()` (write)
- Multiple connection strings for different environments (production, QA)

## Data Sources
1. **Incurred Triangles** (`incurred_raw`): Raw Year-Quarter incurred loss data from Vena extract. Columns: Product (profile_id), Exposure Year, Development Period, Ri_type (Gross/ceded types), Incurred amounts
2. **Paid Triangles** (`paid_raw`): Raw Year-Quarter paid loss data, same structure
3. **Vena Assumption Vectors** (`vena_data_extract_raw`): Per profile, per exposure year: Premium, BF IELR, PAI, LTI, CC Exposure Weight, Previous Valuation CC Detrended LR, Actuarial LR, Financial Budget LR, Recovery Ratios (Paid/Incurred/Premium)
4. **Method Selection Data** (`method_raw_extract`): 7 method selection vectors from Vena (Selected LR Method, Premium Method, Ultimate Method, etc.)
5. **LDF Data** (`vena_ldf`): Loss development factor data from Vena
6. **Profile Mapping** (`MBR_profile_mapping`): Maps profiles to analysis parameters, includes `run_flag` (1=run this profile), `SLU_Analysis_Type`
7. **Average Duration / SML**: Per-profile average claim duration used for Short/Medium/Long classification
8. **Latest AY** (`Latest_Ay`): Maximum non-zero incurred year per profile per Ri_type

## Vena Data Transformation (`MBR_vena_data_transformation_adhoc.R.txt`)

### `fn_to_transform_incurred_paid()`
Transforms raw Vena incurred/paid extract into structured triangle format:
- Input: Raw Vena extract with columns like `[Incurred Loss (Att)]`, development period numbers
- Output: DataFrame with columns: `profile_id`, `exp_year`, `dev_len`, `Gross_Incurred`, `Cumulative_Gross_Incurred`, `Ri_type`
- Handles mapping of Vena column names to internal names

### `fn_to_transform_method_data()`
Parses 7 method selection string vectors from Vena:
- Selected LR Method, Selected Premium Method, Selected Ultimate Method, etc.
- Maps human-readable method names to internal codes

### `fn_to_transform_vena_all_data()`
Complex ETL orchestrator:
- **Branch-to-Profile aggregation**: Multiple Vena "branches" (e.g., sub-products) map to one MBR profile. Aggregates by summing numeric vectors.
- **Sparta-to-Profile aggregation**: Similar aggregation from Sparta naming convention
- **Old-to-new vector name mapping**: Handles renamed columns between Vena versions
- **LDF data integration**: Merges LDF vectors from separate Vena extract

## Key Vena Input Variables (per profile, per exposure year)
| Variable | Description | Used In |
|----------|-------------|---------|
| `Selected FY Ultimate Premium` | Earned premium for the year | BF, CC, LR methods |
| `BF IELR (Att)` | Initial Expected Loss Ratio | BF method |
| `Premium Adjustment Index` (PAI) | Trends premium to common level | BF, CC |
| `Loss Trend Index` (LTI) | Trends losses to common level | BF, CC |
| `CC Exposure Period Weight` | Weight for Cape Cod averaging | CC method |
| `Previous Valuation CC Detrended LR` | Prior quarter's CC result | CC method |
| `Actuarial LR (Att)` | Actuary-selected loss ratio | LR method |
| `Financial Budget LR (Att)` | Budget loss ratio | LR method |
| `Selected LR Method (Att)` | Which LR source to use | LR method |
| `to Gross Paid Recovery Ratio` | Paid reinsurance recovery % | Ceded calculations |
| `to Gross Incurred Recovery Ratio` | Incurred reinsurance recovery % | Ceded calculations |
| `to Gross Premium Recovery Ratio` | Premium reinsurance recovery % | Ceded calculations |

## Output Destinations

### SQL Tables (~30 tables in `afr_analytics` schema)
All follow delete-then-append pattern: DELETE existing rows for current analysis period, then APPEND new results.

**Core Output Tables:**
- `MBR_age_to_age_outliers` — Outlier detection results
- `MBR_cumulative_incurred_loss` — Cumulative triangles
- `MBR_cumulative_incurred_loss_YY` — Year-Year cumulative triangles
- `MBR_influential_points` — Cook's distance influential points
- `MBR_curve_fit` — Curve fit values for all 4 distributions
- `MBR_curve_fit_r_squared` — R² values per curve
- `MBR_dev_prop_incurred` — Development proportion of incurred
- `MBR_factor_one_index` — End-of-development index
- `MBR_iteration_weighted_RMSE` — RMSE per converged iteration
- `MBR_all_origin` — Best iteration's per-AY results
- `MBR_actuarial_method_ultimates` — All method ultimates
- `MBR_ultimate_methods_to_use` — Available methods per profile
- `MBR_best_iteration` — Best iteration factor details
- `MBR_best_iteration_interpolated` — Interpolated (quarterly) best iteration
- `MBR_exp_year_selected_ultimate_rmse` — Method selection RMSE
- `MBR_exp_year_selected_ultimate_working` — Method selection working data
- `MBR_summary_CoU` — Summary: Change of Ultimate
- `MBR_algorithm_indexes` — All algorithm index values
- `MBR_completion_of_triangle` — Triangle completion data
- `MBR_exp_year_max_dev_len` — Max development length per exposure year
- `MBR_tail_factor` — Tail factor values
- `MBR_initial_selected_averages` — VW averages with outlier removal
- `MBR_initial_selected_averages_wo_outliers_removal` — VW averages without outlier removal
- `MBR_initial_selection_summary` — Convergence summary
- `MBR_YQ_incurred_triangles` — Raw YQ incurred data
- `MBR_YQ_paid_triangles` — Raw YQ paid data
- `MBR_vena_vectors` — All Vena assumption vectors
- `MBR_vena_LDF_dev_period` — Vena LDF data
- `MBR_vena_vectors_method_names` — Vena method selection data
- `MBR_movement_vector_vena` — Movement analysis vectors

### Excel Export
Written to shared network drive: `/mnt_delfi0002_actuarial/Base Ultimate Calculation Template/MBR Development/`
- `MBR_output.xlsx` — Multiple sheets with key results
- `MBR_output_triangle.xlsx` — Cumulative incurred triangles
- `MBR_output_curve_fit.xlsx` — Curve fit details
- Various CSV files for summaries and RMSE checks
