# MBR / SLU Code Documentation

## What This Is

Complete documentation of the Machine Based Reserves (MBR) / Selected Loss Ultimate (SLU) codebase — an automated actuarial loss reserving system written in R. This documentation was created to support understanding the system for conversion to Python/PySpark.

## Reading Order

### If you're new to all of this (start here):
1. **[00 — High-Level Overview](00_HIGH_LEVEL_OVERVIEW.md)** — What MBR does, the full pipeline, glossary of terms
2. **[02 — Loss Triangles & SML](02_LOSS_TRIANGLES_AND_SML.md)** — Core concept: what loss triangles are, how they're built
3. **[03 — Outlier Detection](03_OUTLIER_DETECTION.md)** — How bad data points are identified and excluded
4. **[04 — Volume-Weighted Averages](04_VOLUME_WEIGHTED_AVERAGES.md)** — How initial LDF selections are made
5. **[05 — Curve Fitting](05_CURVE_FITTING.md)** — Four mathematical models fit to the LDF pattern
6. **[06 — Iteration Algorithm](06_ITERATION_ALGORITHM.md)** — **The core algorithm** — recursive tree-search for valid LDF sequences
7. **[07 — Actuarial Methods](07_ACTUARIAL_METHODS.md)** — Four methods to estimate ultimate losses (DFM, BF, CC, LR)
8. **[08 — Method Selection](08_METHOD_SELECTION.md)** — How the best method is picked per exposure year
9. **[09 — Tail Factors & Indexes](09_TAIL_FACTORS_AND_INDEXES.md)** — Development beyond the observed triangle
10. **[10 — Ceded/Reinsurance](10_CEDED_REINSURANCE.md)** — How reinsurance calculations work
11. **[11 — Interpolation](11_INTERPOLATION.md)** — Converting annual patterns to quarterly
12. **[01 — Data Pipeline & Inputs](01_DATA_PIPELINE_AND_INPUTS.md)** — SQL sources, Vena ETL, output tables
13. **[12 — Parallel Processing & Export](12_PARALLEL_PROCESSING_AND_EXPORT.md)** — How profiles run in parallel, output destinations

### If you're planning the Python conversion:
- **[13 — R to Python Conversion Guide](13_R_TO_PYTHON_CONVERSION_GUIDE.md)** — Library mapping, global state refactoring, PySpark strategy, testing plan

### For line-by-line detail during actual conversion:
- **[A1 — Main Orchestrator Reference](A1_REF_main_orchestrator.md)** — Line-by-line analysis of `SLU_main_code.R.txt` and `MBR_vena_data_transformation_adhoc.R.txt`
- **[A2 — Curve Fit, Weighted Avg, Interpolation Reference](A2_REF_curve_weight_interp.md)** — Line-by-line analysis of 3 files
- **[A3 — Factor Indexes & Iteration Algorithm Reference](A3_REF_factors_iteration.md)** — Line-by-line analysis of 3 files
- **[A4 — Actuarial Methods & Selection Reference](A4_REF_methods_selection.md)** — Line-by-line analysis of 3 files

## File Map

```
docs/
├── README.md                          ← You are here
├── 00_HIGH_LEVEL_OVERVIEW.md          ← Start here: pipeline, glossary, reading paths
├── 01_DATA_PIPELINE_AND_INPUTS.md     ← SQL sources, Vena ETL, ~30 output tables
├── 02_LOSS_TRIANGLES_AND_SML.md       ← Triangle concepts, YQ/YY, SML classification
├── 03_OUTLIER_DETECTION.md            ← Adjusted boxplot, medcouple, worked example
├── 04_VOLUME_WEIGHTED_AVERAGES.md     ← VW formula, best-n selection, CDF derivation
├── 05_CURVE_FITTING.md                ← 4 distributions, Cook's distance, R² ranking
├── 06_ITERATION_ALGORITHM.md          ← Recursive tree-search (core of MBR)
├── 07_ACTUARIAL_METHODS.md            ← DFM, BF, CC, LR with formulas & examples
├── 08_METHOD_SELECTION.md             ← Rule-based + RMSE hindsight simulation
├── 09_TAIL_FACTORS_AND_INDEXES.md     ← Factor-one index, <1 detection, tail factor
├── 10_CEDED_REINSURANCE.md            ← Recovery ratios, ceded method selection
├── 11_INTERPOLATION.md                ← Cubic spline annual→quarterly
├── 12_PARALLEL_PROCESSING_AND_EXPORT.md ← parLapply, SQL/Excel/Vena export
├── 13_R_TO_PYTHON_CONVERSION_GUIDE.md ← Library map, refactoring, PySpark, testing
├── A1_REF_main_orchestrator.md        ← Line-by-line: main code + Vena transform
├── A2_REF_curve_weight_interp.md      ← Line-by-line: curve fit, weighted avg, interp
├── A3_REF_factors_iteration.md        ← Line-by-line: factor indexes, iteration algo
└── A4_REF_methods_selection.md        ← Line-by-line: actuarial methods, selection, RMSE
```

## Source Files → Documentation Map

| R Source File | Conceptual Doc | Reference Doc |
|---|---|---|
| `SLU_main_code.R.txt` (3924 lines) | 00, 01, 12 | A1 |
| `MBR_vena_data_transformation_adhoc.R.txt` (467 lines) | 01 | A1 |
| `MBR_weighted_average.R.txt` (133 lines) | 03, 04 | A2 |
| `MBR_curve_fit.R.txt` (575 lines) | 05 | A2 |
| `MBR_interpolation.R.txt` (80 lines) | 11 | A2 |
| `MBR_factor_one_index.R.txt` (51 lines) | 09 | A3 |
| `MBR_factor_less_than_one_index.R.txt` (64 lines) | 09 | A3 |
| `MBR_iteration_algorithm_0.99_modified.R.txt` (216 lines) | 06 | A3 |
| `MBR_actuarial_method_ultimates.R.txt` (163 lines) | 07 | A4 |
| `MBR_method_selection_by_exposure_year_cc_change.R.txt` (199 lines) | 08 | A4 |
| `MBR_threshold_ultimate_weighted_RMSE.R.txt` (80 lines) | 09 | A4 |
| `MBR_tail_factor_methods.R.txt` (52 lines) | 09 | A4 |
| `MBR_ceded_all_calculations.R.txt` (44 lines) | 10 | A4 |
| `MBR_iteration_weighted_rmse_sml.R.txt` (201 lines) | 04, 06 | A4 |
