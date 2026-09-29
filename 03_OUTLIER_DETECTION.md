# Outlier Detection (Adjusted Boxplot Method)

## What are Age-to-Age Factors?

Also called Loss Development Factors (LDFs). For a given exposure year and development period, the age-to-age factor is:

```
age_to_age = Cumulative_Incurred(dev_len + 1) / Cumulative_Incurred(dev_len)
```

Example: If cumulative incurred at dev period 6 is $800K and at dev period 9 is $950K:
```
age_to_age = 950,000 / 800,000 = 1.1875
```
This means claims grew by 18.75% from dev period 6 to 9.

## Why Detect Outliers?

Some age-to-age factors are anomalous -- a large single claim settling, a data correction, or unusual development. Including these distorts the volume-weighted averages. The system uses a robust statistical method to flag them.

## The Adjusted Boxplot Method -- Step by Step

From `MBR_weighted_average.R.txt`, function `fn_get_age_to_age_outliers()`:

### Step 1: Compute Age-to-Age Factors

```r
actuals_cum = mutate(actuals_cum, age_to_age = lead(Cumulative_Gross_Incurred) / Cumulative_Gross_Incurred)
actuals_cum = mutate(actuals_cum, age_to_age = ifelse(is.na(age_to_age)|is.nan(age_to_age)|is.infinite(age_to_age), 1, age_to_age))
```

- `lead()` gets the next row's value (next development period for the same exposure year)
- Edge cases (NA, NaN, Inf from division by zero) are set to 1

### Step 2: Remove Invalid Data

- Remove exposure years with total incurred <= 0 (no real claims)
- Remove last diagonal entries (no "next" period to compute factor)
- Remove exposure years with negative cumulative incurred

### Step 3: Compute Statistics Per Development Period

Group by `dev_len` and compute:

```r
dev_period_quartiles_df = actuals_cum %>% group_by(dev_len) %>% summarise(
    IQR_value = IQR(age_to_age),              # Interquartile Range = Q3 - Q1
    Q1_value  = quantile(age_to_age, 0.25),   # 25th percentile
    Q3_value  = quantile(age_to_age, 0.75),   # 75th percentile
    MC        = medcouple(age_to_age),         # Medcouple (robust skewness)
    Skewness  = skewness(age_to_age)           # Classical skewness
)
```

**Medcouple (MC)**: A robust measure of skewness from the `robustbase` package. It ranges from -1 to 1. Positive MC means right-skewed. It is more robust than classical skewness because it is based on medians, not means. The code caps MC at [-0.5, 0.5]:

```r
MC = ifelse(MC < -0.5, -0.5, ifelse(MC > 0.5, 0.5, MC))
```

### Step 4: Compute Adjusted Outlier Bounds

```
Min_Range = Q1 - 3 * exp(-Skewness * |MC|) * IQR
Max_Range = Q3 + 3 * exp( Skewness *  MC ) * IQR
```

When IQR = 0 (all values identical): `Min_Range = 0.95 * Q1`, `Max_Range = 1.05 * Q3`

The exponential adjustments account for skewness:

- For right-skewed data (positive Skewness, positive MC): the upper bound is widened more than standard, the lower bound is tightened
- For left-skewed data: opposite behavior
- The factor of 3 (instead of the standard 1.5 in regular boxplots) makes this more permissive

### Step 5: Flag Outliers

```r
outlier_flag = ifelse(age_to_age < Min_Range | age_to_age > Max_Range, 1, 0)
```

### Step 6: Determine Outlier Detection Range

Outlier detection only applies to development periods where at least `outlier_detection_min_points` (5) data points exist:

```r
dev_len_ratios_count = actuals_cum %>% group_by(dev_len) %>% summarise(count = n())
outlier_detection_last_dev_month = max dev_len where count >= 5
```

Beyond this development period, outlier_flag defaults to 0 (not flagged).

## Worked Example

Consider age-to-age factors at dev_len = 6 for 7 exposure years:

```
Exp Year    Age-to-Age Factor
2019        1.25
2020        1.18
2021        1.22
2022        1.20
2023        3.50  <- Anomalous (large claim settled)
2024        1.15
2025        1.19
```

**Statistics:**

- Q1 = 1.18, Q3 = 1.25, IQR = 0.07
- Medcouple MC = 0.3 (right-skewed due to outlier), capped at 0.3
- Skewness = 2.5

**Bounds:**

- Min = 1.18 - 3 * exp(-2.5 * 0.3) * 0.07 = 1.18 - 3 * 0.472 * 0.07 = 1.18 - 0.099 = **1.081**
- Max = 1.25 + 3 * exp(2.5 * 0.3) * 0.07 = 1.25 + 3 * 2.117 * 0.07 = 1.25 + 0.445 = **1.695**

**Result:** The 3.50 factor (2023) is flagged as an outlier. All others fall within [1.081, 1.695].
