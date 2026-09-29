# Analysis: Factor Index & Iteration Algorithm Files

This document provides an exhaustive analysis of three closely related R files that handle
**Loss Development Factor (LDF) validation and selection** via index detection and a recursive
iteration/convergence algorithm.

---

## Table of Contents

1. [MBR_factor_one_index.R.txt — End-of-Triangle Detection](#1-mbr_factor_one_indextxt)
2. [MBR_factor_less_than_one_index.R.txt — Sub-1.0 Factor Analysis](#2-mbr_factor_less_than_one_indextxt)
3. [MBR_iteration_algorithm_0.99_modified.R.txt — Recursive Convergence Algorithm](#3-mbr_iteration_algorithm_099_modifiedtxt)
4. [How the Three Files Connect](#4-how-the-three-files-connect)

---

## 1. MBR_factor_one_index.R.txt

### Purpose

This file answers: **"At what development period does meaningful loss development effectively stop?"**

In insurance, claims develop (grow or shrink) over time. Early development periods see large changes;
later periods see tiny, negligible changes. This function finds the cutoff point — the development
period index after which remaining development is so small it can be ignored.

### Function: `fn_get_end_triangle_index`

#### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `profile_id_analyzed` | string | Identifier for the insurance profile (line of business + attributes) being analyzed |
| `sml_flag` | string | "S", "M", or "L" — Short, Medium, or Long-tailed business classification |
| `actuals_cl` | data.frame | Actual claims data (already filtered for the profile) with columns including `dev_len` and `Gross_Incurred` |
| `last_dev_period_index` | integer | The maximum development period index available in the triangle |

#### Return Value

A **list** with two elements:
- `dev_prop_inc_df` — A data.frame with the proportion-of-incurred calculation details (for auditing)
- `end_index` — The integer index where the triangle effectively ends

#### Step-by-Step Logic

```
Step 1: Take absolute values of Gross_Incurred
        (negative incurred = recoveries; we care about magnitude of development)
        
Step 2: Aggregate incurred by development length
        Group by dev_len, sum Gross_Incurred → one row per dev period
        
Step 3: Calculate total incurred across all development periods
        total_inc = sum of all Gross_Incurred
        
Step 4: Self-join the data on a dummy column ('fake_col')
        This creates every pair (dev_len.x, dev_len.y) where dev_len.x < dev_len.y
        Purpose: For each dev period, sum all incurred that comes AFTER it
        
Step 5: For each dev period, compute:
        Gross_Incurred_ahead = sum of incurred in all later dev periods
        Prop_Total_Inc = Gross_Incurred_ahead / total_inc
        
Step 6: Flag each dev period:
        dev_less_than_1 = 1 if Prop_Total_Inc * 100 <= factor_1_index_threshold
                          (i.e., remaining development is below threshold, e.g. 0.5%)
        dev_greater_than_1 = 1 if |Prop_Total_Inc| * 100 > 1
                              (i.e., there's still >1% of total incurred developing)
        
Step 7: Find end_index:
        - If any dev period has dev_less_than_1 == 1, take the FIRST such period
        - Otherwise, use last_dev_period_index (the full triangle)
        
Step 8: Floor the index at consecutive_less_than_one_num
        (ensures we have enough periods for downstream <1 factor analysis)
```

#### Mathematical Formula

For each development period `d`:

```
Prop_Total_Inc(d) = Σ |Incurred(d')| for all d' > d
                    ─────────────────────────────────
                          Σ |Incurred(d)| for all d
```

The threshold test is: `Prop_Total_Inc(d) × 100 ≤ factor_1_index_threshold`

#### Business Meaning

Imagine a claims profile where 99.5% of all claims development occurs within the first 60 months.
After 60 months, only 0.5% of total incurred remains to develop. This function identifies "60 months"
as the `end_index`. Everything beyond that point is noise — and the system will handle it differently
(via tail factors rather than explicit LDFs).

#### Global Variables Referenced

| Variable | Purpose |
|----------|---------|
| `factor_1_index_threshold` | The percentage threshold (e.g. 0.5) below which development is negligible |
| `consecutive_less_than_one_num` | Minimum number of periods needed for <1 factor analysis |
| `analysis_year` | Current valuation year |
| `analysis_qtr` | Current valuation quarter |
| `analysis_val_flag` | Valuation flag |

#### Connection to Other Files

- **Downstream:** The `end_index` it returns is used as `index_cons_1` in the less-than-one factor
  analysis and as the boundary for the iteration algorithm.
- **Upstream:** Called from the main code (`SLU_main_code.R`) during the LDF selection pipeline.

---

## 2. MBR_factor_less_than_one_index.R.txt

### Purpose

This file answers: **"Where do loss development factors drop below 1.0, and what does that pattern
look like?"**

An LDF below 1.0 means claims are *shrinking* (e.g., due to recoveries, subrogation, or favorable
development). These factors need special handling because standard actuarial methods assume LDFs ≥ 1.0.

The file contains **three functions** that detect and characterize sub-1.0 factor patterns.

---

### Function 1: `fn_get_less_than_one_factors_index`

#### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `profile_id_analyzed` | string | Profile identifier |
| `consecutive_less_than_one_num` | integer | How many consecutive <1 factors to look for (e.g., 5) |
| `x` | numeric vector | The LDF values (initial selections) |
| `index_cons_1` | integer | The end-of-triangle index (from `fn_get_end_triangle_index`) |

#### Return Value

An **integer**: the index where the first run of N consecutive sub-1.0 factors begins.
Returns `0` if no such run exists.

#### Step-by-Step Logic

```
Step 1: Iterate through positions 1 to (index_cons_1 - N + 1)
        where N = consecutive_less_than_one_num
        
Step 2: At each position i, check if ALL values from i to (i + N - 1) are < 1.0
        This is a sliding window of size N

Step 3: If a full run of N consecutive <1 factors is found:
        - Record the starting index
        - Stop searching (take the FIRST such run)
        
Step 4: If no run found after exhausting all positions:
        - Return 0
```

#### Example

```
x = [1.05, 1.03, 0.98, 0.97, 0.96, 0.95, 0.94, 1.01, ...]
consecutive_less_than_one_num = 5

Checking position 1: x[1]=1.05 → fails immediately
Checking position 2: x[2]=1.03 → fails immediately
Checking position 3: x[3]=0.98, x[4]=0.97, x[5]=0.96, x[6]=0.95, x[7]=0.94 → ALL < 1 ✓

Result: 3 (the run starts at index 3)
```

#### Business Meaning

Insurance lines often hit a point where development reverses direction — claims start to close,
subrogation recoveries come in, or case reserves are taken down. Five consecutive sub-1.0 factors
indicates a genuine pattern of favorable development, not just noise. The starting index of this
pattern marks where the system transitions from "development is ongoing" to "development is reversing."

---

### Function 2: `fn_get_prop_less_than_one_factors`

#### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `profile_id_analyzed` | string | Profile identifier |
| `x` | numeric vector | The LDF values |
| `index_cons_1` | integer | The end-of-triangle index |

#### Return Value

A **numeric** value between 0 and 1: the proportion of factors that are below 1.0 in the range
[1, index_cons_1 - 1].

#### Step-by-Step Logic

```
Step 1: Extract factors from position 1 to (index_cons_1 - 1)
Step 2: Count how many are < 1.0
Step 3: Divide count by total number of factors in range
```

#### Formula

```
prop_less_than_one = count(x[i] < 1 for i in 1..index_cons_1-1)
                     ──────────────────────────────────────────
                                  (index_cons_1 - 1)
```

#### Business Meaning

If most of the factors in the active part of the triangle are already below 1.0, this suggests the
line of business is in runoff or dominated by recoveries. This proportion influences downstream
decisions about how aggressively to smooth factors and which actuarial methods to prefer.

---

### Function 3: `fn_get_default_last_index_less_than_one_factors`

#### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `x` | numeric vector | The LDF values |
| `index_cons_1` | integer | The end-of-triangle index |

#### Return Value

A **list** with two elements:
- `default_last_index_less_than_one_factors` — Index where a significant drop in sub-1.0 factors occurs
- `incr_pct_change_grt_than_threshold` — Boolean: whether any such significant drop exists

#### Step-by-Step Logic

```
Step 1: Create a data frame from x
Step 2: Add lag_x = previous factor value (lag of x; first value defaults to 1)
Step 3: Compute incremental percentage change:
        incr_pct_change = x / lag_x - 1
        (If lag_x is 0, set to 0 to avoid division by zero)
        
Step 4: Flag "valid points" where:
        - x < 1 (current factor is below 1.0)  AND
        - lag_x < 1 (previous factor was also below 1.0)  AND
        - incr_pct_change <= -incr_pct_change_threshold
          (the drop from one factor to the next exceeds the threshold)

Step 5: Check if ANY valid point exists in positions 2 through (index_cons_1 - 1)

Step 6: The default_last_index is:
        - If any valid point exists: the FIRST such point
        - Otherwise: index_cons_1 (the full end-of-triangle index)
```

#### Formula

```
incr_pct_change(i) = x(i) / x(i-1) - 1

valid_point(i) = 1  if  x(i) < 1  AND  x(i-1) < 1  AND  incr_pct_change(i) ≤ -threshold
```

#### Business Meaning

This detects a **cliff** in the sub-1.0 factor pattern — a sudden, significant drop that suggests
the favorable development is accelerating or that data past this point is unreliable. The identified
index becomes a boundary: factors beyond this point may be replaced by curve fits or set to 1.0.

#### Global Variables Referenced

| Variable | Purpose |
|----------|---------|
| `incr_pct_change_threshold` | The percentage-change threshold for detecting significant drops |

---

## 3. MBR_iteration_algorithm_0.99_modified.R.txt

### Purpose

This is the **core convergence engine** of the MBR system. It answers: **"Can we construct a valid,
monotonically decreasing sequence of LDFs (all ≥ 0.99) by substituting curve-fit values where the
initial selections fail?"**

The algorithm uses **recursive backtracking with branching** — it's essentially a constraint
satisfaction solver for LDF sequences.

### Function 1: `best_rsq_replace`

#### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `iteration` | data.frame | An iteration result with columns `Iteration_Values`, `Convergence`, `Iteration_Values_Original` |
| `start_index` | integer | First index to replace |
| `end_index` | integer | Last index to replace |
| `data` | data.frame | Contains curve-fit values (columns: `Exponential_Decay`, `Inverse_Power`, `Power`, `Weibull`) |
| `r_sq_data` | data.frame | R-squared values for each distribution, sorted descending by R² |

#### Return Value

The **iteration** data.frame, with `Iteration_Values` potentially replaced from `start_index`
to `end_index` using the best available curve fit.

#### Step-by-Step Logic

```
Step 1: Only operate if the iteration has Convergence == 1 (it converged)

Step 2: For each of the 4 curve distributions (ranked by R²):
        Check if curve_value[start_index] < iteration_value[start_index - 1]
        (i.e., the curve at the replacement start is less than the preceding iteration value,
         maintaining monotonic decrease)
        Mark as "replaceable" if yes

Step 3: If NO curve is replaceable:
        Force-replace using the highest-R² curve anyway (with a warning)

Step 4: Replace iteration values from start_index to end_index using the
        first replaceable curve (highest R² among replaceable ones)
        Save original values in Iteration_Values_Original
```

#### Business Meaning

After the iteration algorithm converges, the tail portion of the factor sequence may still need
smoothing. This function replaces the tail with the best-fitting mathematical curve, preserving
the constraint that the sequence must decrease monotonically.

---

### Function 2: `validate_iteration` (The Core Algorithm)

#### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `x` | numeric vector | Current LDF sequence being validated/modified |
| `l` | integer | Recursion level (starts at 0, increments with each recursive call) |
| `d` | string | Distribution name that generated this branch (e.g., "ExponentialDecay") |
| `c` | integer | Global function call counter (used as iteration ID) |
| `t` | binary vector | Index replacement tracker (0 = not yet tried, 1 = already replaced at this index) |
| `first_index` | integer | Start of the validation range |
| `last_index` | integer | End of the validation range |
| `data` | data.frame | Curve-fit values for all 4 distributions |
| `profile_id_analyzed` | string | Profile identifier |
| `iter_algo_curves_to_use` | character vector | Which curves are available (subset of the 4 distributions) |

#### Return Value

Always returns `0`. The real outputs are **side effects** — writes to global variables:
- `iterations_list[[profile_id_analyzed]]` — List of all iterations tried
- `function_counter[profile_id_analyzed]` — Running count of recursive calls
- `profile_run_success_flag[profile_id_analyzed]` — Set to 0 if iteration limit exceeded

#### Step-by-Step Logic (The Algorithm)

This is a recursive backtracking tree search. Here is the complete flow:

```
┌──────────────────────────────────────────────────────────────────┐
│  validate_iteration(x, level, dist, counter, tracker, ...)      │
│                                                                  │
│  1. GUARD: If function_counter > 50,000 → abort (set flag = 0)  │
│                                                                  │
│  2. INCREMENT function_counter                                   │
│                                                                  │
│  3. RECORD this iteration in iterations_list (Convergence = 0)   │
│                                                                  │
│  4. SCAN x from first_index to last_index:                       │
│     For each position i:                                         │
│       If i == first_index:                                       │
│         INVALID if x[i] < 0.99                                  │
│       Else:                                                      │
│         INVALID if x[i] < 0.99 OR x[i] > x[i-1]               │
│       If INVALID → break with j=1, record position i            │
│                                                                  │
│  5. If j == 1 (invalid value found at position i):               │
│     a. SEARCH UPWARD from i back to first_index:                 │
│        Find the first index k where:                             │
│        - tracker[k] == 0 (haven't tried replacing here)          │
│        - At least one curve provides a valid replacement:        │
│          • curve_value[k] >= 1.0                                 │
│          • If k > first_index: curve_value[k] < x[k-1]          │
│                                                                  │
│     b. If found, mark tracker[k] = 1                             │
│                                                                  │
│     c. BRANCH: For each usable curve at position k:              │
│        - Create x_copy with x_copy[k] = curve_value[k]          │
│        - RECURSE: validate_iteration(x_copy, level+1, ...)      │
│                                                                  │
│     d. Up to 4 recursive branches per invalid position           │
│        (one per distribution: Exponential_Decay, Inverse_Power,  │
│         Power, Weibull)                                           │
│                                                                  │
│  6. If j == 0 (all values valid):                                │
│     → Mark this iteration's Convergence = 1                      │
│     → Algorithm has CONVERGED for this branch                    │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

#### The Constraint Rules

The algorithm enforces two constraints on the LDF sequence:

1. **Minimum value:** Every LDF must be ≥ 0.99
2. **Monotonic decrease:** Each LDF must be ≤ the previous LDF (no increases allowed after first_index)

```
For all i in [first_index, last_index]:
  x[i] ≥ 0.99
  x[i] ≤ x[i-1]   (for i > first_index)
```

#### Recursion Tree Example

```
Initial: x = [1.10, 1.05, 0.97, 1.02, 0.98]
                                 ^--- INVALID (< 0.99)

Level 0: Scan finds x[3] = 0.97 is invalid
         Search upward from index 3...
         Index 3: tracker[3]=0, ExpDecay[3]=1.01 < x[2]=1.05? Yes → branch
         
         Branch A (ExpDecay at 3):
           x = [1.10, 1.05, 1.01, 1.02, 0.98]
           Scan: x[4]=1.02 > x[3]=1.01 → INVALID at index 4
           Search upward...
           
           Branch A1 (Weibull at 4):
             x = [1.10, 1.05, 1.01, 1.00, 0.98]
             Scan: x[5]=0.98 < 0.99 → INVALID at index 5
             Search upward...
             
             Branch A1a (...):
               x = [1.10, 1.05, 1.01, 1.00, 0.99]
               Scan: ALL VALID → CONVERGED ✓
               
         Branch B (InversePower at 3):
           x = [1.10, 1.05, 1.03, 1.02, 0.98]
           Scan: x[4]=1.02 < x[3]=1.03? Yes. x[5]=0.98 < 0.99 → INVALID
           ...continues branching...
```

#### Global Variables Modified (Side Effects)

| Variable | Type | Description |
|----------|------|-------------|
| `iterations_list` | named list of lists | Each profile_id maps to a list of iteration data.frames. Every recursive call appends one. |
| `function_counter` | named numeric vector | Counts recursive calls per profile. Used to enforce the 50,000 iteration limit. |
| `profile_run_success_flag` | named numeric vector | Set to 0 if iteration limit exceeded (algorithm failed to converge within budget) |
| `iteration_num_threshold` | integer (read-only) | The maximum allowed iterations (50,000) |

#### Convergence Characteristics

- **Best case:** The initial selections already satisfy constraints → converges at Level 0.
- **Typical case:** A few replacements are needed → converges within a few hundred iterations.
- **Worst case:** Deep branching exhausts all 50,000 iterations without finding a valid sequence
  (the profile is flagged as non-converging).
- **Branching factor:** Up to 4 at each level (one per curve distribution).
- **Depth:** Up to `last_index - first_index + 1` levels.

#### The 0.99 Threshold

The file name says "0.99_modified" — this refers to the minimum acceptable factor value. A factor
of 0.99 means claims shrink by 1% in that development period. This is a practical floor: even in
lines with favorable development, a factor below 0.99 at a single step is considered noise or error,
not a real pattern.

---

## 4. How the Three Files Connect

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           LDF Selection Pipeline                            │
│                                                                             │
│  ┌───────────────────────────────────┐                                      │
│  │ fn_get_end_triangle_index         │                                      │
│  │ (MBR_factor_one_index.R)          │                                      │
│  │                                   │                                      │
│  │ Input: Claims triangle data       │                                      │
│  │ Output: end_index                 │───┐                                  │
│  │ "Where does development stop?"    │   │                                  │
│  └───────────────────────────────────┘   │                                  │
│                                          ▼                                  │
│  ┌───────────────────────────────────────────────────────────────┐          │
│  │ fn_get_less_than_one_factors_index                            │          │
│  │ fn_get_prop_less_than_one_factors                             │          │
│  │ fn_get_default_last_index_less_than_one_factors               │          │
│  │ (MBR_factor_less_than_one_index.R)                            │          │
│  │                                                               │          │
│  │ Input: LDF selections + end_index                             │          │
│  │ Output: Where <1 factors start, their proportion, drop points │───┐     │
│  │ "How do sub-1.0 factors behave within the active triangle?"   │   │     │
│  └───────────────────────────────────────────────────────────────┘   │     │
│                                                                      ▼     │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ validate_iteration + best_rsq_replace                                 │  │
│  │ (MBR_iteration_algorithm_0.99_modified.R)                             │  │
│  │                                                                       │  │
│  │ Input: Initial LDF selections + curve fits + index boundaries         │  │
│  │ Output: A valid, monotonically decreasing LDF sequence (≥ 0.99)      │  │
│  │ "Build the best constrained LDF sequence using curve substitutions"   │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  Final Output: Selected LDFs → used to compute ultimates                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Data Flow Summary

1. **Factor One Index** determines the boundary of meaningful development (`end_index`)
2. **Factor Less Than One** characterizes the sub-1.0 behavior within that boundary, providing:
   - The start of consecutive sub-1.0 runs
   - The proportion of sub-1.0 factors
   - Any significant drop points
3. **Iteration Algorithm** takes the initial LDF selections and, within the boundaries established
   by steps 1-2, constructs a valid monotonic sequence by selectively replacing values with curve fits
4. **Best R² Replace** post-processes the converged sequence, smoothing the tail with the
   highest-quality curve fit

### Key Design Decisions

- The 50,000-iteration cap prevents runaway computation for pathological profiles
- The `<<-` (superassignment) operator is used extensively in the iteration algorithm to write
  results to global scope — this is a side-effect-heavy design that Python conversion should replace
  with explicit return values or class state
- The algorithm explores ALL valid branches (it doesn't stop at first convergence), which means
  `iterations_list` can contain multiple converged solutions — downstream code selects the best one
  (typically by weighted RMSE)
