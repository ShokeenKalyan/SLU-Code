# Python Project Design — MBR/SLU on Azure Databricks

This document is written assuming you are new to Python and Databricks. It explains everything from the ground up.

It covers four things:
1. **Background Concepts** — how R and Python organize code differently (and what Databricks is)
2. **The Simple Project Structure** — a flat, easy-to-follow file layout to start with
3. **Key Design Decisions** — what changes from R and why
4. **Task Breakdown & Timeline** — what to build, in what order, and how long it takes

---

## Part 1: Background Concepts

### How R organizes code (what you already know)

In R, the current MBR project looks like this:

```
SLU/
├── SLU_main_code.R              ← The big main file that runs everything
├── MBR_weighted_average.R       ← Helper file with functions
├── MBR_curve_fit.R              ← Helper file with functions
├── MBR_iteration_algorithm.R    ← Helper file with functions
├── ... (10 more helper .R files)
```

How it works:
- `SLU_main_code.R` is the file you run
- Inside it, `source("MBR_weighted_average.R")` loads that file
- After `source()`, all the functions defined in that file become available
- It is as if you copy-pasted that file's code into the main file at that point
- All files share the same "workspace" — any variable or function is visible everywhere

This is simple but has a downside: everything is dumped into one big shared space. If file A creates a variable called `result` and file B also creates one called `result`, they overwrite each other silently.

### How Python organizes code (the new world)

Python does something very similar, but with one important difference: **each file is its own isolated space**.

In Python:
- Each `.py` file is called a **"module"**
- You use `import` instead of `source()` to bring in code from another file
- When you import, you get access to that file's functions, but they stay "inside" that file's name

Here is a concrete side-by-side comparison:

```
R way:                                  Python way:
─────────                               ───────────
source("MBR_curve_fit.R")              import curve_fit
result <- exponentialfunc(data)         result = curve_fit.exponentialfunc(data)
```

Notice the difference: in Python, you write `curve_fit.exponentialfunc()` — the function name is prefixed with the file it came from. This is a good thing: you always know which file a function lives in.

You can also import specific functions directly if you prefer the shorter syntax:

```python
from curve_fit import exponentialfunc

result = exponentialfunc(data)     # now you can use it without the prefix
```

**That is the core idea. Everything else is details.**

### What is `__init__.py`? (and why you can ignore it for now)

When you see `__init__.py` in Python projects, it is a special file that tells Python "this folder is a package" (a group of related modules). It is usually an empty file.

**You do not need this for the simple structure we will use.** It only matters when you organize files into sub-folders. We will keep everything flat (all files in one folder) to start, just like the R project. We can reorganize into sub-folders later when you are comfortable.

### What is Databricks? (the 60-second version)

Think of Databricks as a website where you can:
1. **Write code** in files (like a code editor in your browser)
2. **Run code** on powerful cloud computers (called "clusters")
3. **Connect to databases** to read and write data
4. **Schedule jobs** to run automatically (like a cron job)

When you log into Databricks, you see a **Workspace** — it is like a file explorer with folders and files. You can create folders, create files, and organize things however you want.

There are two types of files you will work with:

| Type | What it is | How you use it |
|---|---|---|
| **Notebook** (`.py`) | A file where you write and run code interactively, cell by cell | Your `main.py` will be a notebook — you click "Run All" to execute |
| **Python file** (`.py`) | A regular code file with functions | Your helper files (curve_fit.py, etc.) — imported by the notebook |

Both are `.py` files, but notebooks have a special format that lets you run code in chunks (called "cells"). Think of a notebook as a scratchpad where you can run things step by step and see results immediately. Regular `.py` files are just containers for functions.

### What will this look like in Databricks?

When you open Databricks and go to your Workspace, you will see something like this:

```
Workspace (the left sidebar in Databricks)
│
├── Users/
│   └── your.name@company.com/
│       └── mbr_slu/                    ← Your project folder
│           ├── main.py                  ← Notebook (click "Run All" to execute)
│           ├── config.py                ← Regular Python file
│           ├── data_reader.py           ← Regular Python file
│           ├── data_writer.py           ← Regular Python file
│           ├── vena_transform.py        ← Regular Python file
│           ├── triangles.py             ← Regular Python file
│           ├── weighted_average.py      ← Regular Python file
│           ├── curve_fit.py             ← Regular Python file
│           ├── iteration.py             ← Regular Python file
│           ├── rmse.py                  ← Regular Python file
│           ├── actuarial_methods.py     ← Regular Python file
│           ├── method_selection.py      ← Regular Python file
│           ├── factors.py               ← Regular Python file
│           ├── ceded.py                 ← Regular Python file
│           ├── interpolation.py         ← Regular Python file
│           └── helpers.py               ← Regular Python file
```

It looks just like a folder on your computer. You click on any file to open and edit it. You click on `main.py` to run the whole pipeline.

---

## Part 2: The Simple Project Structure

### The layout (flat and simple — just like R)

```
mbr_slu/
│
├── main.py                    ← THE file you run. Orchestrates everything.
│
├── config.py                  ← Settings: dates, thresholds, database connection info
├── data_reader.py             ← Reads data from SQL database
├── data_writer.py             ← Writes results to SQL database and Excel
├── vena_transform.py          ← Transforms Vena Excel exports into usable format
│
├── triangles.py               ← Builds loss triangles + outlier detection
├── weighted_average.py        ← Volume-weighted average LDFs
├── curve_fit.py               ← Fits 4 mathematical curves to LDF patterns
├── iteration.py               ← The core iteration algorithm (tree-search)
├── rmse.py                    ← Weighted RMSE scoring (used by several steps)
│
├── actuarial_methods.py       ← DFM, BF, Cape Cod, Loss Ratio calculations
├── method_selection.py        ← Picks best actuarial method per exposure year
├── factors.py                 ← Factor-one index, factor-less-than-one, tail factors
├── ceded.py                   ← Ceded/reinsurance calculations
├── interpolation.py           ← Annual-to-quarterly conversion (spline)
│
└── helpers.py                 ← Small shared utilities (date math, formatting)
```

**That is it. 16 files. All in one folder. No sub-folders. No `__init__.py`.**

This is intentionally simple. It mirrors the R structure:
- R has 1 main file + 13 helper files → Python has 1 main file + 15 helper files
- R uses `source()` → Python uses `import`
- Both are flat (all files in the same folder)

The only difference from R is that the 3,924-line main R file is split into a few smaller files (config, data_reader, data_writer, main) instead of one giant file. This makes each file easier to read and debug.

### How each R file maps to a Python file

| R File | Python File | What it does |
|---|---|---|
| `SLU_main_code.R` (orchestration) | `main.py` | Runs the full pipeline |
| `SLU_main_code.R` (config/setup) | `config.py` | Stores settings and parameters |
| `SLU_main_code.R` (SQL reads) | `data_reader.py` | Loads data from database |
| `SLU_main_code.R` (SQL writes + Excel) | `data_writer.py` | Saves results |
| `MBR_vena_data_transformation_adhoc.R` | `vena_transform.py` | Vena ETL |
| `MBR_weighted_average.R` | `triangles.py` (outlier part) + `weighted_average.py` | Outliers + VW averages |
| `MBR_curve_fit.R` | `curve_fit.py` | 4 curve fits |
| `MBR_iteration_algorithm_0.99_modified.R` | `iteration.py` | Tree-search iteration |
| `MBR_iteration_weighted_rmse_sml.R` | `rmse.py` | RMSE scoring |
| `MBR_threshold_ultimate_weighted_RMSE.R` | `rmse.py` (included here) | Tail threshold RMSE |
| `MBR_factor_one_index.R` | `factors.py` | Factor-one index |
| `MBR_factor_less_than_one_index.R` | `factors.py` (included here) | Sub-1.0 factor detection |
| `MBR_tail_factor_methods.R` | `factors.py` (included here) | Tail factor computation |
| `MBR_actuarial_method_ultimates.R` | `actuarial_methods.py` | DFM, BF, CC, LR |
| `MBR_method_selection_by_exposure_year_cc_change.R` | `method_selection.py` | Method selection |
| `MBR_ceded_all_calculations.R` | `ceded.py` | Ceded/reinsurance |
| `MBR_interpolation.R` | `interpolation.py` | Spline interpolation |

Notice that three small R files (`factor_one_index`, `factor_less_than_one_index`, `tail_factor_methods`) are combined into one Python file (`factors.py`). They are each 50-65 lines in R — too small to be their own file. Similarly, the threshold RMSE script is merged into `rmse.py`. This keeps the number of files manageable.

### What the main.py file looks like (the big picture)

Here is a simplified sketch of `main.py`. This is the Python equivalent of `SLU_main_code.R`:

```python
# main.py — The MBR/SLU Pipeline
# This is the file you run. It calls all the other files in order.

# ── Step 0: Import all the helper files ─────────────────────
# This is the Python equivalent of R's source() calls.
# It makes all functions from those files available here.

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


# ── Step 1: Load configuration ──────────────────────────────

settings = config.load_config()
# settings now contains: evaluation_date, sml_thresholds,
# database connection info, etc.


# ── Step 2: Load data ───────────────────────────────────────

raw_data = data_reader.load_all_data(settings)
vena_overrides = vena_transform.process_vena_data(settings)


# ── Step 3: Get list of profiles to run ─────────────────────

profile_list = data_reader.get_profile_list(settings)


# ── Step 4: Process each profile ────────────────────────────

all_results = []

for profile_id in profile_list:

    # This dictionary carries all data for one profile
    # through the pipeline. Think of it as a bag that each
    # step puts its results into.
    state = {}

    # 4a. Get this profile's data
    state["profile_data"] = data_reader.get_profile_data(profile_id, raw_data)
    state["overrides"] = vena_transform.get_profile_overrides(profile_id, vena_overrides)

    # 4b. Build loss triangle
    state["triangle"] = triangles.build(state["profile_data"], settings)

    # 4c. Detect outliers
    state["outliers"] = triangles.detect_outliers(state["triangle"])

    # 4d. Compute volume-weighted averages
    state["vw_avg"] = weighted_average.compute(state["triangle"], state["outliers"])

    # 4e. Score and pick best-N
    state["best_n"] = rmse.select_best_n(state["vw_avg"], state["triangle"])

    # 4f. Fit curves
    state["curves"] = curve_fit.fit_all(state["best_n"])

    # 4g. Run iteration algorithm
    state["iterations"] = iteration.run(state["best_n"], state["curves"])
    state["selected_ldfs"] = rmse.select_best_iteration(state["iterations"])

    # 4h. Compute factor indexes and tail
    state["factor_one_idx"] = factors.get_factor_one_index(state["selected_ldfs"])
    state["factor_lt_one"] = factors.get_factor_less_than_one(state["selected_ldfs"])
    state["tail"] = factors.compute_tail(state["selected_ldfs"], state["curves"])

    # 4i. Compute actuarial method ultimates
    state["ultimates"] = actuarial_methods.compute_all(state, settings)

    # 4j. Select best method per exposure year
    state["selected"] = method_selection.select(state, settings)

    # 4k. Ceded/reinsurance
    state["ceded"] = ceded.compute(state, settings)

    # 4l. Interpolation (long-tailed only)
    if settings["sml_flag"] == "L":
        state["quarterly"] = interpolation.annual_to_quarterly(state["selected_ldfs"])

    all_results.append(state)


# ── Step 5: Export results ──────────────────────────────────

data_writer.write_to_sql(all_results, settings)
data_writer.write_to_excel(all_results, settings)
data_writer.write_to_vena(all_results, settings)
```

**Compare this to how R does it:**

| Step | R (SLU_main_code.R) | Python (main.py) |
|---|---|---|
| Load helpers | `source("MBR_curve_fit.R")` | `import curve_fit` |
| Call a function | `exponentialfunc(data)` | `curve_fit.exponentialfunc(data)` |
| Share data between steps | Global variables via `<<-` | The `state` dictionary |
| Loop over profiles | `parLapply(cl, profiles, run_mbr)` | `for profile_id in profile_list:` |

### What a helper file looks like

Here is what `factors.py` looks like — it is just a file with functions in it:

```python
# factors.py — Factor indexes and tail factor computation
#
# This file contains three groups of functions, merged from
# three small R files:
#   - MBR_factor_one_index.R        → get_factor_one_index()
#   - MBR_factor_less_than_one.R    → get_factor_less_than_one()
#   - MBR_tail_factor_methods.R     → compute_tail()


def get_factor_one_index(selected_ldfs, threshold):
    """
    Find the first development period where LDFs stabilize at 1.0.
    Scans from right to left.

    This is the Python version of fn_get_end_triangle_index() from R.
    """
    # ... actual logic here ...
    return factor_one_index


def get_factor_less_than_one(selected_ldfs):
    """
    Detect development periods where LDFs drop below 1.0.

    This is the Python version of fn_get_less_than_one_factors_index() from R.
    """
    # ... actual logic here ...
    return less_than_one_info


def compute_tail(selected_ldfs, curves, factor_one_idx):
    """
    Compute the tail factor by extrapolating the curve fit.

    This is the Python version of fn_tail_factor_experience_method() from R.
    """
    # ... actual logic here ...
    return tail_factor
```

**Key point:** Each function has a short description (the text in triple quotes, called a "docstring") saying what it does and which R function it replaces. This makes it easy to cross-reference with the R code.

---

## Part 3: Key Design Decisions

### The `state` dictionary (replacing R's global variables)

This is the single biggest change from R to Python.

**The R way:** R uses `<<-` to write to global variables. When `MBR_curve_fit.R` runs, it stores its results in global variables like `curve_fit_results`, `r_squared_values`, etc. Then `MBR_iteration_algorithm.R` reads those same globals. There are roughly 50-80 globals shared this way. The problem: you cannot tell from looking at a function what data it needs or what data it produces.

**The Python way:** Each profile gets a dictionary called `state`. Each pipeline step reads what it needs from `state` and adds its results into `state`.

A dictionary is just a named container. Think of it like a labeled filing cabinet:

```python
state = {}                              # Start with an empty cabinet
state["triangle"] = ...                 # Put the triangle in the "triangle" drawer
state["outliers"] = ...                 # Put outliers in the "outliers" drawer
state["curves"] = ...                   # Put curve fits in the "curves" drawer

# Later, any step can read from any drawer:
my_triangle = state["triangle"]         # Pull out the triangle
```

**Why this is better:** If a function stops working, you can print `state` and see exactly what data was available at that point. In R, you would need to hunt through dozens of global variables.

### The iteration algorithm (the one tricky conversion)

The R iteration algorithm calls itself recursively (a function that calls itself). This can go thousands of levels deep. Python has a safety limit of 1,000 levels by default.

**Solution:** Convert the recursive approach to a loop with an explicit stack. The logic stays the same — it is a mechanical transformation, not a redesign. We will handle this carefully during Phase 2.

### How database access works on Databricks

On Databricks, you have built-in tools to talk to databases. You do not need to install database drivers manually like in R.

```
R way:                                     Databricks way:
─────                                      ──────────────
1. Install ODBC driver on your machine     1. Already configured by your admin
2. conn <- odbcDriverConnect(...)          2. Use spark.read to query
3. data <- sqlQuery(conn, "SELECT ...")    3. data = spark.read.format("jdbc")...
4. sqlSave(conn, results, "table_name")   4. results.write.format("jdbc")...
```

The details of connecting to your specific database will depend on how your Databricks workspace is configured. Your admin or Databricks team will have set up the connection (called a "JDBC connection" or "SQL Warehouse connection"). You just need the connection details (server name, database name, credentials).

### Simple loop now, parallel later

In R, the code uses `parLapply` to process 400 profiles across 10 CPU cores. We will NOT do this in Phase 1-4. Instead:

- **During development (Phases 1-4):** Use a simple `for` loop. Process one profile at a time. This makes it easy to debug — if something goes wrong, you know exactly which profile and which step caused it.
- **For production (Phase 5):** Switch to Spark's built-in parallelism to distribute profiles across the Databricks cluster. This is a small change to `main.py` once everything else works.

### Saving intermediate results: two modes

You will not always have access to create permanent tables in Databricks (it requires specific permissions that may take time to provision). So the project supports two modes:

**Mode 1: In-Memory (use this now)**

All data lives in Python variables, passed between steps within the same session. If the cluster detaches or your session expires, you re-run from the top.

```python
# Cell 1
df_triangles = data_reader.load_profile_data(profile_id, settings)

# Cell 2 (uses the variable from Cell 1 — only works in the same session)
df_outliers = triangles.detect_outliers(df_triangles)

# Cell 3
df_vw = weighted_average.compute(df_triangles, df_outliers)
```

This is perfectly fine for development. The MBR pipeline for a single profile runs in seconds to minutes, so re-running from the top is not a big deal. The `state` dictionary in `main.py` handles this — all intermediate results are stored in `state` and flow from step to step.

**Mode 2: Delta Table Checkpoints (switch to this when you have write access)**

After each major pipeline step, save the result as a permanent Delta table. If anything fails or the session dies, restart from the last saved checkpoint instead of from scratch.

```python
# Cell 1 — save after loading
df_triangles = data_reader.load_profile_data(profile_id, settings)
spark.createDataFrame(df_triangles).write.format("delta").mode("overwrite").saveAsTable("mbr_dev.triangles")

# Cell 2 — load from checkpoint (works even after cluster restart)
df_triangles = spark.table("mbr_dev.triangles").toPandas()
df_outliers = triangles.detect_outliers(df_triangles)
spark.createDataFrame(df_outliers).write.format("delta").mode("overwrite").saveAsTable("mbr_dev.outliers")
```

The switch from Mode 1 to Mode 2 is small. You add a save-line after each step and a load-line at the start. The core logic does not change at all.

**How this will work in `main.py`:**

```python
# A simple flag controls which mode you are in.
# Flip this to True once you have write access.
USE_DELTA_CHECKPOINTS = False

# After each step, optionally save:
state["triangle"] = triangles.build(state["profile_data"], settings)

if USE_DELTA_CHECKPOINTS:
    spark.createDataFrame(state["triangle"]).write.format("delta") \
        .mode("overwrite").saveAsTable(f"mbr_dev.triangle_{profile_id}")

# At the start of any step, optionally load from checkpoint:
if USE_DELTA_CHECKPOINTS and step_to_resume_from == "outliers":
    state["triangle"] = spark.table(f"mbr_dev.triangle_{profile_id}").toPandas()
```

**Where to find permanent Delta tables in Databricks:**

When you create a Delta table (e.g., `saveAsTable("mbr_dev.triangles")`), it appears in the **Data** tab in the Databricks left sidebar:

```
Databricks left sidebar:
│
├── Home
├── Workspace        ← where your .py code files live
├── Data             ← WHERE YOUR TABLES LIVE ← ← ←
│   └── Catalog
│       └── your_catalog (e.g., "hive_metastore" or your company's catalog)
│           └── your_schema (e.g., "mbr_dev")
│               ├── triangles          ← your saved table
│               ├── outliers           ← your saved table
│               ├── vw_averages        ← your saved table
│               └── ...
├── Compute          ← where your clusters are managed
├── Workflows        ← where scheduled jobs are set up
```

Click on **Data** in the left sidebar → expand the catalog → expand the schema → you will see all your tables listed. You can click on any table to preview its data, see its columns, check when it was last updated, etc.

The table name has two parts: `schema.table_name` (e.g., `mbr_dev.triangles`). The schema is like a folder that groups related tables together. You will want to create a schema like `mbr_dev` for development tables and later `mbr_prod` for production tables. Your admin will set up the catalog and schema — you just need the name to use in your code.

**Plan: start with Mode 1 now, switch to Mode 2 when access is provisioned.** The code structure supports both from day one.

### Future improvement: organized sub-folders

Once you are comfortable with the flat structure and the conversion is working, you can optionally reorganize into sub-folders for cleanliness:

```
mbr_slu/
├── main.py
├── config.py
├── helpers.py
│
├── data/                      ← Group: data in/out
│   ├── __init__.py            ← (empty file that says "this folder is a package")
│   ├── data_reader.py
│   ├── data_writer.py
│   └── vena_transform.py
│
├── core/                      ← Group: core algorithms
│   ├── __init__.py
│   ├── triangles.py
│   ├── weighted_average.py
│   ├── curve_fit.py
│   ├── iteration.py
│   └── rmse.py
│
├── methods/                   ← Group: actuarial methods
│   ├── __init__.py
│   ├── actuarial_methods.py
│   ├── method_selection.py
│   └── ceded.py
│
└── factors/                   ← Group: factors and post-processing
    ├── __init__.py
    ├── factors.py
    └── interpolation.py
```

The only difference is that imports change slightly:

```python
# Flat structure:
import curve_fit

# Sub-folder structure:
from core import curve_fit
```

**This reorganization is optional and can wait until Phase 5 or later.** The flat structure works perfectly fine. Sub-folders just make it tidier when you have many files.

---

## Part 4: Task Breakdown & Timeline

### Overview

Total estimated duration: **14–18 weeks** (one person, primary project).

5 phases. Each builds on the previous one. You validate each phase before moving on.

```
Week  1–3   ████████                Phase 1: Foundation & Data Layer
Week  4–8        ██████████████     Phase 2: Core Development Factors (hardest)
Week  9–12              ████████    Phase 3: Actuarial Methods & Factors
Week 13–15                  ██████  Phase 4: Integration & Validation
Week 16–18                    ████  Phase 5: Parallel & Production
```

---

### Phase 1: Foundation & Data Layer (Weeks 1–3)

**Goal:** Get data flowing in and out. No actuarial math yet — just plumbing.

| # | Task | What you build | Days | R Source |
|---|---|---|---|---|
| 1.1 | Project setup | Create `mbr_slu/` folder in Databricks with all empty `.py` files | 1 | — |
| 1.2 | Config | `config.py` — evaluation date, thresholds, DB connection | 1 | `SLU_main_code.R` (top section) |
| 1.3 | SQL reader | `data_reader.py` — read triangles, premiums, assumptions from database | 3 | `SLU_main_code.R` (SQL queries) |
| 1.4 | Vena ETL | `vena_transform.py` — transform Vena Excel exports | 3 | `MBR_vena_data_transformation_adhoc.R` |
| 1.5 | Triangle builder | `triangles.py` — build YQ and YY loss triangles from raw data | 3 | `SLU_main_code.R` (triangle section) |
| 1.6 | Output | `data_writer.py` — write to SQL/Delta tables and Excel | 2 | `SLU_main_code.R` (export section) |
| 1.7 | Validate | Run for 2-3 profiles, compare data against R | 2 | — |

**Done when:** You can read data for any profile, build its triangle, and confirm the numbers match R.

---

### Phase 2: Core Development Factors (Weeks 4–8)

**Goal:** The mathematical heart — go from raw triangle to selected LDFs. This is the hardest phase.

| # | Task | What you build | Days | R Source |
|---|---|---|---|---|
| 2.1 | Outlier detection | Add `detect_outliers()` to `triangles.py` — adjusted boxplot with medcouple | 2 | `MBR_weighted_average.R` (outlier part) |
| 2.2 | Weighted averages | `weighted_average.py` — VW LDFs for best-3, best-5, best-7, etc. | 3 | `MBR_weighted_average.R` |
| 2.3 | RMSE scoring | `rmse.py` — weighted RMSE for scoring VW averages and iterations | 3 | `MBR_iteration_weighted_rmse_sml.R` |
| 2.4 | Best-N selection | Add logic in `main.py` to pick the best-N using RMSE | 1 | `SLU_main_code.R` |
| 2.5 | Curve fit: Exp Decay | `curve_fit.py` — first curve (start with the simplest one) | 2 | `MBR_curve_fit.R` |
| 2.6 | Curve fit: Weibull | Add second curve to `curve_fit.py` | 2 | `MBR_curve_fit.R` |
| 2.7 | Curve fit: Power | Add third curve | 1 | `MBR_curve_fit.R` |
| 2.8 | Curve fit: Inverse Power | Add fourth curve (has extra parameter optimization) | 2 | `MBR_curve_fit.R` |
| 2.9 | Cook's distance | Add influential-point detection and re-fitting for all 4 curves | 2 | `MBR_curve_fit.R` |
| 2.10 | Iteration algorithm | `iteration.py` — the core tree-search (converted to loop-based) | 5 | `MBR_iteration_algorithm_0.99_modified.R` |
| 2.11 | Iteration scoring | Add iteration RMSE selection to `rmse.py` | 2 | `MBR_iteration_weighted_rmse_sml.R` |
| 2.12 | Validate | Compare selected LDFs against R for several profiles | 3 | — |

**Done when:** For any profile, you go from triangle → outliers → VW averages → curves → iteration → selected LDFs, and the numbers match R.

---

### Phase 3: Actuarial Methods & Factors (Weeks 9–12)

**Goal:** Compute ultimate loss estimates and select the best method.

| # | Task | What you build | Days | R Source |
|---|---|---|---|---|
| 3.1 | Factor indexes | `factors.py` — factor-one index + factor-less-than-one detection | 2 | `MBR_factor_one_index.R` + `MBR_factor_less_than_one_index.R` |
| 3.2 | Tail factors | Add tail factor computation to `factors.py` | 2 | `MBR_tail_factor_methods.R` |
| 3.3 | Tail threshold RMSE | Add tail truncation logic to `rmse.py` | 1 | `MBR_threshold_ultimate_weighted_RMSE.R` |
| 3.4 | DFM method | `actuarial_methods.py` — Development Factor Method | 2 | `MBR_actuarial_method_ultimates.R` |
| 3.5 | BF method | Add Bornhuetter-Ferguson to `actuarial_methods.py` | 2 | `MBR_actuarial_method_ultimates.R` |
| 3.6 | Cape Cod method | Add Cape Cod (includes CC change logic — most complex) | 3 | `MBR_actuarial_method_ultimates.R` |
| 3.7 | LR method | Add Loss Ratio to `actuarial_methods.py` | 1 | `MBR_actuarial_method_ultimates.R` |
| 3.8 | Method selection | `method_selection.py` — rules + RMSE hindsight simulation | 3 | `MBR_method_selection_by_exposure_year_cc_change.R` |
| 3.9 | Ceded | `ceded.py` — reinsurance recovery ratios and ceded ultimates | 2 | `MBR_ceded_all_calculations.R` |
| 3.10 | Interpolation | `interpolation.py` — annual-to-quarterly cubic spline | 2 | `MBR_interpolation.R` |
| 3.11 | Validate | Compare all outputs against R | 3 | — |

**Done when:** Full pipeline works for individual profiles. Ultimates, method selections, and ceded results match R.

---

### Phase 4: Integration & Validation (Weeks 13–15)

**Goal:** Run all profiles, compare everything against R, fix any differences.

| # | Task | What you build | Days |
|---|---|---|---|
| 4.1 | Full pipeline wiring | Wire all steps in `main.py` with the `state` dictionary flow | 3 |
| 4.2 | All-profile loop | Run all ~400 profiles in a simple `for` loop | 2 |
| 4.3 | Full export | Write to all output destinations (SQL, Excel, Vena CSV) | 2 |
| 4.4 | R vs Python comparison | Run both R and Python on same data, compare all ~30 output tables | 5 |
| 4.5 | Fix differences | Investigate and fix any numerical differences found | 3 |

**Done when:** Python pipeline produces results matching R across all profiles.

---

### Phase 5: Parallelization & Production (Weeks 16–18)

**Goal:** Make it production-ready and scheduled on Databricks.

| # | Task | What you build | Days |
|---|---|---|---|
| 5.1 | Spark parallel | Distribute profiles across the Databricks cluster (replaces the `for` loop) | 3 |
| 5.2 | Error handling | Add logging and per-profile error recovery (like R's `tryCatch`) | 2 |
| 5.3 | Databricks Workflow | Set up a scheduled job so the pipeline runs automatically each quarter | 2 |
| 5.4 | Performance test | Run full portfolio, measure timing, find and fix bottlenecks | 3 |
| 5.5 | Documentation | Document the code and write a runbook for operations | 2 |
| 5.6 | Handoff | Walk through code with team | 3 |

**Done when:** The system runs in production on Databricks, scheduled automatically, with logging and monitoring.

---

### Risk areas (where things might take longer than estimated)

| Risk | Why it is risky | What to do about it |
|---|---|---|
| Iteration algorithm (Task 2.10) | The recursion-to-loop conversion is the trickiest single piece. The R code is deeply recursive and uses global state heavily. | Give it the most time (5 days). Test against known R outputs constantly. |
| Numerical precision | R and Python handle decimal math slightly differently. Small differences (e.g., 0.0001%) can compound across the pipeline. | Use tolerance-based comparison, not exact equality. Document acceptable differences. |
| Curve fit convergence | Python's `scipy.curve_fit` may converge to slightly different values than R's `nls()`. | Test with the same starting values. May need to adjust optimization settings. |
| Vena ETL | Lots of edge cases in parsing Excel files. Column names change between Vena versions. | Get sample Vena files early. Build and test incrementally. |
| SML branching | Short/Medium/Long profiles take different code paths throughout. Easy to miss one. | Test with one profile from each SML category from day one. |

---

### How to track and report progress

Mark each task with a status as you go:

| Status | Meaning |
|---|---|
| `NOT STARTED` | Have not begun |
| `IN PROGRESS` | Actively working on it |
| `BLOCKED` | Waiting on something (note what) |
| `IN REVIEW` | Code written, comparing against R output |
| `DONE` | Matches R, tests pass |

For weekly updates to stakeholders, use a one-liner per phase:

> **Week 6 update:**
> - Phase 1: DONE
> - Phase 2: 8 of 12 tasks done. Curve fitting complete. Iteration algorithm in progress.
> - Phase 3-5: Not started.

---

## Quick Reference: R → Python Library Mapping

| What you need | R Package | Python Package | Available on Databricks? |
|---|---|---|---|
| Data tables | `data.table` / `dplyr` / `tidyr` | `pandas` | Yes (pre-installed) |
| Math operations | base R | `numpy` | Yes (pre-installed) |
| Curve fitting | `stats::nls()` | `scipy.optimize.curve_fit()` | Yes (pre-installed) |
| Outlier detection (medcouple) | `robustbase::mc()` | `statsmodels.stats.statlib.medcouple_1d()` | Needs `pip install statsmodels` |
| Skewness | `moments::skewness()` | `scipy.stats.skew()` | Yes (pre-installed) |
| Spline interpolation | `stats::splinefun()` | `scipy.interpolate.CubicSpline()` | Yes (pre-installed) |
| Loss triangles | `ChainLadder` | Build manually with `pandas` | — |
| Parallel processing | `parallel::parLapply()` | PySpark (built into Databricks) | Yes (built-in) |
| Excel files | `openxlsx` / `readxl` | `openpyxl` | Needs `pip install openpyxl` |
| String handling | `stringr` | Python built-in `str` methods | Yes (built-in) |
| Date handling | `lubridate` | Python `datetime` / `pandas` | Yes (built-in) |
| Database access | `RODBC` | Spark JDBC (built into Databricks) | Yes (built-in) |
