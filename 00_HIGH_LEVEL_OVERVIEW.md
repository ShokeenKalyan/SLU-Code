# Machine Based Reserves (MBR) — High-Level Overview

## What is MBR?

An automated actuarial loss reserving system written in R that estimates IBNR (Incurred But Not Reported) reserves for insurance business lines. It replaces manual actuarial judgment with algorithmic selection of loss development patterns and actuarial methods. Run quarterly as part of the reserving cycle.

## Business Context

Insurance companies must estimate how much money they'll eventually pay on claims already occurred but not fully reported/paid. This is "loss reserving." Traditional approach: actuaries manually analyze development patterns and select methods. MBR automates this using statistical curve fitting, an optimization algorithm to find valid development patterns, and RMSE-based model selection.

## End-to-End Processing Pipeline

```
SQL Server (ODBC)  ──→  Import triangles, assumptions  ──→  Per-profile parallel processing (10 cores)
                                                                          │
                            ┌─────────────────────────────────────────────┘
                            ▼
                   ┌──────────────────────────────────────────────────────────────┐
                   │  FOR EACH PROFILE (run_mbr function):                        │
                   │                                                              │
                   │  1. Triangle Construction (YQ or YY based on SML)           │
                   │  2. Outlier Detection (adjusted boxplot on age-to-age)      │
                   │  3. Volume-Weighted Averages (test n=3,4,5,...,24)          │
                   │  4. Best VW Period Selection (by weighted RMSE)             │
                   │  5. Curve Fitting (Exponential, Weibull, Power, Inv.Power)  │
                   │  6. Iteration Algorithm (recursive tree-search, ≥0.99,     │
                   │     monotonically decreasing, up to 11,000 iterations)      │
                   │  7. Best Iteration Selection (min weighted RMSE)            │
                   │  8. Tail Factor (experience method)                         │
                   │  9. Actuarial Methods (DFM, BF, CC, LR ultimates)          │
                   │  10. Method Selection per Exposure Year (rules + RMSE)      │
                   │  11. Ceded/Reinsurance Calculations                         │
                   │                                                              │
                   │  Returns: ~25 result dataframes                             │
                   └──────────────────────────────────────────────────────────────┘
                            │
                            ▼
                   Combine results across all profiles
                            │
                            ▼
              ┌─────────────┼───────────────┐
              ▼             ▼               ▼
        SQL Server     Excel files     Vena CSVs
        (~30 tables)   (shared drive)  (financial planning)
```

## Key Configuration Parameters

- `analysis_year = 2026`, `analysis_qtr = 3` — the valuation date
- `years_analyzed = 25` — max development periods
- `S = 10` (short-tail), `M = 14` (medium), `L = 24` (long) — years analyzed by SML type
- `years_capped = 14` — caps how far back exposure years go
- `iteration_num_threshold = 11000` — max recursive iterations per profile
- `outlier_detection_min_points = 5` — minimum data points for outlier detection
- `factor_1_index_threshold = 0.02` — 2% remaining incurred signals end of development
- `default_first_index` and `default_last_index` — algorithm operating range
- SML Classification: Short (avg duration <3yr), Medium (3-5yr), Long (>5yr)
- YQ triangles (quarterly dev periods 3,6,9,...) for S/M; YY triangles (annual dev periods 12,24,...) for L

## Source Files

| File | Lines | Description |
|------|-------|-------------|
| `SLU_main_code.R.txt` | 3924 | Main orchestrator: imports, parallel processing, `run_mbr()`, result collection, SQL/Excel/Vena export |
| `MBR_weighted_average.R.txt` | 133 | Outlier detection (adjusted boxplot) and volume-weighted n-period averages |
| `MBR_curve_fit.R.txt` | 575 | Four curve fitting functions with Cook's distance influential point removal |
| `MBR_iteration_algorithm_0.99_modified.R.txt` | 216 | Recursive tree-search algorithm building valid LDF sequences |
| `MBR_iteration_weighted_rmse_sml.R.txt` | 201 | Weighted RMSE for VW period selection and best iteration selection |
| `MBR_factor_one_index.R.txt` | 51 | Finds development period where incurred development effectively ends |
| `MBR_factor_less_than_one_index.R.txt` | 64 | Detects significant below-1 factor patterns |
| `MBR_tail_factor_methods.R.txt` | 52 | Tail factor calculation (experience method, NCCI) |
| `MBR_actuarial_method_ultimates.R.txt` | 163 | BF, Cape Cod, Loss Ratio ultimate calculations |
| `MBR_method_selection_by_exposure_year_cc_change.R.txt` | 199 | Rule-based + RMSE-based method selection per exposure year |
| `MBR_threshold_ultimate_weighted_RMSE.R.txt` | 80 | Upper triangle back-calculation RMSE for quality validation |
| `MBR_ceded_all_calculations.R.txt` | 44 | Helper functions for ceded/reinsurance processing |
| `MBR_interpolation.R.txt` | 80 | Cubic spline interpolation (annual → quarterly for long-tail) |
| `MBR_vena_data_transformation_adhoc.R.txt` | 467 | ETL for Vena financial planning platform data |

## Processing Pipeline — Step by Step

### Step 1: Data Import (see `01_DATA_PIPELINE_AND_INPUTS.md`)

Import raw triangles, Vena assumption vectors, profile mappings, SML classifications from SQL Server via ODBC. Transform Vena extracts into structured formats.

### Step 2: Triangle Construction (see `02_LOSS_TRIANGLES_AND_SML.md`)

Build incremental and cumulative loss development triangles. YQ (quarterly) for short/medium-tailed lines, YY (annual) for long-tailed. Filter by SML-specific year ranges.

### Step 3: Outlier Detection (see `03_OUTLIER_DETECTION.md`)

Compute age-to-age development factors. Detect outliers using adjusted boxplot method with medcouple and skewness-adjusted bounds. Flag anomalous factors.

### Step 4: Volume-Weighted Averages (see `04_VOLUME_WEIGHTED_AVERAGES.md`)

Compute VW averages for multiple n-period windows. Select best n by weighted RMSE (excluding first dev period). Derive CDFs and cumulative percentages.

### Step 5: Curve Fitting (see `05_CURVE_FITTING.md`)

Fit 4 mathematical distributions to initial selections. Remove influential points via Cook's distance. Rank curves by R-squared. These provide replacement values for the iteration algorithm.

### Step 6: Iteration Algorithm (see `06_ITERATION_ALGORITHM.md`)

Recursive tree-search generates valid LDF sequences (>=0.99, monotonically decreasing) by substituting curve-fit values. Capped at 11,000 iterations. Two-phase: first with top 2 curves, then all 4 if needed.

### Step 7: Best Iteration Selection (see `06_ITERATION_ALGORITHM.md`)

Select converged iteration with minimum weighted RMSE between actual incurred-to-ultimate ratios and predicted cumulative percentages.

### Step 8: Tail Factors (see `09_TAIL_FACTORS_AND_INDEXES.md`)

Extrapolate development beyond the observed triangle. Experience method: product of initial LDFs beyond factor-one index. Applied to best iteration.

### Step 9: Actuarial Methods (see `07_ACTUARIAL_METHODS.md`)

Compute ultimates using four methods: DFM (Chain Ladder), BF (Bornhuetter-Ferguson), CC (Cape Cod), LR (Loss Ratio). Each uses different assumptions and data.

### Step 10: Method Selection (see `08_METHOD_SELECTION.md`)

For each exposure year, select the best actuarial method. Rules: >=85% developed leads to DFM, current year leads to LR, <=40% leads to LR. Middle years: hindsight RMSE simulation picks the best method.

### Step 11: Ceded Calculations (see `10_CEDED_REINSURANCE.md`)

Derive reinsurance (ceded) results from gross using recovery ratios. Separate method selection logic for ceded.

### Step 12: Interpolation (see `11_INTERPOLATION.md`)

For long-tailed profiles, cubic spline interpolation converts annual cumulative percentages to quarterly granularity.

### Step 13: Export (see `12_PARALLEL_PROCESSING_AND_EXPORT.md`)

Combine results across profiles. Delete-then-append to ~30 SQL tables. Export Excel workbooks and Vena CSVs.

## Glossary

| Term | Definition |
|------|-----------|
| **IBNR** | Incurred But Not Reported — the reserve for claims that have occurred but aren't fully reflected in current data |
| **LDF** | Loss Development Factor — ratio showing how cumulative claims grow from one period to the next (same as age-to-age factor) |
| **CDF** | Cumulative Development Factor — product of all remaining LDFs from a given period to ultimate |
| **Cum_Percentages** | 1/CDF — the proportion of ultimate losses developed so far (0 to 1) |
| **VW Average** | Volume-Weighted Average — weighted by the denominator's magnitude, giving more influence to larger exposure years |
| **SML** | Short/Medium/Long classification of business lines by their claim development speed |
| **DFM** | Development Factor Method (Chain Ladder) — Ultimate = Incurred x CDF |
| **BF** | Bornhuetter-Ferguson — blends actual development with an expected loss ratio |
| **CC** | Cape Cod — similar to BF but derives its expected loss ratio from the data itself |
| **LR** | Loss Ratio method — Ultimate = Premium x Expected Loss Ratio |
| **Exposure Year** | The year in which the insured exposure occurred (accident year or underwriting year) |
| **Development Period** | Time elapsed since the exposure year (in months: 3, 6, 9, ... for YQ; 12, 24, ... for YY) |
| **Loss Triangle** | Matrix with exposure years as rows, development periods as columns, showing how losses evolve |
| **Tail Factor** | Multiplier extrapolating development beyond the last observed period |
| **Cook's Distance** | Statistical measure of how much a regression changes when a single point is removed |
| **RMSE** | Root Mean Squared Error — measures prediction accuracy |
| **Ri_type** | Reinsurance type — Gross (total), or a specific ceded/reinsurance category |
| **Recovery Ratio** | Proportion of gross amount recovered from reinsurance (Premium, Incurred, or Paid basis) |
| **PAI** | Premium Adjustment Index — trends premium to a common level |
| **LTI** | Loss Trend Index — trends losses to a common level |
| **IELR** | Initial Expected Loss Ratio — actuarial estimate used in BF method |
| **Vena** | Financial planning platform used for assumptions input/output |
| **Profile** | A specific insurance product/line combination being analyzed |

## How to Read the Other Docs

- **New to actuarial concepts?** Start with `02_LOSS_TRIANGLES_AND_SML.md` then `03_OUTLIER_DETECTION.md`
- **Want to understand the core algorithm?** Read `04_VOLUME_WEIGHTED_AVERAGES.md` → `05_CURVE_FITTING.md` → `06_ITERATION_ALGORITHM.md`
- **Focus on business logic?** Read `07_ACTUARIAL_METHODS.md` → `08_METHOD_SELECTION.md`
- **Planning the Python conversion?** Read `13_R_TO_PYTHON_CONVERSION_GUIDE.md`
- **Understanding data flow?** Read `01_DATA_PIPELINE_AND_INPUTS.md` → `12_PARALLEL_PROCESSING_AND_EXPORT.md`
