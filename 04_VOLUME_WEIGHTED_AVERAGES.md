# Volume-Weighted Averages and Initial Selection

## What is a Volume-Weighted Average?

A simple average treats all exposure years equally. A **volume-weighted average** gives more weight to exposure years with larger claim volumes, since they are more statistically credible.

### Formula

For n most recent exposure years at a given development period:

```
VW_n(dev_period) = Sum Cumulative(dev_period + 1) for last n years
                   ------------------------------------------------
                   Sum Cumulative(dev_period) for last n years
```

This is equivalent to summing the numerators and denominators separately, then dividing -- rather than averaging the individual ratios.

### Example

At dev_len=6, last 3 exposure years:

```
Year    Cumulative@6    Cumulative@9
2024    1,100K          1,300K
2025    1,030K          1,180K
2026     580K            (not available)
```

VW-2 = (1,300K + 1,180K) / (1,100K + 1,030K) = 2,480K / 2,130K = **1.1643**

A simple average would be: (1,300/1,100 + 1,180/1,030) / 2 = (1.1818 + 1.1456) / 2 = **1.1637** -- slightly different.

## The n-Period Concept

Different values of n capture different amounts of history. A smaller n is more responsive to recent trends; a larger n is more stable.

**Which n values are tested depends on SML:**

| SML | n values tested |
|-----|----------------|
| S (Short) | 3, 4, 5 |
| M (Medium) | 3, 4, 5, 6, 7, 8, 9, 10, 24 |
| L (Long) | 5, 6, 7, 8, 9, 10, 24 |

## calc_weighted_average() -- How It Works

From `MBR_weighted_average.R.txt`, lines 84-132:

```r
calc_weighted_average = function(n, data, age_to_age_outliers, remove_outliers_flag) {
  wa_matrix = matrix(nrow=1, ncol=4*years_analyzed-(4-analysis_qtr))  # one row of VW averages

  for(i in 1:(ncol(data)-1)) {  # iterate through adjacent column pairs
    temp_df = data[, i:(i+1)]   # get current and next development period columns
    # ... join with outlier flags, filter outliers if flag='Y'
    # ... remove rows with 0 incurred or NA values
    k = nrow(temp_df)            # count of valid data points

    if(k >= n)
      wa_matrix[1,i] = sum(temp_df[k:(k-n+1), 'n']) / sum(temp_df[k:(k-n+1), 'd'])
    else
      wa_matrix[1,i] = sum(temp_df[, 'n']) / sum(temp_df[, 'd'])  # use all if fewer than n
  }

  wa_matrix[1, length(wa_matrix)] = 1  # last development = 1 (no further development)
  wa_matrix[is.na(wa_matrix)] = 1      # fill NAs with 1
  return(wa_matrix)
}
```

Key points:

- `data` is the cumulative triangle matrix (rows = exp_years, columns = dev_periods)
- For each adjacent pair of columns: take the n most recent valid data points (by exp_year)
- "Valid" = not an outlier (if remove_outliers_flag='Y'), not zero, not NA
- If fewer than n points exist, use all available
- Results of 0, NaN, NA, or Inf are replaced with 1

## Selecting the Best VW Period

For each n, the system computes a **weighted RMSE** to measure how well VW-n matches the actual age-to-age factors.

From `MBR_iteration_weighted_rmse_sml.R.txt`, function `calc_VW_Averages_weighted_RMSE()`:

### Step 1: Convert VW Averages to Cumulative Percentages

```r
Factors_df$Cum_Factors = cumprod(Factors_df$Incr_Factors)  # cumulative product of LDFs
Factors_df$Cum_Percentages = 1 / Factors_df$Cum_Factors    # proportion developed
```

### Step 2: Compute Per-Period RMSE

For each development period, compute RMSE between actual age-to-age factors and the VW average.

### Step 3: Weight by Development Stage

```r
weights = |1 - Cum_Percentages|
weighted_rmse = Sum(dev_len_rmse * weights) / Sum(weights)
```

This gives MORE weight to earlier development periods (where Cum_Percentages is far from 1) because errors there have a bigger impact on the ultimate estimate.

### Step 4: Also Compute RMSE Excluding First N Periods

```
weighted_rmse_excl1 -- excludes first development period
weighted_rmse_excl2 -- excludes first 2
weighted_rmse_excl3 -- excludes first 3
weighted_rmse_excl4 -- excludes first 4
```

Early development periods can be noisy. The **selection is based on `weighted_rmse_excl1`** (excluding the first development period):

```r
volume_weighted_n = rownames(VW_Averages_wRMSE_excl1_df)[which.min(VW_Averages_wRMSE_excl1_df$weighted_rmse)]
```

## From VW Averages to CDFs and Cum_Percentages

Once the best VW-n is selected, the system computes the full development pattern:

```
Incremental LDFs (VW averages):  [1.50, 1.20, 1.08, 1.04, 1.02, 1.01, 1.00]
                                    | reverse cumulative product
CDFs (Cumulative Dev Factors):   [1.50*1.20*1.08*...  1.20*1.08*...  1.08*...  ...]
                                 = [2.124, 1.416, 1.180, 1.093, 1.051, 1.030, 1.010, 1.000]
                                    | reciprocal
Cum_Percentages:                 [0.471, 0.706, 0.847, 0.915, 0.951, 0.971, 0.990, 1.000]
```

**Interpretation:** At dev_period 3, only 47.1% of ultimate losses are reported. By dev_period 12, 91.5% is reported.

## Two Versions of VW Averages

The code computes VW averages TWICE:

1. **With outlier removal** (`wa_matrix`): Used for curve fitting and the iteration algorithm
2. **Without outlier removal** (`wa_matrix_wo_outliers`): Stored for diagnostic comparison

```r
wa_matrix = calc_weighted_average(volume_weighted_n, triangle_cum_matrix, age_to_age_outliers_df, remove_outliers_flag='Y')
wa_matrix_wo_outliers = calc_weighted_average(volume_weighted_n, triangle_cum_matrix, age_to_age_outliers_df, remove_outliers_flag='N')
```

## What Happens Next

The VW averages (with outlier removal) become the **Initial Selections** -- the starting point for:

1. **Curve Fitting** -- 4 mathematical distributions are fit to these initial selections
2. **Iteration Algorithm** -- uses initial selections as the base, tries replacing values with curve-fit alternatives
