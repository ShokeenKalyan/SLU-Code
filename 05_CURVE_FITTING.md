# Curve Fitting — Four Distribution Models

## Purpose

After computing the initial Volume-Weighted (VW) average LDFs, four mathematical curves are fit to smooth the pattern. These curves serve two purposes:
1. **Provide replacement values** for the iteration algorithm when VW values violate constraints
2. **Extrapolate behavior** for development periods with sparse data

Each curve models how LDFs decay from large values (early development) toward 1.0 (fully developed).

## Overview of All Four Curves

| Curve | Formula | Linearized Form | R Function |
|-------|---------|----------------|------------|
| Exponential Decay | y = 1 + exp(a + b·x) | log(y-1) = a + b·x | `exponentialfunc()` |
| Weibull | y = 1/(1-exp(-exp(a+b·ln(x)))) | log(log(y/(y-1))) = a + b·log(x) | `weibullfunc()` |
| Power | y = exp(exp(a + b·x)) | log(log(y)) = a + b·x | `powerfunc()` |
| Inverse Power (IPC) | y = 1 + exp(a + b·ln(x+c)) | log(y-1) = a + b·log(x+c) | `IPCfunc()` |

All curves:
- Only use data points where y > 1 (LDFs above 1 — can't log-transform values ≤ 1)
- Use SML-specific period ranges (multiplier: S/M=3 for quarterly, L=12 for annual)
- Apply Cook's Distance to remove influential points, then refit

## Curve 1: Exponential Decay

**Mathematical Model:**
```
y = 1 + exp(a + b·x)
```
Where x = development period (3, 6, 9, ... or 12, 24, 36, ...) and y = LDF value.

**Linearization:** Since we can't directly fit a nonlinear model with `lm()`, we transform:
```
y - 1 = exp(a + b·x)
log(y - 1) = a + b·x    ← This IS a linear model!
```

**R Code:**
```r
# Filter to valid data points (y > 1, within SML range)
exp_df = filter(y1_df, y > 1, x >= period_multiplier, x <= period_multiplier * years_analyzed)

# Fit linear model on log-transformed data
model = lm(log(y - 1) ~ x, data = exp_df)

# Predict: transform back
ycap = 1 + exp(predict(model, newdata = ...))
```

**Behavior:** Decays exponentially. Good for lines where development slows at a constant rate.

## Curve 2: Weibull

**Mathematical Model:**
```
y = 1 / (1 - exp(-exp(a + b·ln(x))))
```

**Linearization:**
```
y/(y-1) = 1/(1 - exp(-exp(a+b·ln(x)))) / (exp(-exp(a+b·ln(x)))/(1 - exp(-exp(a+b·ln(x)))))
```
After algebraic manipulation:
```
log(log(y / (y - 1))) = a + b·log(x)
```

**R Code:**
```r
weibull_df = filter(y1_df, y > 1, ...)
model = lm(log(log(y / (y - 1))) ~ log(x), data = weibull_df)
```

**Behavior:** Flexible S-shaped decay. Can model both rapid initial development and long tails.

## Curve 3: Power

**Mathematical Model:**
```
y = exp(exp(a + b·x))
```

**Linearization:**
```
log(y) = exp(a + b·x)
log(log(y)) = a + b·x
```

**R Code:**
```r
pow_df = filter(y1_df, y > 1, ...)
model = lm(log(log(y)) ~ x, data = pow_df)
```

**Behavior:** Double-exponential decay. Can model very rapid initial decline.

## Curve 4: Inverse Power (IPC)

**Mathematical Model:**
```
y = 1 + exp(a + b·ln(x + c))
```
Where `c` is an additional shift parameter.

**Linearization:**
```
log(y - 1) = a + b·log(x + c)
```

**Key Difference:** The constant `c` must be optimized. The code tries multiple values:
```r
c_values = c(-0.5, 0, 1, 3, 5) * period_multiplier
# period_multiplier = 3 for S/M (quarterly), 12 for L (annual)
```

For each `c` value:
1. Fit the linear model
2. Compute R²
3. Keep the `c` with highest R²

If ALL `c` values fail (no valid fit), falls back to the Exponential Decay formula.

**R Code (simplified):**
```r
for(c_val in c_values) {
  IPC_df$log_x_plus_c = log(IPC_df$x + c_val)
  model = lm(log(y - 1) ~ log_x_plus_c, data = IPC_df)
  r_sq = summary(model)$r.squared
  if(r_sq > best_r_sq) { best_model = model; best_r_sq = r_sq }
}
```

**Behavior:** More flexible than Exponential Decay due to the shift parameter. Can better fit curves where early development doesn't follow a simple exponential pattern.

## Cook's Distance — Influential Point Removal

### What is Cook's Distance?
A statistical measure that quantifies how much the regression changes when a single data point is removed. Points with high Cook's Distance are "influential" — they disproportionately affect the fit.

### The Process (identical for all 4 curves):

```
Step 1: Fit initial model to all valid data points
Step 2: Compute Cook's Distance for each point
Step 3: Flag points where Cook's D > 4/n (n = number of data points)
Step 4: Remove flagged points
Step 5: Refit model on remaining points
Step 6: Use the REFITTED model's predictions going forward
```

**R Code:**
```r
# Step 1: Initial fit
model = lm(log(y-1) ~ x, data = exp_df)

# Step 2-3: Identify influential points
cooks_d = cooks.distance(model)
influential = which(cooks_d > 4/nrow(exp_df))

# Step 4: Remove influential points
exp_df_clean = exp_df[-influential, ]

# Step 5: Refit
model_clean = lm(log(y-1) ~ x, data = exp_df_clean)

# Step 6: Predict with clean model (on ALL x values, including removed points)
ycap_noexcl = 1 + exp(predict(model_clean, newdata = all_x_values))
```

### Important: Two Sets of Predictions
- `ycap`: Predictions from the INITIAL model (before influential point removal)
- `ycap_noexcl`: Predictions from the REFITTED model (after removal)
- **`ycap_noexcl` is what gets used downstream** in the iteration algorithm

### Influential Points Data
The system stores which points were flagged as influential for each curve:
```
influential_points_data columns:
  dev_len, Initial_Selection,
  influential_point_exp_fit,      # "Y" = influential, "N" = not, "Not used in curve fit" = excluded
  influential_point_weibull_fit,
  influential_point_power_fit,
  influential_point_ipc_fit
```

## R² (R-Squared) Values

Each curve's fit quality is measured by R²:
```r
r_sq = summary(model)$r.squared
```

R² ranges from 0 to 1. Higher = better fit.

The four R² values are sorted in descending order:
```r
r_sq_data = arrange(r_sq_data, desc(R_Squared))
```

This ranking determines which curves are preferred in the iteration algorithm:
- Top-ranked curve is tried first for replacements
- Initially only top 2 curves are used; if no iteration converges, all 4 are used

## Handling Edge Cases

After curve fitting, any `NaN` values in predictions are replaced with 1:
```r
data = mutate(data,
  Exponential_Decay = ifelse(is.nan(Exponential_Decay), 1, Exponential_Decay),
  Inverse_Power = ifelse(is.nan(Inverse_Power), 1, Inverse_Power),
  Power = ifelse(is.nan(Power), 1, Power),
  Weibull = ifelse(is.nan(Weibull), 1, Weibull)
)
```

This can happen when:
- Too few data points for fitting (< 2)
- All data points are identical (R² undefined)
- Log transformation produces invalid values

## Output Data Structure

The `data` dataframe (one row per development period):
```
| dev_qtr | dev_len | Initial_Selection | Exponential_Decay | Inverse_Power | Power | Weibull |
|---------|---------|-------------------|-------------------|---------------|-------|---------|
| 1       | 3       | 1.500             | 1.480             | 1.520         | 1.470 | 1.510   |
| 2       | 6       | 1.200             | 1.210             | 1.195         | 1.220 | 1.190   |
| 3       | 9       | 1.080             | 1.090             | 1.075         | 1.095 | 1.082   |
| ...     | ...     | ...               | ...               | ...           | ...   | ...     |
```

## Processing Flow

```
Initial VW Selections (y1)
        │
        ├───→ exponentialfunc(y1, sml_flag) ──→ {exp_df, exp_rsq, influential_points}
        ├───→ weibullfunc(y1, sml_flag)    ──→ {wbl_df, wbl_rsq, influential_points}
        ├───→ powerfunc(y1, sml_flag)      ──→ {pow_df, pow_rsq, influential_points}
        └───→ IPCfunc(y1, sml_flag)        ──→ {IPC_df, IPC_rsq, influential_points}
                │
                ▼
        Combined into `data` dataframe (all 4 curves + initial selection)
        R² values sorted descending into `r_sq_data`
                │
                ▼
        Fed into Iteration Algorithm (doc 06)
```
