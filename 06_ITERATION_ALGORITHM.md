# The Iteration Algorithm — Recursive Tree-Search for Valid LDF Sequences

## Purpose

The initial Volume-Weighted (VW) average LDFs may violate actuarial constraints — some values might be below 0.99 or not monotonically decreasing. The iteration algorithm generates **many alternative valid LDF sequences** by systematically replacing problematic values with curve-fit alternatives, then selects the best one by RMSE.

This is the **core innovation** of MBR: instead of an actuary manually adjusting the pattern, the algorithm explores a tree of possible adjustments and picks the statistically best one.

## The Two Constraints

Every valid LDF sequence must satisfy:

1. **Each LDF >= 0.99** — Claims shouldn't shrink significantly (a factor of 0.99 means 1% shrinkage, which is the minimum acceptable)
2. **Each LDF <= previous LDF** — Development should slow over time (monotonically decreasing sequence)

Exception: The first index position only needs constraint #1 (no predecessor to compare against).

### Example of an Invalid Sequence
```
Development:  3     6     9     12    15    18
LDF:         1.50  1.30  1.25  0.98  1.10  1.02
                               ^^^^  ^^^^
                               < 0.99  > previous (1.10 > 0.98)
```
Two violations: index 4 is below 0.99, index 5 is greater than its predecessor.

## The Index System

Several indexes control where the algorithm operates:

| Index | What it means | How it's determined |
|-------|--------------|-------------------|
| `default_first_index` | Start of algorithm range | Configuration parameter (early periods are trusted) |
| `default_last_index` | End of algorithm range | Configuration parameter, adjusted for <1 factors |
| `factor_one_index` | Where development effectively ends | First period where remaining incurred < 2% of total |

### Factor One Index (from `MBR_factor_one_index.R.txt`)
`fn_get_end_triangle_index()`:
- Computes the proportion of total incremental incurred at each development period
- Finds the first dev period where cumulative proportion exceeds `(1 - factor_1_index_threshold)`, i.e., less than 2% of total incurred remains
- Beyond this point, LDFs are set to 1.000 (no further development)

### Factor Less-Than-One Detection (from `MBR_factor_less_than_one_index.R.txt`)
Three functions assess whether below-1 factors are meaningful:
1. `fn_get_less_than_one_factors_index()`: Finds first index of N consecutive factors < 1
2. `fn_get_prop_less_than_one_factors()`: What proportion of factors (before factor_one_index) are < 1
3. `fn_get_default_last_index_less_than_one_factors()`: Detects sharp drops (>5% change) in the consecutive <1 factor pattern

**Decision logic:**
```
IF (consecutive <1 factors found AND before factor_one_index)
   OR (proportion of <1 factors >= threshold)
   OR (sharp drop detected):
   -> include_less_than_one_factors = TRUE
   -> Adjust default_last_index downward to stop before the <1 zone
```

## The Main Algorithm Flow

```
                        +-----------------------------------+
                        |  Initial VW Selections (x)        |
                        |  + Curve fit data (4 curves)      |
                        |  + R-squared rankings             |
                        +-----------------+-----------------+
                                          |
                    +---------------------+---------------------+
                    |                                           |
              <1 factors = NO                            <1 factors = YES
                    |                                           |
          +---------+---------+                    +------------+-----------+
          |                   |                    |                        |
    factor_one >        factor_one <=        idx_<1 >                idx_<1 <=
    default_last        default_last         default_last             default_last
          |                   |                    |                        |
   validate_iter      validate_iter         validate_iter           validate_iter
   [first->last]      [first->factor1-1]    [first->last]          [first->adj_last]
        +                                         +
   best_rsq_replace                          best_rsq_replace
   [last+1->factor1-1]                       [last+1->idx_<1-1]
```

## validate_iteration() — The Recursive Function

This is the heart of the algorithm. It's a **depth-first tree search** that explores different ways to fix constraint violations.

### Parameters
```r
validate_iteration(x, l, d, c, t, first_index, last_index, data, profile_id_analyzed, iter_algo_curves_to_use)
```
| Parameter | Type | Description |
|-----------|------|-------------|
| `x` | numeric vector | Current LDF sequence being validated |
| `l` | integer | Recursion level (depth in the tree) |
| `d` | string | Which distribution generated this branch |
| `c` | integer | Global function call counter value |
| `t` | integer vector | Index replacement tracker (1=already replaced, 0=available) |
| `first_index` | integer | Start of validation range |
| `last_index` | integer | End of validation range |
| `data` | dataframe | Curve fit values for all 4 distributions |
| `profile_id_analyzed` | string | Current profile ID |
| `iter_algo_curves_to_use` | character vector | Which curves to try (2 or 4) |

### Step-by-Step Walkthrough

```
STEP 1: Check iteration threshold
   IF function_counter > 11,000 -> STOP (set success flag to 0, return)
   This prevents infinite recursion for profiles with many violations.

STEP 2: Increment global function counter
   function_counter[profile] <<- function_counter[profile] + 1
   The <<- operator modifies the GLOBAL variable (R-specific; critical for Python conversion)

STEP 3: Record current iteration in global list
   iterations_list[[profile]][[c]] = data.frame(Iteration_Values=x, Level=l, ...)
   Initially marked as Convergence=0

STEP 4: Scan for violations
   FOR i = first_index TO last_index:
     IF i == first_index:
       violation = (x[i] < 0.99)
     ELSE:
       violation = (x[i] < 0.99) OR (x[i] > x[i-1])
     IF violation found -> BREAK (stop scanning, go fix it)

STEP 5: If violation found (j==1):
   Walk BACKWARDS from violation index i to first_index:
     FOR k = i DOWN TO first_index:
       IF tracker[k] == 0 (not yet replaced at this index):
         Check if ANY allowed curve provides a valid replacement at k:
           - curve_value >= 1 (must be >= 1, not just >= 0.99)
           - IF k > first_index: curve_value < x[k-1] (must be < predecessor)
         IF valid replacement exists -> BREAK (found replaceable index k)
       ELSE:
         CONTINUE backwards

   IF no replaceable index found -> "Algorithm did not converge" (dead end)

STEP 6: Create branches for each valid curve at index k
   For each allowed curve (Exponential, Weibull, Power, Inverse Power):
     IF curve provides valid value at k:
       x_copy = copy of x
       x_copy[k] = curve_value_at_k
       RECURSE: validate_iteration(x_copy, l+1, curve_name, ...)

STEP 7: If NO violation found (j==0):
   Mark iteration as CONVERGED:
   iterations_list[[profile]][[c]][5] <<- 1   (set Convergence column to 1)
```

### Tree Diagram — Worked Example

Starting with initial selections that violate at index 4:

```
Level 0: [1.50, 1.30, 1.25, 0.98, 1.10, 1.02]  <- violation at i=4 (0.98 < 0.99)
         Walk back from i=4: can replace at k=4
         +------------------+------------------+
         |                  |                  |
Level 1: Exp(k=4)=1.03     Weibull(k=4)=1.01  Power(k=4)=1.05
         [1.50,1.30,1.25,   [1.50,1.30,1.25,  [1.50,1.30,1.25,
          1.03,1.10,1.02]    1.01,1.10,1.02]    1.05,1.10,1.02]
         violation at i=5    violation at i=5    violation at i=5
         (1.10 > 1.03)      (1.10 > 1.01)     (1.10 > 1.05)
         |                   |                  |
Level 2: try replacing k=5  try replacing k=5  try replacing k=5
         Exp(k=5)=1.01      Exp(k=5)=1.01     Exp(k=5)=1.01
         [..,1.03,1.01,..]  [...,1.01,1.01,..]  invalid: 1.01<1.02@k=6?
         check k=6: 1.02>1.01 -> violation!      Actually checking if 1.01<1.05
         |                                       and 1.02>1.01 -> violation at k=6
Level 3: try replacing k=6
         ...and so on until converged or threshold hit
```

Each path through the tree produces one "iteration" — a candidate LDF sequence.

## best_rsq_replace() — Extending Beyond the Algorithm Range

After validate_iteration runs (covering first_index to default_last_index), there may be development periods from default_last_index+1 to factor_one_index-1 that also need values. These are filled using the best-fitting curve:

```r
best_rsq_replace = function(iteration, start_index, end_index, data, r_sq_data) {
  # r_sq_data is sorted by R-squared descending
  # For each curve (best R-squared first):
  #   Check if curve value at start_index < iteration value at start_index-1
  #   (ensures continuity -- new values must be below the last algorithm-set value)
  #   If valid: replace iteration values from start_index to end_index
  #   If NO curve can replace: force-use the best R-squared curve anyway
}
```

## Two-Phase Strategy

The algorithm is run in two phases to balance speed and completeness:

**Phase 1**: Use only the **top 2 curves** (by R-squared)
- Fewer branches per level -> fewer iterations -> faster
- Works for most profiles

**Phase 2** (only if Phase 1 produces zero converged iterations):
- Reset all counters and trackers
- Use **all 4 curves**
- More branches -> more iterations -> better chance of convergence

```r
if(profile_iteration_converged[profile_id_analyzed] == FALSE) {
  # Reset globals
  function_counter[profile_id_analyzed] <<- 0
  iterations_list[profile_id_analyzed] <<- list(list())
  
  # Use all 4 curves
  iter_algo_curves_to_use = r_sq_data$Distribution[1:4]
  
  # Re-run the same algorithm
  validate_iteration(...)
}
```

## Fallback: Initial Selection as Converged

After both phases, the first iteration (the initial VW selection itself) is ALWAYS marked as converged:
```r
iterations_list_final[[1]]$Convergence = 1
```
This ensures there's always at least one option, even if the algorithm can't find any fully valid sequence.

## Post-Algorithm: Set Values to 1 Beyond factor_one_index

```r
if(index_cons_1 < length(x)) {
  iterations_list_final = lapply(iterations_list_final, function(iter_df) {
    iter_df$Iteration_Values[index_cons_1:length(x)] = 1
    return(iter_df)
  })
}
```

## Selecting the Best Iteration (from `MBR_iteration_weighted_rmse_sml.R.txt`)

From all converged iterations, select the one with the **minimum weighted RMSE**:

### calc_weighted_RMSE() function:

1. Convert iteration's LDF values -> cumulative factors -> cumulative percentages
2. Compute DFM Ultimate per exposure year = Gross_Incurred x Cum_Factor
3. Compute incurred-to-ultimate ratio = Cumulative_Gross_Incurred / Ultimate
4. At each development period, compute RMSE between actual inc_to_ult and predicted Cum_Percentages
5. Weight by |1 - Cum_Percentages| (earlier development = higher weight)
6. Select iteration with minimum weighted RMSE

```r
iter_min_weighted_rmse = which.min(weighted_rmse_df$weighted_rmse)
best_iter_result_list = weighted_rmse_list[iter_min_weighted_rmse]
```

## Global Variables (Critical for Python Conversion)

The R code uses `<<-` (superassignment) to modify global state from within recursive calls:

| Variable | Type | Purpose |
|----------|------|---------|
| `iterations_list` | nested list | Stores ALL iterations (converged and non-converged) per profile |
| `function_counter` | named vector | Counts recursive calls per profile |
| `index_replacement_tracker` | matrix | Tracks which indexes have been replaced in current branch |
| `profile_run_success_flag` | named vector | Set to 0 if threshold exceeded |
| `profile_iteration_converged` | named logical | FALSE if no iteration converged |

**Python conversion note:** R's `<<-` modifies variables in the parent scope. In Python, use:
- A class with instance attributes (recommended)
- Mutable containers (dict/list) passed as arguments
- `nonlocal` or `global` keywords (least clean)

Also note: Python's default recursion limit is 1000. This algorithm can recurse thousands of levels deep. Either increase the limit (`sys.setrecursionlimit()`) or convert to an iterative approach with an explicit stack.

## Performance Characteristics

- **Iteration threshold**: 11,000 per profile (configurable via `iteration_num_threshold`)
- **Branching factor**: Up to 2 (Phase 1) or 4 (Phase 2) branches per level
- **Typical profiles**: Converge within hundreds to low thousands of iterations
- **Problematic profiles**: Hit the 11,000 cap and fall back to initial selection
- **Parallel execution**: Each profile runs independently on separate cores (10 workers)
