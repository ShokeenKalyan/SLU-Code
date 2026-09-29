# Method Selection by Exposure Year

## Overview

After computing all four actuarial method ultimates (DFM, BF, CC, LR) for each exposure year, MBR selects the "best" method per year. The selection uses a combination of **rules** (for extreme cases) and **RMSE-based simulation** (for middle years).

Source: `MBR_method_selection_by_exposure_year_cc_change.R.txt`

## Step 1: Check Method Availability

`get_valid_methods()` checks if each method can be used:

```r
# BF disabled if no IELR data
if(all(inputs_vena$BF_IELR == 0, na.rm=TRUE) || all(is.na(inputs_vena$BF_IELR)))
  ultimate_methods_to_use$BF = 0

# CC disabled if no exposure weights
if(all(inputs_vena$CC_Exp_weight == 0, na.rm=TRUE) || all(is.na(inputs_vena$CC_Exp_weight)))
  ultimate_methods_to_use$CC = 0
```

DFM and LR are always available.

## Step 2: Rule-Based Selection

For certain exposure years, the method is determined by rules (no RMSE calculation needed):

| Condition | Selected Method | Rationale |
|-----------|----------------|-----------|
| `Cum_Percentages ≥ 0.85` | DFM | Year is ≥85% developed — actual data is highly reliable |
| `exp_year == analysis_year` | LR | Current year has minimal development — use expected LR |
| `Cum_Percentages ≤ 0.40` | LR | Year is ≤40% developed — too immature for DFM/BF/CC |
| Very old years (before threshold) | DFM | Fully developed — pattern already proven |

## Step 3: RMSE-Based Selection (Middle Years)

For exposure years that don't trigger any rule (moderately developed, not current year), MBR uses a **hindsight simulation**:

### The Simulation Logic

**Question:** "At this year's current development stage, which method would have predicted best historically?"

**Method:**
1. For each candidate method (DFM, BF, CC, LR):
   a. Look at what we know NOW for this exposure year (current incurred, current Cum_Percentages)
   b. Ask: "If we applied this method at an EARLIER development stage, what would it have predicted?"
   c. Compare the prediction to what actually happened
   d. Compute RMSE across simulated development stages

2. Select the method with the **lowest RMSE**

### Detailed Steps

```
For each exposure year (in the middle zone):
    For each available method (DFM, BF, CC, LR):
        For each earlier development stage:
            Simulate: what would this method's ultimate have been?
            Compare to: actual current development (incurred-to-ultimate ratio)
        Compute RMSE across all simulated stages
    
    Pick method with minimum RMSE → selectedMethod
    Use that method's ultimate → SelectedUltimate
```

## Output

For each exposure year, the result includes:
- `selectedMethod`: one of "DFM_Ultimate", "BF_Ultimate", "CC_Ultimate", "LR_Ultimate"
- `SelectedUltimate`: the dollar amount from the selected method
- RMSE values for each method (diagnostic)

### Summary CoU (Change of Ultimate)

The final output combines:
```
summary_CoU_df:
  profile_id | exp_year | Gross_Incurred | Cum_Percentages | Ultimate (DFM) | selectedMethod | SelectedUltimate
```

## Ceded Method Selection (Different Logic)

For ceded (reinsurance), method selection follows simpler rules (from main code lines ~3786-3803):
- `pattern_threshold = 0.3`
- If `exp_year == analysis_year` → LR_Ultimate
- If `Cum_Percentages > 0.3` → Incurred_RR_Ultimate (recovery ratio based on incurred)
- If `Cum_Percentages ≤ 0.3` → Premium_RR_Ultimate (recovery ratio based on premium)
