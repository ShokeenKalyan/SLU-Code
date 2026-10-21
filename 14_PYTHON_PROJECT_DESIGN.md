# Python Project Design — MBR/SLU on Azure Databricks

This document covers three things:
1. **Project Structure** — how the Python code is organized and why
2. **Key Design Decisions** — what changes from R and why
3. **Task Breakdown & Timeline** — what to build, in what order, and how long it takes

---

## Part 1: Project Structure

### The folder layout

```
mbr_slu/
│
├── notebooks/
│   └── run_pipeline.py              ← The Databricks notebook that kicks everything off
│
├── mbr/
│   ├── __init__.py                  ← Makes this folder a Python package
│   ├── config.py                    ← All configuration (dates, thresholds, DB connection info)
│   ├── pipeline.py                  ← Runs the full pipeline for one profile (the "main" logic)
│   │
│   ├── data/
│   │   ├── __init__.py
│   │   ├── sql_reader.py            ← Reads data from Snowflake/SQL via Spark JDBC
│   │   ├── sql_writer.py            ← Writes results back to SQL / Delta tables
│   │   ├── vena_transform.py        ← The Vena ETL (converts Vena Excel → structured data)
│   │   └── excel_io.py              ← Excel read/write utilities
│   │
│   ├── triangles/
│   │   ├── __init__.py
│   │   ├── builder.py               ← Builds loss development triangles from raw data
│   │   └── outlier_detection.py     ← Adjusted boxplot outlier detection (medcouple)
│   │
│   ├── development/
│   │   ├── __init__.py
│   │   ├── weighted_average.py      ← Volume-weighted average LDFs (best-N selection)
│   │   ├── curve_fit.py             ← 4-curve parametric fitting (Weibull, etc.)
│   │   ├── iteration.py             ← The core iteration algorithm (tree-search)
│   │   └── rmse.py                  ← Weighted RMSE scoring (used everywhere)
│   │
│   ├── methods/
│   │   ├── __init__.py
│   │   ├── actuarial_methods.py     ← DFM, BF, Cape Cod, Loss Ratio ultimates
│   │   ├── method_selection.py      ← Rule-based + RMSE hindsight method selection
│   │   └── ceded.py                 ← Ceded/reinsurance calculations
│   │
│   ├── factors/
│   │   ├── __init__.py
│   │   ├── factor_one_index.py      ← Find where LDFs stabilize at 1.0
│   │   ├── factor_less_than_one.py  ← Detect sub-1.0 anomalous factors
│   │   ├── tail_factors.py          ← Tail factor computation
│   │   └── interpolation.py         ← Annual-to-quarterly spline interpolation
│   │
│   └── utils/
│       ├── __init__.py
│       └── helpers.py               ← Shared small utilities (date math, formatting, etc.)
│
├── tests/
│   ├── __init__.py
│   ├── test_triangles.py
│   ├── test_weighted_average.py
│   ├── test_curve_fit.py
│   ├── test_iteration.py
│   ├── test_actuarial_methods.py
│   ├── test_method_selection.py
│   ├── test_factors.py
│   ├── test_interpolation.py
│   ├── test_ceded.py
│   ├── test_rmse.py
│   └── fixtures/                    ← Saved R outputs used as test "golden" data
│       └── ...
│
└── requirements.txt                 ← Python dependencies
```

### How R files map to Python files

This table shows exactly where each R file's logic ends up:

| R Source File | Python File | Folder |
|---|---|---|
| `SLU_main_code.R.txt` (orchestration part) | `pipeline.py` | `mbr/` |
| `SLU_main_code.R.txt` (data loading part) | `sql_reader.py` | `mbr/data/` |
| `SLU_main_code.R.txt` (triangle building part) | `builder.py` | `mbr/triangles/` |
| `SLU_main_code.R.txt` (export part) | `sql_writer.py`, `excel_io.py` | `mbr/data/` |
| `MBR_vena_data_transformation_adhoc.R.txt` | `vena_transform.py` | `mbr/data/` |
| `MBR_weighted_average.R.txt` | `weighted_average.py` | `mbr/development/` |
| `MBR_iteration_weighted_rmse_sml.R.txt` | `rmse.py` | `mbr/development/` |
| `MBR_curve_fit.R.txt` | `curve_fit.py` | `mbr/development/` |
| `MBR_iteration_algorithm_0.99_modified.R.txt` | `iteration.py` | `mbr/development/` |
| `MBR_factor_one_index.R.txt` | `factor_one_index.py` | `mbr/factors/` |
| `MBR_factor_less_than_one_index.R.txt` | `factor_less_than_one.py` | `mbr/factors/` |
| `MBR_tail_factor_methods.R.txt` | `tail_factors.py` | `mbr/factors/` |
| `MBR_threshold_ultimate_weighted_RMSE.R.txt` | `rmse.py` (added here) | `mbr/development/` |
| `MBR_actuarial_method_ultimates.R.txt` | `actuarial_methods.py` | `mbr/methods/` |
| `MBR_method_selection_by_exposure_year_cc_change.R.txt` | `method_selection.py` | `mbr/methods/` |
| `MBR_ceded_all_calculations.R.txt` | `ceded.py` | `mbr/methods/` |
| `MBR_interpolation.R.txt` | `interpolation.py` | `mbr/factors/` |

---

## Part 2: Key Design Decisions (and why)

### Why this structure?

The R codebase has 1 giant main file (3,924 lines) and 13 helper files all sitting flat in one folder. That works in R because `source()` just dumps everything into one shared scope. Python does not work that way — it uses `import`, which means each file is a separate module with its own scope. This is actually an advantage: it forces cleaner boundaries.

The Python structure groups files by **what part of the pipeline they belong to**:

```
data/          → Getting data in and out
triangles/     → Building and cleaning the loss triangles
development/   → The core LDF selection process (VW avg → curves → iteration)
methods/       → Actuarial methods and final selection
factors/       → Tail factors, indexes, and interpolation
utils/         → Small shared helpers
```

If you are debugging why a tail factor looks wrong, you go to `mbr/factors/`. If the curve fit is failing, you go to `mbr/development/`. You never need to search a 3,924-line file.

### How the "global state" problem is solved

**The R problem:** The R code uses `<<-` (global assignment) roughly 50-80 times. Every function writes to shared global variables that other functions read. This means function A sets a variable, function B reads it, function C changes it — all without any of them declaring this in their signatures. It works, but it is very hard to trace what depends on what.

**The Python solution: a `ProfileState` dictionary.**

Instead of global variables, each profile gets a single dictionary that holds all its data as it flows through the pipeline. Each function takes this dictionary as input, reads what it needs, adds its results, and returns it.

```python
# In pipeline.py — simplified view of how a profile runs

def run_profile(profile_id, config):
    """Run the full MBR pipeline for one profile."""

    # This dictionary carries ALL data for this profile through the pipeline.
    # Each step reads from it and adds its results to it.
    state = {}

    # Step 1: Load data
    state["raw_data"] = sql_reader.load_profile_data(profile_id, config)
    state["vena_overrides"] = vena_transform.get_overrides(profile_id, config)

    # Step 2: Build triangles
    state["triangle"] = builder.build_triangle(state["raw_data"], config)

    # Step 3: Outlier detection
    state["outliers"] = outlier_detection.detect(state["triangle"])

    # Step 4: Volume-weighted averages
    state["vw_averages"] = weighted_average.compute(state["triangle"], state["outliers"])

    # Step 5: Score VW averages → pick best-N
    state["best_n"] = rmse.select_best_n(state["vw_averages"], state["triangle"])

    # Step 6: Curve fitting
    state["curves"] = curve_fit.fit_all(state["best_n"])

    # Step 7: Iteration algorithm
    state["iterations"] = iteration.run(state["best_n"], state["curves"])

    # Step 8: Score iterations → pick best
    state["selected_ldfs"] = rmse.select_best_iteration(state["iterations"], state["triangle"])

    # Step 9: Factor indexes
    state["factor_one_idx"] = factor_one_index.compute(state["selected_ldfs"])
    state["factor_lt_one"] = factor_less_than_one.compute(state["selected_ldfs"])

    # Step 10: Tail factors
    state["tail"] = tail_factors.compute(state["selected_ldfs"], state["curves"], state["factor_one_idx"])

    # Step 11: Actuarial methods
    state["ultimates"] = actuarial_methods.compute_all(state, config)

    # Step 12: Method selection
    state["selected"] = method_selection.select(state["ultimates"], state["triangle"], config)

    # Step 13: Ceded/reinsurance
    state["ceded"] = ceded.compute(state, config)

    # Step 14: Interpolation (long-tailed profiles only)
    if config.sml_flag == "L":
        state["quarterly"] = interpolation.convert(state["selected_ldfs"])

    return state
```

**Why this is better:**
- You can see exactly what each step needs and what it produces
- You can test any step in isolation by giving it a pre-built `state` dictionary
- You can print `state` at any point to see exactly what data exists
- No hidden dependencies — everything is explicit

### How parallel processing works on Databricks

In R, the code uses `parLapply` to process profiles across 10 CPU cores on a single machine. On Databricks, you have a cluster with many machines, so you get much more parallelism for free.

```python
# In notebooks/run_pipeline.py — the Databricks entry point

from mbr.config import load_config
from mbr.pipeline import run_profile
from mbr.data import sql_reader, sql_writer

# Load configuration
config = load_config()

# Get the list of profiles to process
profiles = sql_reader.get_profile_list(config)

# Option A: Simple loop (good for debugging — runs one at a time)
results = []
for profile_id in profiles:
    result = run_profile(profile_id, config)
    results.append(result)

# Option B: Spark parallel (production — distributes across cluster)
# Each profile runs independently on a different worker node
from pyspark.sql import SparkSession
spark = SparkSession.builder.getOrCreate()

profile_df = spark.createDataFrame([(p,) for p in profiles], ["profile_id"])
# Use pandas_udf or mapInPandas to run per-profile logic in parallel

# Export combined results
sql_writer.export_all(results, config)
```

The key insight: start with Option A (simple loop) during development. Switch to Option B (Spark parallel) only after everything works correctly. This makes debugging much easier.

### How SQL connectivity changes

| Aspect | R (current) | Python on Databricks |
|---|---|---|
| Connection | `RODBC::odbcDriverConnect()` | Spark JDBC (`spark.read.jdbc()`) or `pyodbc` |
| Read | `sqlQuery(conn, "SELECT ...")` | `spark.read.jdbc(url, table)` or `pd.read_sql()` |
| Write | `sqlSave(conn, df, table)` | `df.write.jdbc(url, table)` or Delta `df.write.format("delta")` |
| Delete+Append | `sqlQuery("DELETE..."); sqlSave(append=TRUE)` | `df.write.mode("overwrite")` |

On Databricks, you can also use **Delta tables** (an improved table format) which give you versioning, time-travel, and better performance. This is optional but recommended for output tables.

### How the iteration algorithm changes

The R iteration algorithm uses deep recursion (can go thousands of levels deep) and global variables to track the best solution. Python has a recursion limit of 1,000 by default.

**Solution:** Convert the recursion to an iterative approach using an explicit stack. This is a standard transformation:

```python
# Instead of:
def validate_iteration(ldfs, index):   # recursive — can blow the stack
    ...
    validate_iteration(ldfs, index+1)  # recurse deeper

# Use:
def validate_iteration(initial_ldfs, curves):  # iterative — no stack limit
    stack = [initial_state]                     # explicit stack
    best_result = None

    while stack and iteration_count < MAX_ITERATIONS:
        current = stack.pop()
        ...
        if is_valid(current):
            if is_better(current, best_result):
                best_result = current
        else:
            for branch in get_branches(current, curves):
                stack.append(branch)            # instead of recursing

    return best_result
```

Same logic, no recursion limit issues, and easier to debug because you can inspect the stack at any point.

### What each Python library is for

These are the libraries you will need (all available on Databricks by default or easily installable):

| Library | What it does | Used for |
|---|---|---|
| `pandas` | Data manipulation (tables, filtering, grouping) | Replaces R's `data.table`/`dplyr` |
| `numpy` | Numerical operations (arrays, math) | Replaces R's built-in vectorized math |
| `scipy` | Scientific computing | `curve_fit()` for NLS, `CubicSpline` for interpolation, `skew()` for skewness |
| `statsmodels` | Statistical models | `medcouple_1d()` for outlier detection |
| `openpyxl` | Excel file reading/writing | Replaces R's `openxlsx`/`readxl` |
| `pyodbc` | SQL database connectivity | Replaces R's `RODBC` (optional if using Spark JDBC) |
| `pyspark` | Spark interface (comes with Databricks) | Parallel processing, SQL reads/writes |

---

## Part 3: Task Breakdown & Timeline

### Overview

Total estimated duration: **14–18 weeks** (assuming one person, working on this as primary project).

The work is divided into 5 phases. Each phase builds on the previous one. You can validate each phase independently before moving to the next.

### Phase 1: Foundation & Data Layer (Weeks 1–3)

Set up the project, get data flowing in and out. No actuarial logic yet — just plumbing.

| # | Task | Description | Est. Days | R File(s) |
|---|---|---|---|---|
| 1.1 | Project setup | Create folder structure, `__init__.py` files, `requirements.txt`, Databricks repo setup | 1 day | — |
| 1.2 | Configuration module | `config.py` — evaluation date, thresholds, DB connection strings, SML parameters | 1 day | Parts of `SLU_main_code.R.txt` |
| 1.3 | SQL reader | Read triangles, premiums, and assumptions from Snowflake via Spark JDBC | 3 days | Parts of `SLU_main_code.R.txt` |
| 1.4 | Vena ETL | Convert Vena Excel transforms to Python | 3 days | `MBR_vena_data_transformation_adhoc.R.txt` |
| 1.5 | Triangle builder | Build YQ and YY triangles from raw data | 3 days | Parts of `SLU_main_code.R.txt` |
| 1.6 | SQL writer + Excel export | Write results to SQL/Delta tables and Excel | 2 days | Parts of `SLU_main_code.R.txt` |
| 1.7 | Tests for Phase 1 | Validate data matches R output for a few profiles | 2 days | — |

**Phase 1 milestone:** You can read data for any profile, build its triangle, and write results back. This proves the data pipeline works end-to-end.

### Phase 2: Core Development Factors (Weeks 4–8)

The mathematical heart of the system. This is the hardest phase.

| # | Task | Description | Est. Days | R File(s) |
|---|---|---|---|---|
| 2.1 | Outlier detection | Adjusted boxplot with medcouple | 2 days | `MBR_weighted_average.R.txt` (outlier part) |
| 2.2 | Volume-weighted averages | Best-N VW average computation | 3 days | `MBR_weighted_average.R.txt` (VW part) |
| 2.3 | Weighted RMSE scoring | RMSE for best-N selection and iteration scoring | 3 days | `MBR_iteration_weighted_rmse_sml.R.txt` |
| 2.4 | Best-N selection | Wire RMSE scoring to VW averages to pick best-N | 1 day | Part of `SLU_main_code.R.txt` |
| 2.5 | Curve fitting — Exponential Decay | First of 4 curves (simplest, good to establish pattern) | 2 days | `MBR_curve_fit.R.txt` |
| 2.6 | Curve fitting — Weibull | Second curve | 2 days | `MBR_curve_fit.R.txt` |
| 2.7 | Curve fitting — Power (Sherman) | Third curve | 1 day | `MBR_curve_fit.R.txt` |
| 2.8 | Curve fitting — Inverse Power | Fourth curve (has extra `c` parameter optimization) | 2 days | `MBR_curve_fit.R.txt` |
| 2.9 | Cook's distance + refit | Influential point detection and re-fitting for all 4 curves | 2 days | `MBR_curve_fit.R.txt` |
| 2.10 | Iteration algorithm | Convert recursive tree-search to iterative stack-based approach | 5 days | `MBR_iteration_algorithm_0.99_modified.R.txt` |
| 2.11 | Iteration RMSE selection | Score converged iterations, select best | 2 days | `MBR_iteration_weighted_rmse_sml.R.txt` |
| 2.12 | Tests for Phase 2 | Compare LDFs, curves, and selected iterations against R | 3 days | — |

**Phase 2 milestone:** For any profile, you can go from raw triangle → outlier-cleaned VW averages → curve fits → iterated LDF selection, and the numbers match R output.

### Phase 3: Actuarial Methods & Factors (Weeks 9–12)

Apply the selected LDFs to estimate ultimate losses.

| # | Task | Description | Est. Days | R File(s) |
|---|---|---|---|---|
| 3.1 | Factor-one index | Find where LDFs stabilize at 1.0 | 1 day | `MBR_factor_one_index.R.txt` |
| 3.2 | Factor-less-than-one detection | Detect anomalous sub-1.0 factors | 1 day | `MBR_factor_less_than_one_index.R.txt` |
| 3.3 | Tail factors | Compute tail factors from curve extrapolation | 2 days | `MBR_tail_factor_methods.R.txt` |
| 3.4 | Tail threshold RMSE | Determine where to truncate the tail | 1 day | `MBR_threshold_ultimate_weighted_RMSE.R.txt` |
| 3.5 | DFM (Chain Ladder) | Development Factor Method ultimates | 2 days | `MBR_actuarial_method_ultimates.R.txt` |
| 3.6 | Bornhuetter-Ferguson | BF method ultimates | 2 days | `MBR_actuarial_method_ultimates.R.txt` |
| 3.7 | Cape Cod | CC method ultimates (includes CC change logic) | 3 days | `MBR_actuarial_method_ultimates.R.txt` |
| 3.8 | Loss Ratio | LR method ultimates | 1 day | `MBR_actuarial_method_ultimates.R.txt` |
| 3.9 | Method selection | Rule-based + RMSE hindsight simulation | 3 days | `MBR_method_selection_by_exposure_year_cc_change.R.txt` |
| 3.10 | Ceded/reinsurance | Recovery ratios and ceded ultimates | 2 days | `MBR_ceded_all_calculations.R.txt` |
| 3.11 | Interpolation | Annual-to-quarterly cubic spline | 2 days | `MBR_interpolation.R.txt` |
| 3.12 | Tests for Phase 3 | Compare all ultimates and selections against R | 3 days | — |

**Phase 3 milestone:** The full pipeline works end-to-end for a single profile. All ultimates, method selections, and ceded calculations match R.

### Phase 4: Integration & Validation (Weeks 13–15)

Wire everything together, run all profiles, validate the whole system.

| # | Task | Description | Est. Days |
|---|---|---|---|
| 4.1 | Pipeline orchestrator | Wire all modules into `pipeline.py` with the `state` dictionary flow | 3 days |
| 4.2 | Profile loop (simple) | Run all profiles in a sequential loop, collect results | 2 days |
| 4.3 | Full export | Output to all destinations (SQL/Delta, Excel, Vena CSV) | 2 days |
| 4.4 | R vs Python comparison | Run both systems on the same data, compare all outputs numerically | 5 days |
| 4.5 | Fix discrepancies | Investigate and fix any numerical differences | 3 days |

**Phase 4 milestone:** The Python pipeline produces results that match R across all profiles within acceptable numerical tolerance.

### Phase 5: Parallelization & Production (Weeks 16–18)

Make it production-ready on Databricks.

| # | Task | Description | Est. Days |
|---|---|---|---|
| 5.1 | Spark parallelization | Distribute profile processing across Databricks cluster | 3 days |
| 5.2 | Error handling & logging | Add proper logging, error recovery per profile (like R's tryCatch) | 2 days |
| 5.3 | Databricks Workflow setup | Schedule as a recurring Databricks job (replaces R's manual/cron execution) | 2 days |
| 5.4 | Performance testing | Run full portfolio, measure timing, optimize bottlenecks | 3 days |
| 5.5 | Documentation | Update code comments, write runbook for operations | 2 days |
| 5.6 | Handoff & knowledge transfer | Walk through code with team, document decisions | 3 days |

**Phase 5 milestone:** The system runs in production on Databricks, scheduled automatically, with monitoring and logging.

### Timeline Summary

```
Week  1–3   ████████░░░░░░░░░░  Phase 1: Foundation & Data Layer
Week  4–8   ░░░░░░░████████████  Phase 2: Core Development Factors (hardest)
Week  9–12  ░░░░░░░░░░░████████  Phase 3: Actuarial Methods & Factors
Week 13–15  ░░░░░░░░░░░░░░░████  Phase 4: Integration & Validation
Week 16–18  ░░░░░░░░░░░░░░░░░██  Phase 5: Parallelization & Production
```

### Risk areas (where things might take longer)

| Risk | Why | Mitigation |
|---|---|---|
| Iteration algorithm conversion | Deep recursion → iterative stack is tricky to get right | Allocate extra time (5 days). Test extensively with known R outputs. |
| Numerical precision differences | R and Python floating-point behavior can differ slightly | Use `np.allclose(rtol=1e-6)`. Accept small differences. Track and document them. |
| Curve fit convergence | `scipy.curve_fit` may converge differently than R's `nls()` | Test with same starting values. May need to tune optimization parameters. |
| Vena ETL complexity | Lots of edge cases in Excel parsing | Have sample Vena files for testing. Build incrementally. |
| SML branching logic | Different paths for Short/Medium/Long scattered throughout | Test with one profile from each SML category from the start. |

### How to track progress

A simple tracking approach: mark each task with a status.

| Status | Meaning |
|---|---|
| `NOT STARTED` | Haven't begun work |
| `IN PROGRESS` | Actively working on it |
| `BLOCKED` | Waiting on something (note what) |
| `IN REVIEW` | Code written, comparing against R output |
| `DONE` | Matches R output, tests pass |

Update the task table above weekly. Share the phase-level summary with stakeholders:

> "Phase 2 — Core Development Factors: 7 of 12 tasks done. On track for Week 8 completion. Curve fitting is complete. Iteration algorithm is in progress — converting recursion to iterative stack."

---

## Quick Reference: R → Python Library Mapping

| R | Python | Install |
|---|---|---|
| `data.table` / `dplyr` / `tidyr` | `pandas` | Pre-installed on Databricks |
| `RODBC` | `pyodbc` or Spark JDBC | Spark JDBC is built-in |
| `stats::nls()` | `scipy.optimize.curve_fit()` | Pre-installed on Databricks |
| `robustbase::mc()` | `statsmodels.stats.statlib.medcouple_1d()` | `pip install statsmodels` |
| `moments::skewness()` | `scipy.stats.skew()` | Pre-installed on Databricks |
| `stats::splinefun()` | `scipy.interpolate.CubicSpline()` | Pre-installed on Databricks |
| `ChainLadder` | Manual triangle ops with pandas | — |
| `parallel::parLapply()` | PySpark / `concurrent.futures` | Built-in |
| `openxlsx` / `readxl` | `openpyxl` | `pip install openpyxl` |
| `stringr` | Python built-in `str` methods | Built-in |
| `lubridate` | Python `datetime` / `pandas.Timestamp` | Built-in |
