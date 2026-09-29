# Actuarial Methods — Computing Ultimate Loss Estimates

## Overview

After selecting the best development pattern (from the iteration algorithm), MBR computes ultimate loss estimates using four different actuarial methods. Each uses the same development pattern but incorporates different assumptions.

**Ultimate Loss** = the total amount an insurer expects to eventually pay on claims from a given exposure year, including amounts not yet reported or settled.

**IBNR** = Ultimate Loss - Current Incurred = the reserve needed for future development.

## Method 1: DFM (Development Factor Method / Chain Ladder)

The simplest and most fundamental method. Already computed during iteration selection.

**Formula:**
```
Ultimate = Gross_Incurred × Cum_Factor
         = Gross_Incurred / Cum_Percentages
```

**Assumptions:**
- Past development patterns will continue unchanged
- No external information needed beyond the triangle data

**Best for:** Well-developed exposure years (Cum_Percentages close to 1) where the pattern is reliable.

**Example:**
```
Gross_Incurred = $6,000,000
Cum_Percentages = 0.75 (75% developed)
Cum_Factor = 1/0.75 = 1.333

DFM Ultimate = $6,000,000 × 1.333 = $8,000,000
IBNR = $8,000,000 - $6,000,000 = $2,000,000
```

## Method 2: BF (Bornhuetter-Ferguson)

Blends actual development data with an a priori (expected) loss ratio. Gives less weight to actual data for immature years.

From `MBR_actuarial_method_ultimates.R.txt`, function `calc_BF_Inc_Loss()`:

**Formula:**
```
BF_IELR_modified = BF_IELR × (PAI / LTI)

BF Ultimate = Gross_Incurred + (1 - Cum_Percentages) × Premium × BF_IELR_modified
```

**Where:**
- `BF_IELR` = Initial Expected Loss Ratio (from Vena — actuary's expectation)
- `PAI` = Premium Adjustment Index (trends premium to a common level)
- `LTI` = Loss Trend Index (trends losses to a common level)
- The `PAI/LTI` ratio adjusts the IELR for premium and loss trends

**Intuition:** The unreported portion `(1 - Cum_Percentages)` is estimated using the expected loss ratio rather than projecting from actual data. For a 25% undeveloped year, BF adds 25% × Premium × Expected_LR.

**Example:**
```
Gross_Incurred = $6,000,000
Cum_Percentages = 0.75
Premium = $10,000,000
BF_IELR = 0.65, PAI = 1.02, LTI = 1.03
BF_IELR_modified = 0.65 × (1.02/1.03) = 0.6437

BF Ultimate = $6,000,000 + (1-0.75) × $10,000,000 × 0.6437
            = $6,000,000 + $1,609,250
            = $7,609,250
```

## Method 3: CC (Cape Cod)

Similar to BF, but derives its expected loss ratio FROM THE DATA rather than using an external assumption.

From `calc_cc_IELR()`:

**Step 1: Compute trended development loss ratio for each exposure year:**
```
trended_dev_LR = (Gross_Incurred × LTI) / (Premium × PAI × Cum_Percentages)
```

**Step 2: Weighted average across exposure years:**
```
weighted_avg_LR = Σ(trended_dev_LR × CC_Exp_weight) / Σ(CC_Exp_weight)
```
where `CC_Exp_weight` is an actuarial weight indicating how much each year should contribute.

**Step 3: De-trend back to each year's level:**
```
CC_detrended_LR = weighted_avg_LR × PAI / LTI
```

**Step 4: Compute ultimate (same structure as BF):**
```
CC Ultimate = Gross_Incurred + (1 - Cum_Percentages) × Premium × CC_detrended_LR
```

**Key Difference from BF:** BF uses an externally-set IELR; CC calculates its own from the data. CC is "self-correcting" — if actual experience is better/worse than expected, the CC LR adjusts.

## Method 4: LR (Loss Ratio)

Ignores actual development entirely and uses a selected loss ratio.

From `calc_LR_Ultimate()`:

**Formula:**
```
LR Ultimate = Premium × Selected_LR
```

**Where `Selected_LR`** comes from one of (controlled by `Selected_LR_Met` field):
- `BF_IELR_MBR` (the MBR-modified BF IELR)
- `Financial_Budget_LR` (from financial planning)
- `Actuarial_LR` (actuary-selected)
- `CC_detrended_LR` (Cape Cod derived)

**Best for:** Very immature years (current year, where development data is nearly meaningless).

**Example:**
```
Premium = $10,000,000
Selected_LR = 0.65 (from BF IELR)

LR Ultimate = $10,000,000 × 0.65 = $6,500,000
```

## Comparison of Methods

| Method | Uses Actual Development? | Uses External Assumptions? | Best For |
|--------|------------------------|---------------------------|----------|
| DFM | Fully | No | Well-developed years (≥85%) |
| BF | Partially | Yes (IELR) | Moderately developed years |
| CC | Partially | Partially (weights) | Moderately developed years |
| LR | No | Fully | Very immature years (≤40%) |

## Recovery Ratio Ultimates (Ceded)

For ceded (reinsurance) calculations, `calc_RR_All_Ultimates()` computes:
```
premium_rr_ultimate  = Gross_Incurred + (Gross_Ultimate - Gross_Incurred) × Premium_Recovery_Ratio
incurred_rr_ultimate = Gross_Incurred + (Gross_Ultimate - Gross_Incurred) × Incurred_Recovery_Ratio
paid_rr_ultimate     = Gross_Incurred + (Gross_Ultimate - Gross_Incurred) × Paid_Recovery_Ratio
```

Where Recovery Ratios are the historical proportion of gross amounts recovered through reinsurance.
