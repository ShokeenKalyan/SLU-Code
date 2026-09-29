# Loss Development Triangles and SML Classification

## What is a Loss Development Triangle?

A loss triangle is a matrix showing how insurance claims evolve over time. Each row represents an **exposure year** (when policies were written or accidents occurred). Each column represents a **development period** (how much time has elapsed since the exposure year).

### Example: Incremental Loss Triangle
Shows the NEW incurred amount in each period:

```
              Dev Period:    3      6      9      12     15     18
Exposure Year:
2021                      500K   300K   150K    80K    40K    20K
2022                      600K   350K   180K    90K    50K
2023                      550K   320K   160K    85K
2024                      700K   400K   200K
2025                      650K   380K
2026                      580K
```

The diagonal (bottom-left to top-right) represents the most recent data available. Newer exposure years have fewer development periods observed.

### Example: Cumulative Loss Triangle
Shows the RUNNING TOTAL at each period:

```
              Dev Period:    3      6      9      12     15     18
Exposure Year:
2021                      500K   800K   950K  1030K  1070K  1090K
2022                      600K   950K  1130K  1220K  1270K
2023                      550K   870K  1030K  1115K
2024                      700K  1100K  1300K
2025                      650K  1030K
2026                      580K
```

The cumulative triangle is the basis for computing age-to-age factors (LDFs).

## YQ vs YY Triangles

### YQ (Year-Quarter) Triangles
- Development periods in **3-month increments**: 3, 6, 9, 12, 15, 18, ...
- Used for **Short-tailed** and **Medium-tailed** business lines
- More granular — captures quarterly development patterns
- `last_dev_period_index = 4 * years_analyzed - (4 - analysis_qtr)`
  - Example: years_analyzed=25, analysis_qtr=3 → index = 4*25 - 1 = 99

### YY (Year-Year) Triangles
- Development periods in **12-month increments**: 12, 24, 36, 48, ...
- Used for **Long-tailed** business lines
- Less granular but appropriate for slow-developing lines (e.g., asbestos, environmental)
- `last_dev_period_index = years_analyzed`
  - Example: years_analyzed=25 → index = 25

## SML Classification

Each insurance profile is classified as Short, Medium, or Long-tailed based on its **average claim duration** (how long it takes for claims to be fully settled).

| Classification | Duration | Years Analyzed | Triangle Type | VW Periods Tested |
|----------------|----------|---------------|---------------|-------------------|
| **S (Short)** | < 3 years | 10 years (`years_analyzed_S_tailed`) | YQ (quarterly) | n ∈ {3, 4, 5} |
| **M (Medium)** | 3–5 years | 14 years (`years_analyzed_M_tailed`) | YQ (quarterly) | n ∈ {3,4,5,6,7,8,9,10,24} |
| **L (Long)** | > 5 years | 24 years (`years_analyzed_L_tailed`) | YY (annual) | n ∈ {5,6,7,8,9,10,24} |

Additionally, `years_capped = 14` limits the maximum lookback from the analysis year, regardless of SML type.

### How SML Affects Processing
```
oldest_year calculation:
  S: oldest_year = max(max_non_zero_inc_year - 10 + 1, analysis_year - 14 + 1)
  M: oldest_year = max(max_non_zero_inc_year - 14 + 1, analysis_year - 14 + 1)
  L: oldest_year = analysis_year - 24 + 1
```

Data before `oldest_year` is zeroed out (Gross_Incurred set to 0).

## Triangle Construction in R

The code uses the **ChainLadder** R package:

```r
# Build incremental triangle from actuals data
triangle_incr = as.triangle(actuals_cl, origin="exp_year", dev="dev_len", value="Gross_Incurred")

# Convert incremental to cumulative
triangle_cum = incr2cum(triangle_incr, na.rm=TRUE)
```

### Key Data Structures

**`actuals_cl`** (incremental claims):
| profile_id | exp_year | dev_len | Gross_Incurred | Ri_type |
|------------|----------|---------|----------------|---------|
| ProductA   | 2020     | 3       | 500000         | Gross   |
| ProductA   | 2020     | 6       | 300000         | Gross   |
| ProductA   | 2021     | 3       | 600000         | Gross   |

**`actuals_cum`** (cumulative claims):
| profile_id | exp_year | dev_len | Gross_Incurred | Cumulative_Gross_Incurred | Ri_type |
|------------|----------|---------|----------------|--------------------------|---------|
| ProductA   | 2020     | 3       | 500000         | 500000                   | Gross   |
| ProductA   | 2020     | 6       | 300000         | 800000                   | Gross   |

### The exp_year_dev_len Concept

`exp_year_dev_len` maps each exposure year to its maximum available development period:

```
exp_year  max_dev_len
2002      99  (quarters: 3, 6, ..., 297)
2003      95
...
2025      6
2026      3   (only one quarter of data)
```

This reflects the "diagonal" of the triangle — newer years have less development data.

### Removing Negative Cumulative Incurred
Before processing, exposure years where cumulative incurred goes negative are removed from the triangle (but only if doing so doesn't remove ALL years):

```r
exp_year_negative_cum_inc = unique(filter(actuals_cum, Cumulative_Gross_Incurred < 0)['exp_year'])
if(nrow(exp_year_negative_cum_inc) < years_analyzed){
  triangle_cum_df = anti_join(triangle_cum_df, exp_year_negative_cum_inc, by='exp_year')
}
```

This is important because negative cumulative incurred produces invalid age-to-age factors.

## The Triangle as a Matrix

After construction, the triangle is stored as both:
1. A **ChainLadder triangle object** — for library functions
2. A **data frame** (`triangle_cum_df`) — for manual operations
3. A **matrix** (`triangle_cum_matrix`) — passed to the VW average function

The matrix form looks like (matching the ASCII triangle above):
```
        3     6     9     12    15    18
2021   500K  800K  950K  1030K 1070K 1090K
2022   600K  950K  1130K 1220K 1270K  NA
2023   550K  870K  1030K 1115K  NA    NA
...
```

`NA` values represent future (unobserved) cells in the lower-right of the triangle.
