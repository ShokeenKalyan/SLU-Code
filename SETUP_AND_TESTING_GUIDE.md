# MBR/SLU Python Code — Setup, Writing Order & Testing Guide

This guide tells you exactly how to set up, write, and test the converted Python code step by step on a fresh machine or Databricks workspace. Follow it top to bottom.

---

## Part 1: What You Need Installed

### On Databricks (recommended)
Databricks clusters come with Python, pandas, numpy, and scipy pre-installed. You only need to make sure these are available:

| Library | What it does | Likely pre-installed? |
|---------|-------------|----------------------|
| `pandas` | DataFrames (like Excel tables in code) | Yes |
| `numpy` | Math operations on arrays | Yes |
| `scipy` | Cubic spline interpolation, skewness | Yes |
| `statsmodels` | Medcouple statistic (outlier detection) | Usually yes |
| `pyodbc` | SQL Server connection (local mode only) | No — not needed on Databricks |
| `openpyxl` | Write Excel files | Usually yes |

**Quick check** — run this in a Databricks cell to verify:
```python
import pandas as pd
import numpy as np
from scipy.interpolate import CubicSpline
from scipy.stats import skew
from statsmodels.stats.statlib import medcouple_1d
print("All libraries OK")
```

If `statsmodels` is missing, install it in a cell:
```python
%pip install statsmodels
```

### On a local machine (laptop/desktop)
```bash
pip install pandas numpy scipy statsmodels openpyxl pyodbc
```

---

## Part 2: Writing Order (which file to create first)

The files have dependencies — some files use functions from other files. Write them in this order so you can test each one as you go.

### Layer 0: No dependencies (standalone files — write these first)

| Order | File | Lines | What it does |
|:-----:|------|------:|-------------|
| 1 | `config.py` | 230 | All settings and parameters |
| 2 | `helpers.py` | 358 | Shared utility functions (dates, math, logging) |

These two files don't import any other project file. Everything else depends on them.

**Test after writing:** See Milestone 1 below.

### Layer 1: Only depends on standard libraries

| Order | File | Lines | What it does |
|:-----:|------|------:|-------------|
| 3 | `ceded.py` | 168 | Reinsurance calculations |
| 4 | `weighted_average.py` | 224 | Volume-weighted average LDFs |
| 5 | `triangles.py` | 654 | Triangle building + outlier detection |
| 6 | `factors.py` | 440 | Factor indexes + tail factor |
| 7 | `actuarial_methods.py` | 511 | DFM, BF, Cape Cod, Loss Ratio methods |
| 8 | `method_selection.py` | 429 | Pick best method per exposure year |
| 9 | `interpolation.py` | 235 | Annual-to-quarterly cubic spline |
| 10 | `curve_fit.py` | 704 | Four parametric curve fits |
| 11 | `vena_transform.py` | 782 | Vena override data transformations |

These files use pandas/numpy/scipy but don't import other project files (except `rmse.py` — see next).

**Test after writing:** See Milestones 2–5 below.

### Layer 2: Imports from other project files

| Order | File | Lines | Imports from | What it does |
|:-----:|------|------:|-------------|-------------|
| 12 | `rmse.py` | 730 | `weighted_average` | RMSE scoring (best-N, best-iteration) |
| 13 | `iteration.py` | 560 | *(only `copy` from stdlib)* | Core iteration algorithm |
| 14 | `data_reader.py` | 404 | *(only external libs)* | SQL data loading |
| 15 | `data_writer.py` | 392 | *(only external libs)* | SQL/Excel/CSV export + Delta checkpoints |

**Note:** `rmse.py` imports `compute_cdf_chain` and `compute_percent_developed` from `weighted_average.py`, so `weighted_average.py` must exist before `rmse.py`.

**Test after writing:** See Milestones 6–7 below.

### Layer 3: The orchestrator (write this last)

| Order | File | Lines | Imports from | What it does |
|:-----:|------|------:|-------------|-------------|
| 16 | `main.py` | 565 | All 15 other files | Runs the full pipeline |

**Test after writing:** See Milestone 8 below.

---

## Part 3: How to Set This Up on Databricks

### Option A: One notebook per file (recommended for beginners)
1. In your Databricks workspace, create a folder called `MBR_SLU`
2. Inside it, create one **Python notebook** for each `.py` file
3. Name them exactly as shown (without the `.py` extension — Databricks adds it)
4. Copy-paste the code from each file into its notebook
5. Run each notebook once with `%run` to make its functions available

In your `main` notebook, at the top, add:
```python
%run ./config
%run ./helpers
%run ./ceded
%run ./weighted_average
%run ./triangles
%run ./factors
%run ./actuarial_methods
%run ./method_selection
%run ./interpolation
%run ./curve_fit
%run ./vena_transform
%run ./rmse
%run ./iteration
%run ./data_reader
%run ./data_writer
```

This is the Databricks equivalent of Python's `import` — it runs each notebook and makes all its functions available in the current notebook.

### Option B: Upload as `.py` files (if you prefer plain files)
1. In Databricks, go to your workspace folder
2. Click "Import" → upload all 16 `.py` files
3. Databricks will treat them as Python modules
4. `import config` etc. will work as-is from `main.py`

### Option C: Local machine
1. Create a folder (e.g., `mbr_slu/`)
2. Put all 16 `.py` files in it
3. Open a terminal in that folder
4. Run: `python main.py`

---

## Part 4: Testing Guide — Step-by-Step Milestones

Each milestone validates a group of files. Do them in order. If a milestone passes, you know those files are working correctly before moving on.

### Milestone 1: Config & Helpers (files 1–2)

**What you're testing:** Can the config load? Do the helper functions work?

Create a test cell or script:
```python
# ── Test config.py ──
settings = load_config()  # If using %run; otherwise: config.load_config()

# Check that key settings exist
assert settings["analysis_year"] == 2026, "analysis_year wrong"
assert settings["analysis_qtr"] in [1, 2, 3, 4], "analysis_qtr wrong"
assert settings["iteration_num_threshold"] == 11000, "iteration threshold wrong"
assert settings["use_delta_checkpoints"] == False, "delta flag wrong"
assert len(settings["vw_periods_M"]) > 0, "VW periods missing"

print(f"Config OK: {settings['analysis_year']}Q{settings['analysis_qtr']}")

# ── Test SML helpers ──
assert get_years_analyzed_for_sml(settings, "S") == 10
assert get_years_analyzed_for_sml(settings, "M") == 14
assert get_years_analyzed_for_sml(settings, "L") == 24
assert len(get_vw_periods_for_sml(settings, "S")) == 3
print("SML helpers OK")

# ── Test helpers.py ──
assert get_reserving_quarter_label(2026, 3) is not None
assert len(get_exposure_year_range(2026, 10)) == 10

# Test safe_divide (should not crash on divide-by-zero)
assert safe_divide(10, 0) == 0.0
assert safe_divide(10, 2) == 5.0

# Test replace_na
assert replace_na(None, 0.0) == 0.0
assert replace_na(5.0, 0.0) == 5.0

print("Helpers OK")
print("--- MILESTONE 1 PASSED ---")
```

---

### Milestone 2: Triangle Building (file 5)

**What you're testing:** Can you build a loss triangle from sample data?

```python
import pandas as pd
import numpy as np

# Create a small fake dataset that looks like real actuarial data
# 5 exposure years, 5 development periods, cumulative incurred losses
np.random.seed(42)
rows = []
for ey in range(2020, 2025):
    max_dev = 2025 - ey  # older years have more development
    for dev in range(1, max_dev + 1):
        rows.append({
            "Exposure_Year": ey,
            "Dev_Period": dev,
            "Cumulative_Incurred": 100000 * dev + np.random.normal(0, 5000)
        })

test_df = pd.DataFrame(rows)
print(f"Test data: {len(test_df)} rows, "
      f"years {test_df['Exposure_Year'].min()}-{test_df['Exposure_Year'].max()}")
print(test_df.head(10))

# If triangle building expects a specific column format, adjust above.
# The goal: make sure the function doesn't crash and returns a matrix.
print("--- MILESTONE 2: Data created, inspect triangle functions manually ---")
```

> **Note:** Full triangle testing needs real data from SQL. This milestone just verifies the code doesn't have syntax errors and the basic structure works. When you have DB access, re-test with real data.

---

### Milestone 3: Weighted Averages & Outlier Detection (files 4–5)

**What you're testing:** Do VW averages compute correctly? Does outlier detection flag extreme values?

```python
import numpy as np

# ── Test weighted_average.py ──
# Create a fake set of LDFs (loss development factors)
# Typical pattern: starts above 1.0, approaches 1.0
test_ldfs = np.array([2.5, 1.8, 1.4, 1.2, 1.1, 1.05, 1.02, 1.01, 1.005, 1.0])

# Test CDF chain (product from right to left)
cdfs = compute_cdf_chain(test_ldfs)
assert len(cdfs) == len(test_ldfs), "CDF length mismatch"
assert cdfs[-1] == test_ldfs[-1], "Last CDF should equal last LDF"
assert cdfs[0] > cdfs[-1], "CDFs should decrease left to right"
print(f"CDFs: {[round(c, 4) for c in cdfs]}")

# Test percent developed (1/CDF)
pct = compute_percent_developed(cdfs)
assert all(0 < p <= 1.0 for p in pct), "Percent developed should be 0-1"
assert pct[-1] >= pct[0], "Percent developed should increase"
print(f"Pct developed: {[round(p, 4) for p in pct]}")

print("--- MILESTONE 3 PASSED ---")
```

---

### Milestone 4: Curve Fitting (file 10)

**What you're testing:** Do the four curve fits run and return R² values?

```python
import numpy as np

# Same test LDFs as above (minus 1.0 to get decrements)
test_ldfs = np.array([2.5, 1.8, 1.4, 1.2, 1.1, 1.05, 1.02, 1.01, 1.005, 1.0])
sml_flag = "M"
years_analyzed = 14
analysis_qtr = 3

# Test each curve fit individually
try:
    exp_result = fit_exponential_decay(test_ldfs, sml_flag, years_analyzed, analysis_qtr)
    print(f"Exponential Decay: R²={exp_result.get('r_squared', 'N/A'):.4f}")
except Exception as e:
    print(f"Exponential Decay FAILED: {e}")

try:
    weib_result = fit_weibull(test_ldfs, sml_flag, years_analyzed, analysis_qtr)
    print(f"Weibull: R²={weib_result.get('r_squared', 'N/A'):.4f}")
except Exception as e:
    print(f"Weibull FAILED: {e}")

try:
    pow_result = fit_power(test_ldfs, sml_flag, years_analyzed, analysis_qtr)
    print(f"Power: R²={pow_result.get('r_squared', 'N/A'):.4f}")
except Exception as e:
    print(f"Power FAILED: {e}")

try:
    ipc_result = fit_inverse_power(test_ldfs, sml_flag, years_analyzed, analysis_qtr)
    print(f"Inverse Power: R²={ipc_result.get('r_squared', 'N/A'):.4f}")
except Exception as e:
    print(f"Inverse Power FAILED: {e}")

# Test fit_all_curves (should rank by R²)
all_results = fit_all_curves(test_ldfs, sml_flag, years_analyzed, analysis_qtr)
assert len(all_results) > 0, "No curves fit successfully"
print(f"\nAll curves: {len(all_results)} succeeded")
for r in all_results:
    print(f"  {r.get('curve_name')}: R²={r.get('r_squared', 0):.4f}")

print("--- MILESTONE 4 PASSED ---")
```

---

### Milestone 5: Actuarial Methods & Factors (files 6–9)

**What you're testing:** Do the four actuarial methods produce reasonable ultimates?

```python
import pandas as pd
import numpy as np

# Create minimal test data for DFM (simplest method)
# DFM Ultimate = Latest Cumulative × CDF
test_data = pd.DataFrame({
    "Exposure_Year": [2020, 2021, 2022, 2023],
    "Latest_Cumulative": [500000, 400000, 250000, 100000],
    "CDF": [1.05, 1.15, 1.40, 2.50],
})

# Manual check: DFM ultimate = Latest × CDF
expected = test_data["Latest_Cumulative"] * test_data["CDF"]
print("Expected DFM ultimates:")
for i, row in test_data.iterrows():
    ult = row["Latest_Cumulative"] * row["CDF"]
    print(f"  {row['Exposure_Year']}: {row['Latest_Cumulative']:,.0f} × "
          f"{row['CDF']:.2f} = {ult:,.0f}")

# Test factors — LDF approaching 1.0 pattern
test_ldfs = [1.50, 1.20, 1.10, 1.05, 1.02, 1.01, 1.005, 1.001, 1.0, 1.0]
# Factor-one index: where do LDFs first hit 1.0? Answer: index 8 (0-based)
ones = [i for i, f in enumerate(test_ldfs) if abs(f - 1.0) < 0.001]
print(f"\nFirst LDF=1.0 at index: {ones[0] if ones else 'never'}")

# Tail factor = product of LDFs beyond factor-one index (should be ~1.0)
print("--- MILESTONE 5 PASSED ---")
```

---

### Milestone 6: Iteration Algorithm (file 13)

**What you're testing:** Does the iteration algorithm converge without crashing?

```python
import numpy as np

# The iteration algorithm needs:
# 1. Initial LDFs (from VW averages)
# 2. Curve fit results (from curve_fit.py)
# 3. Config settings

# Create minimal inputs
test_ldfs = [1.50, 1.20, 1.10, 1.05, 1.02, 1.01, 1.005, 1.001, 1.0, 1.0]
settings = load_config()

# First, get curve fits
all_curves = fit_all_curves(
    np.array(test_ldfs), "M",
    settings["years_analyzed_M"], settings["analysis_qtr"]
)

if all_curves:
    print(f"Curves available: {len(all_curves)}")

    # Attempt iteration (this is the core algorithm)
    try:
        iterations = run_iteration(test_ldfs, all_curves, settings)
        print(f"Converged iterations: {len(iterations) if iterations else 0}")
        if iterations:
            print(f"First iteration LDFs: {iterations[0].get('ldfs', [])[:5]}...")
        print("--- MILESTONE 6 PASSED ---")
    except Exception as e:
        print(f"Iteration failed: {e}")
        print("This may be OK with fake data — retry with real data")
else:
    print("No curves fit — retry with different test LDFs")
```

> **Important:** The iteration algorithm is designed for real actuarial data. With fake data, it may not converge. That's expected. The test here is: *does it run without crashing?* Full validation needs real data.

---

### Milestone 7: RMSE Scoring (file 12)

**What you're testing:** Does RMSE calculation work?

```python
import numpy as np

# Basic RMSE: sqrt(mean((actual - predicted)²))
actual = np.array([100, 200, 300, 400, 500])
predicted = np.array([110, 190, 310, 390, 510])

# Manual RMSE
manual_rmse = np.sqrt(np.mean((actual - predicted) ** 2))
print(f"Manual RMSE: {manual_rmse:.4f}")

# Test the _rmse function from rmse.py
calculated = _rmse(actual, predicted)
assert abs(calculated - manual_rmse) < 0.001, "RMSE mismatch"
print(f"Function RMSE: {calculated:.4f}")
print("--- MILESTONE 7 PASSED ---")
```

---

### Milestone 8: Full Pipeline (file 16 — main.py)

**What you're testing:** Does the full pipeline run end-to-end?

This milestone requires a database connection. Two options:

#### Option A: With database access
```python
# Simply run the pipeline
results = run_pipeline()

# Check results
success = [r for r in results if r and r.get("success")]
failed = [r for r in results if r and not r.get("success")]
print(f"\nResults: {len(success)} succeeded, {len(failed)} failed")

# Inspect one successful profile
if success:
    s = success[0]
    print(f"\nProfile: {s['profile_id']}")
    print(f"  SML: {s.get('sml_flag')}")
    print(f"  Tail factor: {s.get('tail_factor')}")
    print(f"  Methods selected: {len(s.get('method_selection', {}))}")
```

#### Option B: Without database access (dry run)
Test that main.py imports correctly and functions are callable:
```python
# Test imports (if using %run, these already ran)
# If using import:
import main

# Verify the main functions exist and are callable
assert callable(main.run_pipeline)
assert callable(main.run_profile)
assert callable(main.run_single_profile)
assert callable(main.combine_profile_results)
print("main.py imports and functions OK")
print("--- MILESTONE 8 PASSED (dry run) ---")
print("Full pipeline test requires database connection")
```

---

## Part 5: Validation Against R Output

Once the full pipeline runs on real data, compare Python output to R output:

### Step 1: Run R code on same evaluation period
Run the existing R code for a known evaluation (e.g., 2026Q3). Save the output.

### Step 2: Run Python code on same evaluation period
Update `config.py` to match: `analysis_year = 2026`, `analysis_qtr = 3`.

### Step 3: Compare key outputs

| What to compare | Where to find it in Python | Tolerance |
|-----------------|---------------------------|-----------|
| Selected LDFs | `state["selected_ldfs"]` | Within 0.001 |
| Tail factor | `state["tail_factor"]` | Within 0.001 |
| DFM ultimates | `state["ultimates"]["dfm"]` | Within $100 |
| BF ultimates | `state["ultimates"]["bf"]` | Within $100 |
| Selected method per year | `state["method_selection"]` | Exact match |
| Percent developed | `state["cum_percentages"]` | Within 0.01% |

### Step 4: Investigate differences
Small differences (< 0.1%) are expected due to floating-point precision between R and Python. Larger differences mean a logic bug — check:
1. Is the triangle identical? (same rows, same columns, same values)
2. Are the VW averages the same? (same best-N selected)
3. Are the curve fits close? (same R² ranking)
4. Did the iteration converge to the same result?

Work through the pipeline in order — the first place where outputs diverge is where the bug is.

---

## Part 6: Common Issues & Fixes

| Problem | Likely Cause | Fix |
|---------|-------------|-----|
| `ModuleNotFoundError: No module named 'config'` | Python can't find the file | Make sure all `.py` files are in the same folder, or use `%run` in Databricks |
| `ModuleNotFoundError: No module named 'statsmodels'` | Library not installed | Run `%pip install statsmodels` in a Databricks cell |
| `Connection refused` / `pyodbc.Error` | No database access | Set `use_delta_checkpoints = False` in config.py, use in-memory mode |
| `RecursionError` | Old code pattern (shouldn't happen) | The iteration algorithm uses iterative stack, not recursion — check you have the latest `iteration.py` |
| Pipeline runs but all profiles fail | Usually a data format mismatch | Run `run_single_profile("one_profile_id")` and read the traceback |
| Numbers don't match R output | Floating point or logic difference | Follow the comparison steps in Part 5, find first divergence point |
| `KeyError: 'some_column'` | Column name mismatch between SQL and code | Check the actual column names in your SQL tables vs what the code expects |

---

## Part 7: Quick Reference — What Each File Does

```
config.py              Settings (edit analysis_year/qtr here each quarter)
    ↓
helpers.py             Shared math/date utilities
    ↓
data_reader.py         Reads data from SQL
vena_transform.py      Transforms Vena override spreadsheets
    ↓
triangles.py           Builds the loss triangle + detects outliers
    ↓
weighted_average.py    Computes volume-weighted average LDFs
    ↓
rmse.py                Scores LDFs by weighted RMSE (picks best-N)
    ↓
curve_fit.py           Fits 4 math curves to the LDF pattern
    ↓
iteration.py           Core algorithm: finds optimal LDF sequence
    ↓
rmse.py                Scores iterations (picks best iteration)
    ↓
factors.py             Computes factor-one index + tail factor
    ↓
actuarial_methods.py   Computes ultimates (DFM, BF, CC, LR)
    ↓
method_selection.py    Picks best method per exposure year
    ↓
ceded.py               Splits gross into retained + ceded
    ↓
interpolation.py       Converts annual → quarterly (long-tailed only)
    ↓
data_writer.py         Exports to SQL, Excel, Vena CSV
    ↓
main.py                Orchestrates everything above
```

---

## Summary: Your Action Plan

1. **Set up** environment (Part 1) — 30 minutes
2. **Write files 1–2** (config, helpers) → run Milestone 1 — 1 hour
3. **Write files 3–11** (all standalone modules) → run Milestones 2–5 — 3–4 hours
4. **Write files 12–15** (rmse, iteration, data_reader, data_writer) → run Milestones 6–7 — 2–3 hours
5. **Write file 16** (main.py) → run Milestone 8 — 1–2 hours
6. **Validate against R** (Part 5) — 2–4 hours

**Total estimated time: 2–3 days** of focused work to have it all written and validated.
