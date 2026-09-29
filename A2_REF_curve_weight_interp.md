# Detailed Analysis: Curve Fitting, Weighted Averages, and Interpolation

This document provides an exhaustive analysis of three R source files that form the statistical/mathematical backbone of the MBR (Machine Based Reserves) system:

1. **MBR_curve_fit.R.txt** — Fits parametric curves to Loss Development Factors (LDFs)
2. **MBR_weighted_average.R.txt** — Detects outliers and computes volume-weighted average LDFs
3. **MBR_interpolation.R.txt** — Interpolates cumulative development patterns for long-tail profiles

---

## Table of Contents

- [File 1: MBR_curve_fit.R.txt](#file-1-mbr_curve_fitrtext)
  - [Overview](#curve-fit-overview)
  - [Global Variables Used](#curve-fit-globals)
  - [Shared Algorithm: The Curve-Fitting + Influential-Point-Removal Pattern](#shared-algorithm)
  - [Function: exponentialfunc](#function-exponentialfunc)
  - [Function: weibullfunc](#function-weibullfunc)
  - [Function: powerfunc](#function-powerfunc)
  - [Function: IPCfunc (Inverse Power Curve)](#function-ipcfunc)
  - [Curve Comparison Summary Table](#curve-comparison-table)
- [File 2: MBR_weighted_average.R.txt](#file-2-mbr_weighted_averagertext)
  - [Overview](#weighted-avg-overview)
  - [Function: fn_get_age_to_age_outliers](#function-fn_get_age_to_age_outliers)
  - [Function: calc_weighted_average](#function-calc_weighted_average)
- [File 3: MBR_interpolation.R.txt](#file-3-mbr_interpolationrtext)
  - [Overview](#interpolation-overview)
  - [Function: calc_interpolation](#function-calc_interpolation)
  - [Function: func_convert_after_first_one](#function-func_convert_after_first_one)
- [How These Three Files Connect](#how-these-three-files-connect)

---

<a name="file-1-mbr_curve_fitrtext"></a>
## File 1: MBR_curve_fit.R.txt

<a name="curve-fit-overview"></a>
### Overview

This file defines **four curve-fitting functions**, each fitting a different parametric model to observed Loss Development Factors (LDFs). In actuarial reserving, LDFs tell you how much a claim amount "develops" (grows) from one development period to the next. Fitting a smooth curve to these observed LDFs lets you:

1. **Smooth out noise** in historical data
2. **Extrapolate** LDFs to future development periods where you have no observations
3. **Select** a "best fit" curve among competing models

All four functions follow the **exact same algorithmic pattern** but differ only in the mathematical transformation applied.

<a name="curve-fit-globals"></a>
### Global Variables Used

These are set in `SLU_main_code.R` and used freely inside the functions:

| Variable | Example Value | Meaning |
|---|---|---|
| `years_analyzed` | 25 | Maximum number of exposure years in the triangle |
| `analysis_qtr` | 3 | Current quarter (1-4) — Q3 2026 in the current run |

A global empty data frame `df` is created at the top of the file:
```r
df <- as.data.frame(x=numeric(), y=numeric(), rsq=numeric(), rmse=numeric(), dcook=numeric())
```
This is reused inside each function to accumulate leave-one-out diagnostics. **Note**: This is a mutable global — every function call resets/rebuilds it internally.

<a name="shared-algorithm"></a>
### Shared Algorithm: The Curve-Fitting + Influential-Point-Removal Pattern

Every function (`exponentialfunc`, `weibullfunc`, `powerfunc`, `IPCfunc`) follows this exact 7-step pattern:

```
Step 1: Build x-axis (development months) based on sml_flag
Step 2: Filter to data points where LDF > 1
Step 3: Fit the curve to ALL qualifying points → get ŷ (predicted values)
Step 4: Leave-one-out loop:
        For each point i:
          a) Remove point i
          b) Refit the curve on remaining points
          c) Compute R², RMSE, and Cook's Distance
Step 5: Flag influential points for removal:
          - The point whose removal gives the LOWEST RMSE
          - The point whose removal gives the HIGHEST R²
          - Any point with Cook's Distance > 1
Step 6: Remove flagged points, refit curve on clean data
Step 7: Project fitted values across ALL development months
```

**Why LDF > 1 filter?** An LDF of 1.0 means "no further development" — it adds no information to the curve and can distort the fit. All transformations (log, etc.) also require LDF > 1 to avoid log(0) or division by zero.

**Why leave-one-out?** This is a diagnostic technique: if removing a single data point dramatically improves the fit (higher R² or lower RMSE), that point is an outlier distorting the curve. Cook's Distance > 1 is a classical statistical threshold for "influential" points.

**Fallback**: If ≤ 2 data points remain after removing influential points, the curve fit is abandoned and all fitted LDFs are set to 1.0 (meaning "no development" — a safe conservative default).

#### Step 1 Detail: X-axis Construction

The x-axis represents development months. The construction differs by tail length:

**For S (Short) and M (Medium) tailed profiles** (`sml_flag != 'L'`):
```
x = seq(3, 3*4*years_analyzed - (4-analysis_qtr)*3, by=3)
```
- Generates quarterly development months: 3, 6, 9, 12, 15, ..., up to the last observed quarter
- Example with years_analyzed=25, analysis_qtr=3: x = 3, 6, 9, 12, ..., 297

**For L (Long) tailed profiles** (`sml_flag == 'L'`):
```
x = seq(12, years_analyzed*12, by=12)
```
- Generates annual development months: 12, 24, 36, ..., 300
- The y1 input is trimmed to `years_analyzed` rows
- At the end, x labels are remapped: `seq(3*analysis_qtr, years_analyzed*12, by=12)` so development months align with the rest of the system (e.g., 9, 21, 33, ... for Q3)

#### Step 3/6 Detail: Linear Regression (Manual Implementation)

All four functions compute linear regression coefficients **by hand** using the normal equations rather than calling R's `lm()`. The generic formulas (where X and Y are the transformed variables specific to each curve type):

```
sum_x  = Σ Xᵢ
sum_y  = Σ Yᵢ
xx     = Σ Xᵢ²
xy     = Σ Xᵢ·Yᵢ
n      = number of data points

Sxx    = xx - (sum_x²) / n
Sxy    = xy - sum_x · sum_y / n
b      = Sxy / Sxx          (slope)
a      = sum_y/n - b·sum_x/n  (intercept)

SS_res   = Σ (Yᵢ - (a + b·Xᵢ))²
SS_total = Σ (Yᵢ - mean(Y))²
R²       = 1 - SS_res / SS_total
```

If `Sxx == 0` (all x-values identical), `b` defaults to 1 to avoid division by zero.
If `SS_total == 0` (all y-values identical), the ratio is set to 1 making R² = 0.

#### Step 4c Detail: Cook's Distance (Custom Formula)

The code uses a custom Cook's Distance formula:
```
Cook_D = Σ (ŷ_full - ŷ_without_i)² / (2 · RMSE²)
```
Where:
- `ŷ_full` = predicted values from the full model (all points)
- `ŷ_without_i` = predicted values from the model with point i removed
- `RMSE` = root mean squared error of the model without point i

This measures how much the entire set of predictions shifts when a single point is removed.

#### Step 5 Detail: Influential Point Flagging

```r
df = mutate(df,
  to_remove = ifelse(
    rmse == min(rmse) | rsq == max(rsq) | dcook > 1,
    'Y', 'N'
  )
)
```

A point is flagged for removal if ANY of these is true:
- Its removal produces the **minimum RMSE** (it was the most harmful to error)
- Its removal produces the **maximum R²** (it was the most harmful to fit quality)
- Its Cook's Distance > 1 (classical influence threshold)

All flagged points are removed simultaneously, then the curve is refit once on the clean dataset.

---

<a name="function-exponentialfunc"></a>
### Function: `exponentialfunc(y1, sml_flag)`

**Parameters:**
- `y1`: Data frame with one column of LDF values. Row names are exposure years.
- `sml_flag`: Character — `'S'`, `'M'`, or `'L'` for short/medium/long tail

**Returns:** A named list with three elements:
- `exp_df`: Data frame with columns `x` (dev months), `y` (observed LDFs), `ycap_noexcl` (fitted LDFs)
- `exp_rsq`: R² of the final fit
- `influential_points_df`: Diagnostics data frame showing each point's R², RMSE, Cook's D, and whether it was removed

**Mathematical Model:**

The exponential curve models LDFs as:

```
LDF(x) = 1 + exp(a) · exp(b · x)
```

Or equivalently: `LDF(x) = 1 + e^(a + b·x)`

**Linearization:** Taking `Y = ln(LDF - 1)` and `X = x` gives:
```
Y = a + b · X
```
This is a standard linear regression in the transformed space.

**Intuition:** The LDF decays exponentially toward 1.0 as development age increases. The `1 +` shift ensures the asymptote is at LDF = 1 (no further development).

**Actuarial Meaning:** This model assumes the "excess LDF" (the part above 1) decays at a constant percentage rate per development month. Appropriate when claims develop quickly at first and slow down exponentially.

---

<a name="function-weibullfunc"></a>
### Function: `weibullfunc(y1, sml_flag)`

**Parameters and Return:** Same structure as `exponentialfunc`, but keys are `wbl_df`, `wbl_rsq`, `influential_points_df`.

**Mathematical Model:**

```
LDF(x) = 1 / (1 - exp(-exp(a + b · ln(x))))
```

**Linearization:** Taking `Y = ln(ln(LDF / (LDF - 1)))` and `X = ln(x)` gives:
```
Y = a + b · X
```

**Derivation of the transformation:**
- Start with `LDF = 1/(1 - exp(-λ))` where `λ = exp(a + b·ln(x))`
- Then `LDF/(LDF-1) = exp(λ)` → `ln(LDF/(LDF-1)) = λ` → `ln(ln(LDF/(LDF-1))) = a + b·ln(x)`

**Actuarial Meaning:** The Weibull model is more flexible than exponential — the `ln(x)` term means the rate of decay itself changes with age. This captures the common pattern where early development is rapid and then slows, but the rate of slowing itself changes. Good for medium-to-long tailed lines of business.

---

<a name="function-powerfunc"></a>
### Function: `powerfunc(y1, sml_flag)`

**Parameters and Return:** Same structure, keys are `pow_df`, `pow_rsq`, `influential_points_df`.

**Mathematical Model:**

```
LDF(x) = exp(exp(a + b · x))
```

**Linearization:** Taking `Y = ln(ln(LDF))` and `X = x` gives:
```
Y = a + b · X
```

**Important:** This model has NO `+1` shift. The double-exponential means LDFs can grow extremely large for small x and approach 1.0 as x → ∞ only if b < 0.

**Special Guard (unique to Power):** Line 371 adds an extra check:
```r
if(nrow(df) <= 2 | any(m$ycap_noexcl > 999999)){
  m$ycap_noexcl = 1
}
```
If any fitted value exceeds 999,999, the curve is abandoned. This protects against the double-exponential blowing up.

**Actuarial Meaning:** The power curve is aggressive — it models very rapid early development. Useful for lines where early development is extremely volatile but converges quickly. The 999,999 guard acknowledges this model can produce nonsensical results.

---

<a name="function-ipcfunc"></a>
### Function: `IPCfunc(y1, sml_flag)` — Inverse Power Curve

**Parameters and Return:** Same structure, keys are `IPC_df`, `IPC_rsq`, `influential_points_df`.

**Mathematical Model:**

```
LDF(x) = 1 + exp(a + b · ln(x + c))
```

Where `c` is a **shift parameter** chosen from a predefined grid.

**The c-selection process:**

```r
c_possible_values <- c(-0.5, 0, 1, 3, 5)
```

These are scaled by 3 (quarterly) or 12 (annual) depending on `sml_flag`:
- Quarterly: c ∈ {-1.5, 0, 3, 9, 15}
- Annual: c ∈ {-6, 0, 12, 36, 60}

For each candidate `c`:
1. Fit the linear regression: `ln(LDF - 1) = a + b · ln(x + c)`
2. Compute R²
3. Select the `c` with the highest R²

Then the full influential-point-removal algorithm runs with the selected `c`.

**Linearization:** Taking `Y = ln(LDF - 1)` and `X = ln(x + c)` gives:
```
Y = a + b · X
```

**Actuarial Meaning:** The inverse power curve is the most flexible of the four. The shift parameter `c` allows the curve to adapt to different "starting points" — some lines of business start developing immediately while others have a delay. The `ln(x + c)` term gives a power-law decay rate.

**Note (possible bug):** In line 494, the leave-one-out loop uses `IPC_sxx_noexcl` (from the full model) instead of `IPC_sxx` (from the reduced model):
```r
IPC_b <- ifelse(IPC_sxx_noexcl == 0, 1, IPC_sxy / IPC_sxx_noexcl)
```
This may be intentional (using the full-model Sxx as a stabilizer) or a copy-paste error. Every other function uses the reduced-model `sxx` in this position.

---

<a name="curve-comparison-table"></a>
### Curve Comparison Summary Table

| Curve | Formula for LDF(x) | Transformed Y | Transformed X | Best For |
|---|---|---|---|---|
| Exponential | `1 + exp(a + b·x)` | `ln(LDF - 1)` | `x` | Constant decay rate |
| Weibull | `1/(1 - exp(-exp(a + b·ln(x))))` | `ln(ln(LDF/(LDF-1)))` | `ln(x)` | Variable decay rate |
| Power | `exp(exp(a + b·x))` | `ln(ln(LDF))` | `x` | Very rapid early dev |
| Inverse Power | `1 + exp(a + b·ln(x+c))` | `ln(LDF - 1)` | `ln(x + c)` | Flexible with shift |

All four produce R² values that are compared downstream (in other files) to select the best-fitting curve for each profile.

---

<a name="file-2-mbr_weighted_averagertext"></a>
## File 2: MBR_weighted_average.R.txt

<a name="weighted-avg-overview"></a>
### Overview

This file provides two functions:
1. **Outlier detection** on age-to-age factors using an adjusted box plot method
2. **Volume-weighted average** computation of LDFs across exposure years

These are used *before* curve fitting to produce the raw LDF estimates from the loss triangle.

---

<a name="function-fn_get_age_to_age_outliers"></a>
### Function: `fn_get_age_to_age_outliers(actuals_cum, sml_flag)`

**Parameters:**
- `actuals_cum`: Data frame of cumulative incurred losses with columns including `profile_id`, `exp_year`, `dev_len`, `Cumulative_Gross_Incurred`, `Gross_Incurred`
- `sml_flag`: `'S'`, `'M'`, or `'L'`

**Returns:** A named list:
- `actuals_cum`: The input data frame augmented with `age_to_age` factors, outlier statistics, and an `outlier_flag` column (1 = outlier, 0 = not)
- `outlier_detection_last_dev_period_index`: The index of the last development period where outlier detection was performed

**Global variables used:**
- `exp_year_dev_len`: Data frame mapping exposure years to their maximum development length
- `outlier_detection_min_points`: Minimum number of data points required at a development period for outlier detection (set in main code)

#### Step-by-Step Logic

**Step 1: Compute age-to-age factors**
```r
actuals_cum = mutate(actuals_cum,
  age_to_age = lead(Cumulative_Gross_Incurred) / Cumulative_Gross_Incurred
)
```
For each row, the age-to-age factor is `next_period_cumulative / this_period_cumulative`. This is the raw LDF.

Invalid values (NA, NaN, Inf) are replaced with 1.

**Step 2: Identify exposure years to exclude**

Two categories of exposure years are excluded:
1. Years where **total gross incurred ≤ 0** (no meaningful development data)
2. Years with **negative cumulative incurred** at any development (can't compute meaningful ratios)

Also, the **last diagonal** of each exposure year is removed (can't compute a forward-looking ratio for the most recent observation).

**Step 3: Compute quartile-based outlier bounds per development period**

For each development period (dev_len), compute:

| Statistic | Formula |
|---|---|
| IQR | Q3 - Q1 (interquartile range) |
| Q1 | 25th percentile of age-to-age factors |
| Q3 | 75th percentile of age-to-age factors |
| MC | Medcouple — a robust measure of skewness, capped to [-0.5, 0.5] |
| Skewness | Classical skewness of the age-to-age factors |

The **medcouple** (MC) is computed using `mrfDepth::medcouple()`. It measures asymmetry: MC > 0 means right-skewed, MC < 0 means left-skewed.

**Step 4: Compute adjusted outlier bounds**

```
Min_Range = Q1 - 3 · exp(-Skewness · |MC|) · IQR    (if IQR ≠ 0)
          = 0.95 · Q1                                  (if IQR = 0)

Max_Range = Q3 + 3 · exp(Skewness · MC) · IQR         (if IQR ≠ 0)
          = 1.05 · Q3                                  (if IQR = 0)
```

**Why this formula?** This is an **adjusted box plot** method. Standard box plots use fixed 1.5·IQR whiskers, which don't account for skewness. The exponential adjustment:
- When data is right-skewed (Skewness > 0, MC > 0): the upper fence expands (allowing higher values) and the lower fence contracts
- When data is left-skewed: the opposite

The multiplier of 3 (instead of the standard 1.5) makes this a wider fence — more conservative about flagging outliers.

**Step 5: Limit outlier detection to qualifying development periods**

Outlier detection only runs for development periods that have at least `outlier_detection_min_points` data points. The variable `outlier_detection_last_dev_month` is set to the latest development month meeting this criterion.

**Step 6: Flag outliers**

```r
outlier_flag = ifelse(age_to_age < Min_Range | age_to_age > Max_Range, 1, 0)
```

For development periods beyond the outlier detection range, `outlier_flag` defaults to 0 (no outlier — keep everything).

**Actuarial Meaning:** Age-to-age factors in later development periods are based on fewer observations and are naturally more volatile. The outlier detection focuses on earlier development periods where you have enough data to reliably identify anomalies. Outliers might represent one-time large settlements, litigation events, or data errors.

---

<a name="function-calc_weighted_average"></a>
### Function: `calc_weighted_average(n, data, age_to_age_outliers, remove_outliers_flag)`

**Parameters:**
- `n`: Integer — the number of most recent exposure years to include in the average. E.g., `n=5` means "use the 5 most recent years"
- `data`: Matrix of cumulative incurred losses. Rows = exposure years, columns = development periods. Row names are exposure years, column names are development months.
- `age_to_age_outliers`: Data frame from `fn_get_age_to_age_outliers` containing the `outlier_flag` column
- `remove_outliers_flag`: `'Y'` or `'N'` — whether to exclude outliers

**Returns:** A 1-row matrix of volume-weighted average LDFs, one value per development period.

#### Step-by-Step Logic

**For each development period i** (column index):

1. Extract the pair of consecutive columns `(data[,i], data[,i+1])` — the "denominator" (current cumulative) and "numerator" (next cumulative)
2. Join with the outlier flags for that development period
3. If `remove_outliers_flag == 'Y'`, remove rows where `outlier_flag == 1`
4. Remove rows where denominator or numerator is 0 or NA
5. Take the **n most recent** qualifying rows (if fewer than n exist, use all of them)
6. Compute:

```
Volume_Weighted_LDF = Σ numerator[last n rows] / Σ denominator[last n rows]
```

7. If the result is 0, NaN, NA, or Inf → set to 1.0

The last development period's LDF is always set to 1.0 (no further development observable). Any remaining NA values are set to 1.0.

**Actuarial Meaning:** Volume-weighted averages give more weight to exposure years with larger loss amounts. This is preferred over simple averages because a year with $100M in claims is more informative about the development pattern than a year with $1M. Using only the `n` most recent years captures the most current trends.

**Example:**

Suppose for development period 12-to-24 months, the last 3 years show:

| Exp Year | Cum @ 12mo | Cum @ 24mo |
|---|---|---|
| 2024 | 50,000 | 75,000 |
| 2025 | 80,000 | 100,000 |
| 2026 | 30,000 | 42,000 |

Volume-weighted LDF = (75000 + 100000 + 42000) / (50000 + 80000 + 30000) = 217000 / 160000 = **1.356**

Simple average LDF = (1.500 + 1.250 + 1.400) / 3 = **1.383**

The volume-weighted version is pulled toward the 2025 year (largest volume) which had the lowest LDF.

---

<a name="file-3-mbr_interpolationrtext"></a>
## File 3: MBR_interpolation.R.txt

<a name="interpolation-overview"></a>
### Overview

This file handles interpolation for **long-tailed (L) profiles only**. Long-tailed profiles have annual development periods (every 12 months), but the rest of the system works on quarterly (every 3 months). This file uses **cubic spline interpolation** to fill in the quarterly pattern values between the annual knot points.

---

<a name="function-calc_interpolation"></a>
### Function: `calc_interpolation(profile)`

**Parameters:**
- `profile`: Character string — the profile ID (e.g., `"AERO_Airports-Products"`)

**Returns:** A data frame with columns:
- `dev_len`: Development month (quarterly: 3, 6, 9, 12, ...)
- `Cum_Percentages`: Interpolated cumulative development percentages
- `profile_id`: The profile identifier

**Global variables used:**
- `MBR_Cum_Percentages_Vena_df_L`: Data frame of cumulative percentages for long-tail profiles (from Vena data)
- `analysis_qtr`: Current quarter

#### Step-by-Step Logic

**Step 1: Extract and sort the profile's cumulative pattern**
```r
df_1 = filter(MBR_Cum_Percentages_Vena_df_L, profile_id == profile)
df_1 <- df_1[order(df_1$dev_len, decreasing = FALSE), ]
pattern = c(df_1$Cum_Percentages)
```

The `pattern` vector contains cumulative development percentages at annual intervals. For example: `[0.30, 0.55, 0.72, 0.85, 0.92, 0.96, 0.98, 1.00]`

**Step 2: Construct spline knots and interpolate**

The approach differs by quarter:

**If analysis_qtr == 3 (Q3):**

Two separate splines are constructed:

*Early months (months 1-3):*
```r
x1 = c(0, 3, 6, 9)
y1 = c(0, 0, 0, pattern[1])
func = splinefun(x=x1, y=y1, method="natural", ties=mean)
result1 = func(seq(1, 3, 1))  # Months 1, 2, 3
```
This creates a spline from zero through to the first annual observation at month 9. Months 3 and 6 are assumed to be 0 (no development yet).

*Main pattern (months 3-297):*
```r
x = c(0, seq(9, 297, 12))   # 0, 9, 21, 33, ..., 297
y = c(0, pattern)
func = splinefun(x=x, y=y, method="natural", ties=mean)
result = func(seq(3, 297, 1))  # Every month from 3 to 297
```

The two results are combined, then filtered to keep only quarterly dev months.

**If analysis_qtr != 3 (Q1):**

A single spline:
```r
x = c(0, seq(3, 291, 12))   # 0, 3, 15, 27, ..., 291
y = c(0, pattern)
func = splinefun(x=x, y=y, method="natural", ties=mean)
result = func(seq(3, 291, 1))
```

**Step 3: Filter to quarterly development months**
```r
dev_len = seq(3, 3*4*years_analyzed - 3*(4-analysis_qtr), by=3)
result_final = filter(result_final, `Dev Month` %in% dev_len)
```

Only the quarterly points (3, 6, 9, 12, 15, ...) are retained.

**What is `splinefun` doing?** It creates a **natural cubic spline** — a smooth curve that passes through every knot point, with continuous first and second derivatives. "Natural" means the second derivative is zero at the endpoints (no curvature at the boundaries). This produces smooth, non-oscillatory interpolation between annual observations.

**Actuarial Meaning:** Long-tailed lines (like asbestos, environmental liability) develop over decades. Their development patterns are tracked annually, but the reserving system needs quarterly granularity to match the valuation cycle. The spline converts annual cumulative percentages to quarterly ones while preserving the overall shape.

**Visual Example:**

```
Annual observations (knot points):
Month:   0    9    21    33    45    57    ...
Cum%:  0.00  0.15  0.40  0.60  0.75  0.85  ...

After spline interpolation (quarterly):
Month:   3     6     9    12    15    18    21    24    ...
Cum%:  0.02  0.08  0.15  0.22  0.28  0.34  0.40  0.46  ...
       ^     ^           ^     ^     ^           ^
    interpolated     observed  interpolated   observed
```

---

<a name="function-func_convert_after_first_one"></a>
### Function: `func_convert_after_first_one(profile)`

**Parameters:**
- `profile`: Character string — the profile ID

**Returns:** Data frame with `Cum_Percentages` corrected so all values after the first 1.0 are also 1.0.

**Global variable used:**
- `interpolation_result`: The output of `calc_interpolation` (all profiles combined)

#### Logic

```r
min_index = which(df$Cum_Percentages == 1)[1]
if (!is.na(min_index)) {
  df$Cum_Percentages[min_index:length(df$Cum_Percentages)] = 1
}
```

Finds the first development month where cumulative percentage equals exactly 1.0 (100% developed), then forces all subsequent months to 1.0 as well.

**Why is this needed?** Cubic splines can **oscillate** — after reaching 1.0, the spline might dip below 1.0 or exceed 1.0 before settling. This is physically impossible (cumulative development can't go backward once claims are fully developed). This function enforces the monotonicity constraint at the tail.

**Example of the problem:**
```
Without correction:
Month 240: 0.998
Month 252: 1.000  ← first reaches 1.0
Month 264: 1.002  ← spline overshoots!
Month 276: 0.999  ← spline oscillates back

With correction:
Month 252: 1.000
Month 264: 1.000  ← forced to 1.0
Month 276: 1.000  ← forced to 1.0
```

---

<a name="how-these-three-files-connect"></a>
## How These Three Files Connect

```
                    Raw Loss Triangle Data
                           │
                           ▼
              ┌─────────────────────────┐
              │  fn_get_age_to_age_     │
              │  outliers()              │  ← MBR_weighted_average.R
              │  (Detect statistical    │
              │   outliers in LDFs)     │
              └────────────┬────────────┘
                           │
                    Outlier-flagged data
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
   ┌──────────────────┐    ┌──────────────────────┐
   │ calc_weighted_   │    │ calc_weighted_        │
   │ average(n=3,     │    │ average(n=5,          │
   │ remove='Y')      │    │ remove='N')           │
   │                  │    │ ... various n values  │
   └────────┬─────────┘    └──────────┬────────────┘
            │                         │
            └────────────┬────────────┘
                         │
              Volume-weighted LDFs
              (multiple averaging windows)
                         │
              ┌──────────┴───────────┐
              │                      │
              ▼                      ▼
   ┌──────────────────┐   ┌──────────────────┐
   │  Curve Fitting    │   │  Curve Fitting    │
   │  (S/M profiles)   │   │  (L profiles)     │
   │                   │   │                   │
   │  exponentialfunc  │   │  exponentialfunc   │
   │  weibullfunc      │   │  weibullfunc       │
   │  powerfunc        │   │  powerfunc         │
   │  IPCfunc          │   │  IPCfunc           │
   └────────┬──────────┘   └──────────┬────────┘
            │                         │
            │  Best R² curve          │  Best R² curve
            │  selected per           │  selected per
            │  profile                │  profile
            ▼                         ▼
   ┌──────────────────┐   ┌──────────────────┐
   │  Smoothed LDFs   │   │  Smoothed LDFs   │
   │  (quarterly)     │   │  (annual → needs  │
   │                  │   │   interpolation)  │
   └────────┬─────────┘   └──────────┬────────┘
            │                        │
            │                        ▼
            │              ┌──────────────────┐
            │              │ calc_interpolation│ ← MBR_interpolation.R
            │              │ (spline annual → │
            │              │  quarterly)      │
            │              └──────────┬───────┘
            │                        │
            │                        ▼
            │              ┌──────────────────┐
            │              │func_convert_after│
            │              │_first_one()      │
            │              │(cap at 1.0)      │
            │              └──────────┬───────┘
            │                        │
            └────────────┬───────────┘
                         │
              Quarterly cumulative percentages
              (used downstream for ultimate
               loss calculations)
```

### Data Flow Summary

1. **MBR_weighted_average.R** acts first — it takes raw cumulative incurred data, detects outliers, and computes volume-weighted average LDFs for various averaging windows (e.g., last 3 years, last 5 years, all years).

2. **MBR_curve_fit.R** takes the weighted-average LDFs and fits four parametric curves, selecting the best one per profile based on R². This produces smoothed LDFs that can be extrapolated beyond the observed data.

3. **MBR_interpolation.R** is needed only for long-tailed profiles. After curve fitting produces annual cumulative percentages, this file interpolates them to quarterly granularity so they can be used in the same framework as short/medium-tailed profiles.

The output — quarterly cumulative development percentages per profile — feeds into `MBR_actuarial_method_ultimates.R` where Bornhuetter-Ferguson, Cape Cod, and other methods use these patterns to estimate ultimate losses.
