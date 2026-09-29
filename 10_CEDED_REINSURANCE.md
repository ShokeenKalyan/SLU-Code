# Ceded / Reinsurance Calculations

## What is Reinsurance?

Insurance companies buy **reinsurance** — insurance for insurers — to transfer a portion of their risk to reinsurance companies.

**Key terms:**
- **Gross**: Total claims before any reinsurance
- **Ceded**: The portion of claims transferred to reinsurers
- **Net**: Gross minus Ceded (what the insurer retains)
- **Ri_type**: Reinsurance type identifier (Gross, or various ceded categories like quota share, excess of loss, etc.)

## How Ceded Processing Works in MBR

Ceded calculations happen AFTER the full gross processing. The key insight: **ceded development patterns mirror the gross pattern**, because reinsurance typically responds to the same underlying claims.

### Step 1: Replicate Gross Results for All Ri_types

```r
# fn_replicate_ri_type_df(): Cross-joins gross result with reinsurance type list
result_list_All = lapply(result_list, fn_replicate_ri_type_df, ri_type_df = list_ri_type)
```

This creates copies of every gross result dataframe for each reinsurance type, using a cross-join (every gross row × every Ri_type).

### Step 2: Compute Ceded Age-to-Age Factors

Ceded age-to-age factors are computed from actual ceded cumulative incurred data (not derived from gross):
```r
actuals_cum = filter(actuals_cum_Global, profile_id==profile_id_analyzed, Ri_type!='Gross')
actuals_cum = mutate(actuals_cum, age_to_age = lead(Cumulative_Gross_Incurred)/Cumulative_Gross_Incurred)
```

Note: No outlier detection is performed on ceded data (outlier_flag = 0 for all ceded rows).

### Step 3: Compute Ceded Ultimates

Ceded ultimates use the **same development pattern** (Cum_Percentages) from gross, but with ceded-specific actual incurred amounts:

```r
# DFM Ultimate for ceded
best_iter_res_df$Ultimate = best_iter_res_df$Gross_Incurred / best_iter_res_df$Cum_Percentages
```

BF and CC are also computed with ceded-specific Vena inputs (premium, IELR, etc.).

### Recovery Ratio Ultimates
From `calc_RR_All_Ultimates()`:
```
premium_rr_ultimate  = Ceded_Incurred + (Gross_Selected_Ultimate - Gross_Incurred) × Premium_Recovery_Ratio
incurred_rr_ultimate = Ceded_Incurred + (Gross_Selected_Ultimate - Gross_Incurred) × Incurred_Recovery_Ratio
paid_rr_ultimate     = Ceded_Incurred + (Gross_Selected_Ultimate - Gross_Incurred) × Paid_Recovery_Ratio
```

Recovery Ratios represent the historical proportion of gross IBNR recovered from reinsurance.

### Step 4: Ceded Method Selection

Different from gross method selection. Uses simpler rules (from main code ~lines 3786-3803):

```
pattern_threshold = 0.3

For each ceded exposure year:
  IF exp_year == analysis_year:
    → LR_Ultimate
  ELSE IF Cum_Percentages > 0.3:
    → Incurred_RR_Ultimate
  ELSE (Cum_Percentages ≤ 0.3):
    → Premium_RR_Ultimate
```

### Step 5: Filter Valid Ceded Profiles

`fn_apply_non_val_ceded_map()` removes invalid profile/Ri_type combinations:
```r
df = left_join(df, ceded_profile_mapping, by=c("profile_id"="Product", "Ri_type"))
df = filter(df, is_valid_ceded == 1)
```

The `ceded_profile_mapping` table controls which combinations are valid.

### Gross-Only Mode
When `Ri_type_run == 'Gross'`, ceded calculations are skipped entirely. Dummy columns (Paid_RR, Incurred_RR, Premium_RR = 0) are added for consistent output structure.
