# Tail Factors and Development Indexes

## Factor One Index — Where Development Ends

From `MBR_factor_one_index.R.txt`, function `fn_get_end_triangle_index()`:

### Concept
At some development period, claims are essentially fully developed — any remaining movement is negligible. The **factor one index** identifies this point.

### Calculation
1. Compute incremental incurred as a proportion of total incurred per development period
2. Compute the cumulative proportion (running sum from the first period)
3. Find the first development period where **remaining proportion < 2%** (`factor_1_index_threshold = 0.02`)

```
Dev Period:    3     6     9     12    15    18    21    24
Incr %:       40%   25%   15%   10%   5%    3%    1.5%  0.5%
Cum %:        40%   65%   80%   90%   95%   98%   99.5% 100%
Remaining:    60%   35%   20%   10%   5%    2%    0.5%  0%
                                                  ^^^^
                                            Factor one index = 18
                                            (remaining first drops below 2%)
```

Beyond the factor one index, all LDFs are set to 1.000.

### Edge Case
If `factor_one_index < default_first_index`, it's overridden: `factor_one_index = default_first_index + 1`.

## Factor Less-Than-One Detection

Some profiles have development patterns where claims actually SHRINK at later periods (salvage, subrogation, favorable court rulings). These produce LDFs < 1.

From `MBR_factor_less_than_one_index.R.txt`:

### `fn_get_less_than_one_factors_index()`
Finds the first index where N consecutive factors are all < 1.
```
LDFs: [1.50, 1.20, 1.05, 0.98, 0.97, 0.99, 1.01, 0.96, 0.95]
                        ^^^^  ^^^^             (2 consecutive, but not N)
                                               ^^^^  ^^^^  (if N=2, found at index 8)
```

### `fn_get_prop_less_than_one_factors()`
Computes: (count of factors < 1 before factor_one_index) / (total factors before factor_one_index)

### `fn_get_default_last_index_less_than_one_factors()`
Detects sharp drops in the pattern of consecutive <1 factors. If the incremental percentage change exceeds 5%, that's the cutoff.

### Decision Logic
```
include_less_than_one_factors = TRUE if:
  (consecutive_<1_index exists AND before factor_one_index)
  OR (proportion of <1 factors ≥ threshold)
  OR (sharp drop detected)

If TRUE: default_last_index = min(default_last_index, <1_index - 1)
```

## Tail Factors — Extrapolating Beyond Observed Data

### What is a Tail Factor?
The observed triangle shows development up to a certain point. But claims may continue developing beyond that. The **tail factor** accounts for this unseen future development.

```
Observed:    dev 3 → dev 6 → ... → dev 99  (last observed)
Tail:        dev 99 → ultimate             (extrapolated)

Total CDF = observed CDF × tail factor
```

### Experience Method (`fn_tail_factor_experience_method`)
From `MBR_tail_factor_methods.R.txt`:

```r
tail_factor = product of initial selected LDFs from factor_one_index to outlier_detection_last_dev_period
```

This multiplies together the small LDFs at the end of the observed pattern — the "dribble" of remaining development.

**Example:**
```
LDFs at dev periods 78, 81, 84 (the "tail" zone):
  1.005 × 1.003 × 1.001 = 1.00901

Tail factor = 1.00901
```

### Constraint
If `include_less_than_one_factors == FALSE` and `tail_factor < 1`, force `tail_factor = 1`. (Don't allow negative tail development if the profile doesn't have significant <1 factors.)

### Applying the Tail Factor
The tail factor replaces the LDF at the `factor_one_index` development period in the best iteration:
```r
best_iteration_factors_df = mutate(best_iteration_factors_df,
  Incr_Factors = ifelse(dev_len == factor_1_dev_month, tail_factor, Incr_Factors))
best_iteration_factors_df$Cum_Factors = cumprod(best_iteration_factors_df$Incr_Factors)
best_iteration_factors_df$Cum_Percentages = 1 / best_iteration_factors_df$Cum_Factors
```

### NCCI Method (Currently Disabled)
`fn_tail_factor_NCCI_method()` uses the NCCI (National Council on Compensation Insurance) approach with growth factors. This is defined but commented out in the main code — only the experience method is actively used.

## Upper Triangle RMSE (`MBR_threshold_ultimate_weighted_RMSE.R.txt`)

`calc_upper_tri_rmse()` validates the quality of selected ultimates:

1. Using selected ultimates and cumulative percentages, **back-calculate** what incurred amounts would have been at each development stage
2. Compare back-calculated values against **actual** observed values on the diagonal
3. Compute weighted RMSE (weighted by development stage)

This is a quality check — large RMSE suggests the selected pattern doesn't match the actual data well.
