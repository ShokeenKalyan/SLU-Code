# Analysis: Actuarial Methods, Method Selection & Threshold RMSE

This document provides an exhaustive analysis of three interconnected R files that handle the computation of actuarial reserve ultimates, automatic method selection per exposure year, and upper-triangle weighted RMSE calculation used to evaluate how well selected ultimates reconstruct the historical loss triangle.

---

## Table of Contents

1. [File 1: MBR_actuarial_method_ultimates.R](#file-1-mbr_actuarial_method_ultimatesr)
   - [calc_BF_Inc_Loss](#1-calc_bf_inc_loss)
   - [calc_cc_IELR (Gross)](#2-calc_cc_ielr-gross)
   - [calc_cc_IELR_ceded](#3-calc_cc_ielr_ceded)
   - [calc_LR_Ultimate](#4-calc_lr_ultimate)
   - [calc_RR_All_Ultimates](#5-calc_rr_all_ultimates)
2. [File 2: MBR_method_selection_by_exposure_year_cc_change.R](#file-2-mbr_method_selection_by_exposure_year_cc_changer)
   - [get_valid_methods](#1-get_valid_methods)
   - [fn_select_ultimate_by_exp_year](#2-fn_select_ultimate_by_exp_year)
3. [File 3: MBR_threshold_ultimate_weighted_RMSE.R](#file-3-mbr_threshold_ultimate_weighted_rmser)
   - [calc_upper_tri_rmse](#1-calc_upper_tri_rmse)
4. [How These Three Files Interact](#how-these-three-files-interact)
5. [Glossary of Key Terms](#glossary-of-key-terms)

---

## File 1: MBR_actuarial_method_ultimates.R

**Purpose:** Contains functions to recalculate loss ultimates under four standard actuarial methods — Bornhuetter-Ferguson (BF), Cape Cod (CC), Loss Ratio (LR), and Recovery Ratio (RR) — using MBR-selected development patterns and assumptions imported from Vena.

### 1. `calc_BF_Inc_Loss`

**What it does (business):** Calculates the **Bornhuetter-Ferguson Incurred Loss Ultimate** for each exposure year. BF blends the actual reported loss experience with an a-priori expected loss derived from premium and an expected loss ratio.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `d` | data.frame | One profile's data with columns: `exp_year`, `BF_IELR`, `Financial_Budget_LR`, `PAI`, `LTI`, `Gross_Incurred`, `Cum_Percentages`, `Premium` |

**Return:** Same data.frame `d` with two new columns: `BF_IELR_modified` and `BF_Ultimate`.

**Step-by-step logic:**

1. **Determine the current-year loss ratio (`cy_lr`):**
   ```
   IF BF_IELR for the current analysis year == 0:
       use Financial_Budget_LR for that year
   ELSE:
       use BF_IELR for that year
   ```
   This picks the best available a-priori loss ratio for the current year.

2. **Calculate `BF_IELR_modified` for every exposure year:**
   ```
   IF exp_year == analysis_year:
       BF_IELR_modified = cy_lr  (use the current year LR directly)
   ELSE IF LTI == 0:
       BF_IELR_modified = 0  (avoid division by zero)
   ELSE:
       BF_IELR_modified = cy_lr × PAI / LTI
   ```
   **Actuarial meaning:** For prior years, the current-year loss ratio is de-trended by adjusting for premium rate changes (PAI = Premium Adjustment Index) and loss inflation (LTI = Loss Trend Index). This makes the a-priori LR comparable across years.

3. **Clean up NaN/NA values:** Set any NaN or NA `BF_IELR_modified` to 0.

4. **Calculate BF Ultimate:**
   ```
   BF_Ultimate = Gross_Incurred + (1 - Cum_Percentages) × Premium × BF_IELR_modified
   ```

**Formula in mathematical notation:**

$$\text{BF\_Ultimate}_i = \text{Incurred}_i + (1 - \text{CumPct}_i) \times \text{Premium}_i \times \text{IELR}_i^{mod}$$

Where:
- `CumPct` = fraction of ultimate losses already reported (from MBR patterns)
- `(1 - CumPct)` = the unreported fraction — the part BF fills with expected losses
- The "expected" piece = Premium × IELR (expected loss ratio)

**Why this matters:** BF is preferred over pure chain-ladder (DFM) for immature years because it doesn't naively project small early incurred amounts. Instead it anchors on a reasonable a-priori loss ratio.

---

### 2. `calc_cc_IELR` (Gross)

**What it does (business):** Calculates the **Cape Cod (CC) Incurred Loss Ultimate**. Unlike BF which uses an external a-priori LR, Cape Cod derives the expected loss ratio from the triangle data itself via a weighted average of trended loss ratios.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `d` | data.frame | Profile data (same structure as BF, plus `CC_Exp_weight`, `Prev_Val_CC_Detrended_LR`) |
| `muf` | numeric | "Method Update Flag": 0 = use freshly computed CC LR; 1 = use prior-valuation CC LR |
| `sml_flag` | character | "S", "M", or "L" — controls how many years of data are used |

**Return:** `d` with new columns: `trended_dev_LR`, `CC_detrended_LR`, `CC_Ultimate`.

**Step-by-step logic:**

1. **Zero out exposure weights for years beyond the SML window:**
   - S (Short): zero weights for years older than `years_analyzed_S_tailed` (10 years)
   - M (Medium): zero weights for years older than `years_analyzed_M_tailed` (14 years)
   - L (Long): zero weights for years older than `years_analyzed_L_tailed` (24 years)

2. **Calculate trended development loss ratio for each year:**
   ```
   trended_dev_LR = (Gross_Incurred × LTI) / (Premium × PAI × Cum_Percentages)
   ```
   This adjusts each year's loss ratio to a common trend basis (current-year equivalent).

3. **Calculate the weighted CC factor (`fact`):**
   ```
   fact = Σ(trended_dev_LR × Premium × Cum_Percentages × PAI × CC_Exp_weight)
        / Σ(Premium × Cum_Percentages × PAI × CC_Exp_weight)
   ```
   This is a premium-and-maturity-weighted average of the trended LRs across years. Heavier weight goes to years with more premium and more developed data.

4. **De-trend the CC factor back to each year's basis:**
   ```
   CC_detrended_LR = (fact × PAI) / LTI
   For first development period (dev_len ≤ 12): CC_detrended_LR = fact  (no de-trending)
   ```

5. **Calculate CC Ultimate:**
   ```
   IF muf == 1 (use prior valuation):
       CC_Ultimate = Gross_Incurred + (1 - Cum_Percentages) × Premium × Prev_Val_CC_Detrended_LR
   ELSE (muf == 0, fresh calculation):
       CC_Ultimate = Gross_Incurred + (1 - Cum_Percentages) × Premium × CC_detrended_LR
   ```

**Key difference from BF:** BF uses an externally-supplied expected loss ratio; CC derives its own from the data. CC is thus more "self-correcting" but can be unstable with sparse data.

---

### 3. `calc_cc_IELR_ceded`

**What it does:** Identical logic to `calc_cc_IELR` but for **ceded** (reinsurance) triangles. The key difference is that the CC factor is computed **per RI type** (e.g., "Ceded CAP", "Ceded XL"), not globally.

**Additional logic over the gross version:**
```r
# Compute numerator/denominator per row
d$num = trended_dev_LR × Premium × Cum_Percentages × PAI × CC_Exp_weight
d$den = Premium × Cum_Percentages × PAI × CC_Exp_weight

# Group by Ri_type and compute separate facts
fact_df = d %>% group_by(Ri_type) %>% summarise(num=sum(num), den=sum(den))
fact_df$fact = num / den

# Join back so each row gets the factor for its own RI type
d = left_join(d, fact_df, by="Ri_type")
```

This allows each reinsurance type to have its own Cape Cod expected loss ratio, rather than mixing all ceded types into one average.

---

### 4. `calc_LR_Ultimate`

**What it does:** Calculates the **Loss Ratio Ultimate** — simply `LR × Premium` — but the LR to use depends on which loss ratio source is selected per year.

**Step-by-step logic:**

1. **For the current year, determine which LR method name to assign:**
   ```
   IF BF_IELR_modified ≠ 0 AND BF_IELR_modified ≠ Financial_Budget_LR:
       method = 'BF IELR MBR'
   ELSE:
       method = 'Financial Budget Loss'
   ```

2. **For all prior years:** Set method to `'BF IELR MBR'`.

3. **For each row, compute LR Ultimate based on the method name:**
   ```
   'BF IELR MBR'        → LR_Ultimate = BF_IELR_modified × Premium
   'Actuarial Loss'      → LR_Ultimate = Actuarial_LR × Premium
   'Financial Budget Loss' → LR_Ultimate = Financial_Budget_LR × Premium
   'Detrended LR (New)'  → LR_Ultimate = CC_detrended_LR × Premium
   Otherwise             → LR_Ultimate = 0
   ```

**Business meaning:** LR Ultimate is a "pure expectation" method — it ignores actual incurred entirely and relies solely on an a-priori loss ratio × premium. This is useful for the most immature years where incurred data is unreliable.

---

### 5. `calc_RR_All_Ultimates`

**What it does:** Calculates **Recovery Ratio Ultimates** for ceded business. Recovery ratios express the relationship between ceded IBNR and gross IBNR.

**Formulas:**
```
premium_rr_ultimate  = Gross_Incurred + IBNR × Premium_Recovery_Ratio
incurred_rr_ultimate = Gross_Incurred + IBNR × Incurred_Recovery_Ratio
paid_rr_ultimate     = Gross_Incurred + IBNR × Paid_Recovery_Ratio
```

Where `IBNR = gross IBNR` (from the gross calculation above).

It also recalculates `LR_Ultimate` for the ceded layer:
```
IF current year AND BF_IELR_modified == Financial_Budget_LR:
    LR_Ultimate = Gross_Incurred + Financial_Budget_LR × Premium
ELSE:
    LR_Ultimate = Gross_Incurred + BF_IELR_modified × Premium
```

**Business meaning:** For ceded lines, you often can't build meaningful development patterns (sparse/volatile data). So instead, you take the gross IBNR and apply a "recovery ratio" to estimate the ceded share.

---

## File 2: MBR_method_selection_by_exposure_year_cc_change.R

**Purpose:** This is the **method selection engine** — it decides, for each exposure year, which actuarial method's ultimate to use (DFM, BF, CC, or LR) based on rules and a hindsight RMSE analysis.

### 1. `get_valid_methods`

**What it does:** Checks which ultimate methods have valid inputs and should be included in the selection process.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `df` | data.frame | A data frame with columns `LR`, `BF`, `CC`, `DFM`, all initialized to 1 |
| `inputs_vena` | data.frame | Vena assumptions for the profile |

**Logic:**
```
IF current-year LR (BF IELR or Financial Budget) == 0:
    disable BF (set BF = 0)  — can't compute BF without a loss ratio

IF sum of all CC_Exp_weight == 0:
    disable CC (set CC = 0)  — can't compute CC without exposure weights
```

**Return:** Updated `df` with 0s for disabled methods. Example: `(LR=1, BF=0, CC=1, DFM=1)` means BF is not available.

---

### 2. `fn_select_ultimate_by_exp_year`

This is the **most complex and important function** in the entire method selection pipeline. It selects the best actuarial method per exposure year using a combination of hard rules and a hindsight RMSE simulation.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `ultimates_df` | data.frame | All calculated ultimates for the profile (DFM, BF, CC, LR) |
| `best_iter_result_list` | data.frame | Best iteration factors with per-year Cum_Percentages |
| `ultimate_methods_to_use` | data.frame | Which methods are valid (from `get_valid_methods`) |
| `actuals_cum` | data.frame | Cumulative incurred triangle |
| `max_non_zero_inc_year` | integer | Latest year with non-zero incurred |

**Return:** A list with:
- `selections_df`: Per-year selected method and ultimate
- `exp_year_simulate_rmse_df`: RMSE details for simulated years
- `exp_year_simulate_data_df`: Working data for the simulation

**Step-by-step logic:**

#### Step 1: Filter to relevant years
```
Keep only recent ~12 years (from max_non_zero_inc_year - 12)
AND years_capped hard cutoff (14 years)
AND only years with Cum_Percentages >= 50%
```

#### Step 2: Calculate average DFM ULR (Ultimate Loss Ratio)
```
For years with ≥ 50% developed AND non-zero incurred:
    DFM_ULR = DFM_Ultimate / Premium
    avg_dfm_ulr = sum(DFM_Ultimate) / sum(Premium)  (across qualifying years)
```

#### Step 3: Flag outlier years
```
For each year:
    IF DFM_ULR is between 0.5× and 1.5× avg_dfm_ulr → include in RMSE calc ('Y')
    ELSE → exclude ('N')
```
This removes exposure years whose loss ratios are extreme outliers that would distort the RMSE comparison.

#### Step 4: Apply hard rule-based selections
These are applied FIRST, before any RMSE simulation:

| Condition | Selected Method | Rationale |
|-----------|----------------|-----------|
| Cum_Percentages ≥ 85% | DFM_Ultimate | Highly mature — trust the actual development |
| exp_year ≤ oldest year in window | DFM_Ultimate | Very old year — incurred is essentially final |
| exp_year == analysis_year (current year) | LR_Ultimate | No development data yet — use pure loss ratio |
| Cum_Percentages ≤ 40% | LR_Ultimate | Very immature — incurred too unreliable |

Years that don't match any rule get `NA` (to be resolved by RMSE simulation).

#### Step 5: RMSE Hindsight Simulation
For each year still unassigned (`NA`), the code simulates: "If this year were at the same maturity as an older year, how well would each method have predicted the ultimate?"

**The simulation works as follows:**

For each simulated year `Y`:
1. Take all prior years that have actual data at `Y`'s development month
2. For each prior year, compute what each method would have predicted as ultimate at `Y`'s maturity level:
   ```
   DFM_Ultimate_at_Y_maturity = Cumulative_Incurred_at_Y_dev / Cum_Percentages_at_Y_maturity
   BF_Ultimate_at_Y_maturity  = Cumulative_Incurred_at_Y_dev + (1 - Cum_Pct) × Premium × BF_IELR
   CC_Ultimate_at_Y_maturity  = Cumulative_Incurred_at_Y_dev + (1 - Cum_Pct) × Premium × CC_LR
   ```
3. Compare each method's prediction against the **actual DFM ultimate** (the "answer key") using RMSE:
   ```
   DFM_RMSE = RMSE(DFM_Ultimate_actual, DFM_Ultimate_at_Y_maturity)
   BF_RMSE  = RMSE(DFM_Ultimate_actual, BF_Ultimate_at_Y_maturity)
   CC_RMSE  = RMSE(DFM_Ultimate_actual, CC_Ultimate_at_Y_maturity)
   ```
4. **Select the method with the lowest RMSE** for that exposure year

**Important nuance — maturity-based column selection:**
```
IF Cum_Percentages ≥ 50%: consider all available methods (DFM, BF, CC)
IF Cum_Percentages < 50%: exclude DFM from comparison (only BF and CC)
```
Because at low maturities, DFM is volatile and shouldn't be considered.

#### Step 6: DFM Monotonicity Override
```
If DFM is selected for any year, it must also be selected for all OLDER years
```
This enforces the principle that if DFM is reliable at a certain maturity, it should be even more reliable for years that are even more mature.

#### Step 7: Map RMSE names to ultimate names
```
DFM_RMSE → DFM_Ultimate
BF_RMSE  → BF_Ultimate  
CC_RMSE  → CC_Ultimate
```

#### Step 8: Assign selected ultimate values
```python
for each year:
    SelectedUltimate = ultimates_all_years_df[year, selectedMethod]
```

This looks up the actual ultimate value from the method that was selected.

#### Visual flow:

```
┌─────────────────────────────────────────────────────────┐
│                  For each exposure year                   │
├─────────────────────────────────────────────────────────┤
│  ≥85% developed? ──YES──→ DFM (trust actual data)       │
│  Very old year?  ──YES──→ DFM (essentially final)        │
│  Current year?   ──YES──→ LR  (no development yet)       │
│  ≤40% developed? ──YES──→ LR  (too immature for DFM)     │
│                                                          │
│  None of the above? ──→ RMSE Hindsight Simulation       │
│     │                                                    │
│     ├─ Calculate DFM, BF, CC predicted ultimates         │
│     │  using historical data at this year's maturity     │
│     │                                                    │
│     ├─ Compare predictions vs actual via RMSE            │
│     │                                                    │
│     └─ Select method with lowest RMSE                    │
│                                                          │
│  Enforce DFM monotonicity (older ≥ newer)                │
│                                                          │
│  Look up the actual ultimate value for selected method   │
└─────────────────────────────────────────────────────────┘
```

---

## File 3: MBR_threshold_ultimate_weighted_RMSE.R

**Purpose:** Validates a set of selected ultimates by back-calculating the upper triangle and measuring how well the back-calculated values match actual historical data, using a **diagonal-weighted RMSE**.

### 1. `calc_upper_tri_rmse`

**What it does (business):** Given selected ultimate losses for each exposure year, this function works backwards through the loss triangle to reconstruct what the incurred values "should have been" at each historical development point. It then compares these reconstructed values against actual values. A lower RMSE means the selected ultimates are more consistent with historical development patterns.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `SelectedUltimate_df` | data.frame | Selected ultimates per exposure year |
| `last_diagonal_df` | data.frame | (overwritten internally) — latest diagonal data |
| `actuals_cum` | data.frame | Cumulative incurred triangle |

**Return:** A list of three items:
1. `upper_tri_wtd_rmse` — the single weighted RMSE number
2. `rmse_df` — detailed comparison of actual vs calculated for each cell
3. `upper_tri_calc_df` — the full back-calculated upper triangle

**Step-by-step logic:**

#### Step 1: Extract the last diagonal
```r
last_diagonal_df = actuals_cum %>% group_by(exp_year) %>% 
                   top_n(n=4, wt=dev_len)
```
The "last diagonal" is the most recent 4 development periods available for each exposure year (i.e., the latest reported values).

#### Step 2: Separate the triangle
```
actuals_cum_wo_last_diagonal = actuals_cum MINUS last_diagonal_df
```
The "without last diagonal" portion is the historical part we'll try to reconstruct.

#### Step 3: Calculate cumulative factors
```
cum_factor = SelectedUltimate / Cumulative_Gross_Incurred_at_latest_dev
```
This tells us: "How much does the selected ultimate multiply the latest known incurred?"

#### Step 4: Back-calculate the upper triangle
Starting from the latest diagonal and working backwards:
```
For each development period i (from second-to-last down to 1):
    For each exposure year that has data at period i:
        back_calculated_value = next_period_calculated_value / cum_factor_at_this_dev
```

The logic chains backwards through the triangle: if you know the value at dev 48 and the factor from dev 45 to dev 48, you can infer what the value at dev 45 "should be."

#### Step 5: Calculate differences
```
Difference = Calculated_value - Actual_value
Squared_Difference = Difference²
```

#### Step 6: Assign diagonal numbers and weights
Each cell in the upper triangle belongs to a "diagonal" (cells with the same calendar period). The diagonal number is:
```
diagonal_num = (max_dev_len - dev_len) / 3 + 1
```
- Diagonal 1 = most recent (latest data, most reliable)
- Higher diagonals = further back in time

#### Step 7: Compute diagonal-specific RMSE
```
For each diagonal:
    RMSE = sqrt(sum(squared_differences) / count_of_observations)
    weight = 1 / count_of_observations
```

**Why weight by 1/n?** Diagonals closer to the last diagonal have fewer data points (they're near the edge of the triangle). This weighting ensures each diagonal has equal influence regardless of how many exposure years it covers.

#### Step 8: Compute final weighted RMSE
```
upper_tri_wtd_rmse = Σ(RMSE_diagonal × weight_diagonal) / Σ(weight_diagonal)
```

**Business meaning:** A low weighted RMSE means the selected ultimates produce a back-calculated triangle that closely matches what actually happened. This is used to:
- Compare different threshold sets to find the best one
- Validate that MBR's selections are reasonable

#### Visual representation of the back-calculation:

```
Upper Triangle (what we're reconstructing):

         Dev 3    Dev 6    Dev 9    Dev 12   Dev 15 (latest)
EY 2022:   ?        ?        ?        ?       KNOWN (diagonal)
EY 2023:   ?        ?        ?       KNOWN    
EY 2024:   ?        ?       KNOWN
EY 2025:   ?       KNOWN
EY 2026:  KNOWN

Starting from KNOWN values, divide by cum_factor to fill in "?" cells.
Then compare "?" reconstructed values against actual historical values.
```

---

## How These Three Files Interact

The main code (`SLU_main_code.R`) calls these in sequence:

```
1. calc_BF_Inc_Loss(...)          ← File 1: Compute BF ultimates
2. calc_cc_IELR(...)              ← File 1: Compute CC ultimates  
3. calc_LR_Ultimate(...)          ← File 1: Compute LR ultimates
4. get_valid_methods(...)         ← File 2: Check which methods have valid inputs
5. fn_select_ultimate_by_exp_year(...)  ← File 2: Select best method per year

   [For ceded business, additionally:]
6. calc_cc_IELR_ceded(...)        ← File 1: Ceded CC ultimates
7. calc_RR_All_Ultimates(...)     ← File 1: Recovery ratio ultimates
```

The DFM ultimate comes from the iteration algorithm (a separate file), not from this file. These functions compute the BF, CC, and LR alternatives, and then `fn_select_ultimate_by_exp_year` picks the best one per year.

`calc_upper_tri_rmse` (File 3) is not called in the current main flow's final path — it was used in an earlier version of the code to evaluate different threshold sets. It exists as a validation tool.

```
┌───────────────────┐     ┌─────────────────────┐
│ Iteration Algo    │     │ Vena Assumptions     │
│ (DFM factors)     │     │ (Premium, LR, trends)│
└────────┬──────────┘     └──────────┬───────────┘
         │                           │
         ▼                           ▼
┌─────────────────────────────────────────────┐
│          File 1: Method Ultimates           │
│  calc_BF_Inc_Loss → BF Ultimate             │
│  calc_cc_IELR     → CC Ultimate             │
│  calc_LR_Ultimate → LR Ultimate             │
│  (DFM Ultimate comes from iteration algo)   │
└────────────────────┬────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────┐
│      File 2: Method Selection Engine        │
│  get_valid_methods → which methods to use   │
│  fn_select_ultimate_by_exp_year →           │
│    rule-based + RMSE hindsight simulation   │
│    → Selected method per exposure year      │
│    → Selected Ultimate per exposure year    │
└────────────────────┬────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────┐
│   File 3: Upper Triangle Validation (opt.)  │
│  calc_upper_tri_rmse →                      │
│    back-calculate triangle from ultimates   │
│    compute diagonal-weighted RMSE           │
│    → quality score for the selection set    │
└─────────────────────────────────────────────┘
```

---

## Glossary of Key Terms

| Term | Meaning |
|------|---------|
| **Ultimate** | Total expected losses for an exposure year when all claims are finally settled |
| **IBNR** | Incurred But Not Reported — the difference between ultimate and currently reported losses |
| **DFM** | Development Factor Method (chain ladder) — projects ultimate by multiplying current incurred by cumulative development factors |
| **BF** | Bornhuetter-Ferguson — blends actual incurred with a-priori expected losses |
| **CC** | Cape Cod — like BF but derives the expected LR from the triangle data itself |
| **LR** | Loss Ratio method — ultimate = LR × Premium (ignores actual incurred) |
| **RR** | Recovery Ratio — estimates ceded IBNR as a fraction of gross IBNR |
| **Cum_Percentages** | Fraction of ultimate loss already reported (= 1/CDF) |
| **CDF** | Cumulative Development Factor |
| **IELR** | Initial Expected Loss Ratio |
| **PAI** | Premium Adjustment Index — adjusts for premium rate changes over time |
| **LTI** | Loss Trend Index — adjusts for loss inflation over time |
| **CC_Exp_weight** | Cape Cod Exposure Period Weight — weights years for the CC calculation |
| **SML_flag** | Short/Medium/Long tailed classification of the line of business |
| **RMSE** | Root Mean Squared Error — measures prediction accuracy |
| **Diagonal** | A set of cells in the triangle sharing the same calendar period |
| **Hindsight test** | Pretend a mature year is at an immature year's development stage and test how well methods would have predicted |
| **muf** | Method Update Flag — 0 means compute fresh CC LR; 1 means use prior valuation's CC LR |
| **exp_year** | Exposure year (= accident year in most contexts) |
| **dev_len** | Development length in months |
| **Upper triangle** | The portion of the loss triangle above the last diagonal (historical data) |
