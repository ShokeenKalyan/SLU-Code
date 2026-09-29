
# =============================================================================
# FILE: MBR_iteration_weighted_rmse_sml.R
#
# PURPOSE:
#   This file answers two important "which is best?" questions using a
#   statistical scoring method called Weighted RMSE.
#
#   QUESTION 1 (calc_VW_Averages_weighted_RMSE):
#     "How many years of history should we average to get our initial LDFs?"
#     Tests n = 3, 4, 5, ... years and scores each. Lower RMSE = better fit.
#
#   QUESTION 2 (calc_weighted_RMSE):
#     "Which of the many converged LDF sequences from the iteration algorithm
#     is the best one to use for reserving?"
#     Scores each converged iteration. Lower RMSE = better.
#
#   WHAT IS RMSE?
#   Root Mean Squared Error — a measure of how wrong your predictions are.
#   RMSE = sqrt( average of (actual - predicted)^2 )
#   Smaller = predictions are closer to actual values = better fit.
#
#   WHAT IS WEIGHTED RMSE?
#   Not all development periods matter equally. Errors in EARLY development
#   periods (where most claims are still unreported) have a bigger impact
#   on the final reserve estimate than errors in LATE periods.
#   So we weight each period's RMSE by how much development is still to come:
#     weight = |1 - Cum_Percentages|
#   A period at 30% development has weight 0.70 (a lot still to happen).
#   A period at 95% development has weight 0.05 (almost fully settled).
#
# FUNCTIONS IN THIS FILE:
#   1. calc_VW_Averages_weighted_RMSE() — scores each VW-n candidate
#   2. calc_weighted_RMSE()             — scores each converged iteration
#   3. filter_list()                    — helper to extract converged iterations
# =============================================================================



# =============================================================================
# FUNCTION 1: calc_VW_Averages_weighted_RMSE()
#
# PURPOSE:
#   For a given VW averaging period n (e.g. n=5 means "use last 5 years"),
#   compute how well those VW average LDFs fit the actual age-to-age factors
#   in the triangle. This is a "back-test": how well would these averages
#   have predicted the actual development history?
#
# CALLED FROM: SLU_main_code.R, once per candidate n value per profile.
#   Example: called 9 times for a Medium-tailed profile (n ∈ {3,4,5,6,7,8,9,10,24})
#
# PARAMETERS:
#   VW_Averages_period_list — a list containing:
#     $Period           — the n value being tested (e.g. 5)
#     $VW_Averages_matrix — the n-period VW average LDF vector
#   profile_id_analyzed — the insurance product being processed
#   age_to_age_outliers — data frame of all actual age-to-age factors
#                         (with outlier_flag column to exclude bad points)
#   sml_flag            — "S", "M", or "L" (Short/Medium/Long-tailed)
#
# RETURNS: a list with 6 items:
#   weighted_rmse       — overall weighted RMSE (including all dev periods)
#   Factors_df          — the LDF/CDF/Cum_Percentages data for this n
#   weighted_rmse_excl1 — weighted RMSE excluding the 1st dev period
#   weighted_rmse_excl2 — weighted RMSE excluding first 2 dev periods
#   weighted_rmse_excl3 — weighted RMSE excluding first 3 dev periods
#   weighted_rmse_excl4 — weighted RMSE excluding first 4 dev periods
#
#   NOTE: The SELECTION of best n is done using weighted_rmse_excl1 (not the
#   overall weighted_rmse). The first development period is often noisy
#   (e.g. large initial case reserve postings), so excluding it gives a
#   more stable selection.
# =============================================================================

calc_VW_Averages_weighted_RMSE = function(VW_Averages_period_list, profile_id_analyzed, age_to_age_outliers, sml_flag) {

  # Extract the n value (how many years were averaged)
  VW_Average_period = VW_Averages_period_list$Period

  # Convert the VW averages matrix row to a data frame column
  VW_Averages_df = as.data.frame(t(VW_Averages_period_list$VW_Averages_matrix))

  # -------------------------------------------------------------------
  # LONG-TAILED (YY) ADJUSTMENT:
  # Long-tailed (L) profiles use annual triangles (dev periods: 12, 24, 36...).
  # The VW averages matrix is sized for the full YQ grid but only the first
  # years_analyzed rows are meaningful for YY. Trim the excess.
  # -------------------------------------------------------------------
  if (sml_flag == 'L') {
    VW_Averages_df = data.frame(V1 = VW_Averages_df[1:years_analyzed, ])
  }

  # -------------------------------------------------------------------
  # ADD DEVELOPMENT LENGTH COLUMN:
  # Assign the actual development period (in months) to each row.
  #
  # For YY (Long): dev_len comes from exp_year_dev_len mapping
  #   e.g. row 1 = 12 months, row 2 = 24 months, row 3 = 36 months...
  #
  # For YQ (Short/Medium): dev_len = row_index × 3
  #   e.g. row 1 = 3 months, row 2 = 6 months, row 3 = 9 months...
  # -------------------------------------------------------------------
  if (sml_flag == 'L') {
    VW_Averages_df$dev_len = exp_year_dev_len$max_dev_len
  } else {
    VW_Averages_df$dev_len = as.integer(rownames(VW_Averages_df)) * 3
  }

  # -------------------------------------------------------------------
  # BUILD FACTORS_DF: reverse order so it runs from shortest to longest.
  # Then compute Cumulative Development Factors (CDF) and Cum_Percentages.
  #
  # EXAMPLE:
  #   VW averages (short to long dev):  1.50, 1.20, 1.08, 1.02, 1.00
  #   After rev():                       1.00, 1.02, 1.08, 1.20, 1.50
  #   cumprod():  1.00, 1.02, 1.10, 1.32, 1.98  (CDF — multiply from right)
  #   1/CDF:      1.00, 0.98, 0.91, 0.76, 0.50  (Cum_Percentages — % developed)
  #
  # Cum_Percentages tells us: at dev period 3 months, 50% of losses are reported.
  # At dev period 15 months, 91% are reported. Etc.
  # -------------------------------------------------------------------
  Factors_df = data.frame(
    res_year    = analysis_year,
    res_qtr     = analysis_qtr,
    val_flag    = analysis_val_flag,
    profile_id  = profile_id_analyzed,
    dev_len     = rev(VW_Averages_df$dev_len),
    Incr_Factors = rev(VW_Averages_df$V1)
  )
  Factors_df$Cum_Factors    = cumprod(Factors_df$Incr_Factors)
  Factors_df$Cum_Percentages = 1 / Factors_df$Cum_Factors

  # -------------------------------------------------------------------
  # JOIN VW AVERAGES BACK TO ACTUAL AGE-TO-AGE FACTORS:
  # We need to compare our VW average LDF (the predicted value) against
  # the actual age-to-age factors observed in the historical triangle
  # (the actual values) to measure RMSE.
  # -------------------------------------------------------------------
  age_to_age_outliers = left_join(
    age_to_age_outliers,
    select(Factors_df, c("dev_len", "Incr_Factors", "Cum_Factors", "Cum_Percentages")),
    by = "dev_len"
  )

  # -------------------------------------------------------------------
  # FILTER TO VALID DATA POINTS:
  # Use the same exclusions that were applied when computing the VW averages,
  # so that the RMSE reflects the same data population used to build the LDFs.
  #
  # Excluded:
  #   - Outlier points (outlier_flag == 1) — anomalous factors (e.g. large claim)
  #   - Zero incurred points — can't compute age-to-age for zero periods
  # -------------------------------------------------------------------
  age_to_age_outliers = filter(age_to_age_outliers, outlier_flag == 0)
  age_to_age_outliers = arrange(age_to_age_outliers, dev_len, desc(exp_year))
  age_to_age_outliers = filter(age_to_age_outliers, Gross_Incurred != 0)
  age_to_age_outliers = arrange(age_to_age_outliers, dev_len, desc(exp_year))

  # -------------------------------------------------------------------
  # RESTRICT TO THE n MOST RECENT YEARS PER DEVELOPMENT PERIOD:
  # For VW-5 (n=5), the average only uses the 5 most recent exposure years
  # at each development period. For consistency, the RMSE should only
  # compare against those same 5 years.
  #
  # top_n(VW_Average_period) with desc(exp_year) picks the n most recent years.
  # -------------------------------------------------------------------
  exp_year_dev_len_cmbn_rmse = select(age_to_age_outliers, c(dev_len, exp_year)) %>%
    group_by(dev_len) %>%
    top_n(VW_Average_period)
  age_to_age_outliers = inner_join(age_to_age_outliers, exp_year_dev_len_cmbn_rmse, by = c("exp_year", "dev_len"))

  # -------------------------------------------------------------------
  # COMPUTE RMSE PER DEVELOPMENT PERIOD:
  # For each development period, compare the actual age-to-age factors
  # against the VW average (Incr_Factors) using RMSE.
  #
  # Example at dev_len = 6:
  #   Actual age-to-age factors (last 5 years): 1.18, 1.22, 1.20, 1.15, 1.19
  #   VW-5 average (Incr_Factors):              1.188
  #   dev_len_rmse = rmse([1.18, 1.22, 1.20, 1.15, 1.19], [1.188, 1.188, ...])
  #                = sqrt(mean((actuals - 1.188)^2)) = ~0.024
  # -------------------------------------------------------------------
  dev_len_rmse_df = age_to_age_outliers %>%
    group_by(dev_len) %>%
    summarise(dev_len_rmse = rmse(age_to_age, Incr_Factors))
  dev_len_rmse_df = left_join(dev_len_rmse_df, Factors_df, by = "dev_len")

  # -------------------------------------------------------------------
  # COMPUTE WEIGHTS:
  # Weight = |1 - Cum_Percentages| = proportion of losses yet to be developed.
  #
  # Example:
  #   dev 3 months:  Cum_Percentages = 0.30 → weight = 0.70  (70% still to come)
  #   dev 24 months: Cum_Percentages = 0.85 → weight = 0.15  (only 15% to come)
  #   dev 72 months: Cum_Percentages = 0.99 → weight = 0.01  (almost fully settled)
  #
  # Early periods get high weight because errors there materially affect the reserve.
  # Late periods get low weight because they barely move the ultimate.
  # -------------------------------------------------------------------
  dev_len_rmse_df$weights = abs(1 - dev_len_rmse_df$Cum_Percentages)

  # -------------------------------------------------------------------
  # COMPUTE WEIGHTED RMSE (all development periods):
  # weighted_rmse = sum(rmse_per_period × weight) / sum(weights)
  # If the result is NaN (e.g. all weights are 0), default to 1 (worst score).
  # -------------------------------------------------------------------
  weighted_rmse = dev_len_rmse_df %>%
    group_by() %>%
    summarise(weighted_rmse = sum(dev_len_rmse * weights) / sum(weights))
  weighted_rmse = as.data.frame(weighted_rmse)
  weighted_rmse$weighted_rmse = ifelse(is.nan(weighted_rmse$weighted_rmse), 1, weighted_rmse$weighted_rmse)


  # -------------------------------------------------------------------
  # WEIGHTED RMSE EXCLUDING EARLY PERIODS:
  # Computed separately for excl1 through excl4.
  # "excl1" = excluding the earliest (shortest) development period.
  # "excl2" = excluding the 2 shortest periods. Etc.
  #
  # WHY: The first development period is often highly variable/noisy
  # (initial claim reports, large case reserves posted immediately).
  # Excluding it often gives a more stable signal for n selection.
  #
  # SELECTION: The main code uses weighted_rmse_excl1 to pick the best n.
  #
  # slice_max(dev_len, n = nrow - 1): keeps all rows EXCEPT the one with
  # the smallest dev_len (i.e., removes the earliest period).
  # -------------------------------------------------------------------

  if (nrow(dev_len_rmse_df) > 2) {
    # Exclude first development period (keep all except smallest dev_len)
    weighted_rmse_excl1 = dev_len_rmse_df %>%
      slice_max(dev_len, n = nrow(dev_len_rmse_df) - 1) %>%
      group_by() %>%
      summarise(weighted_rmse_excl1 = sum(dev_len_rmse * weights) / sum(weights))
    weighted_rmse_excl1 = as.data.frame(weighted_rmse_excl1)
    weighted_rmse_excl1$weighted_rmse_excl1 = ifelse(is.nan(weighted_rmse_excl1$weighted_rmse_excl1), 1, weighted_rmse_excl1$weighted_rmse_excl1)
  } else {
    # Not enough periods to exclude any — default to 1 (worst score, won't be selected)
    weighted_rmse_excl1 = data.frame(weighted_rmse_excl1 = 1)
  }

  if (nrow(dev_len_rmse_df) > 4) {
    # Exclude first 2 development periods
    weighted_rmse_excl2 = dev_len_rmse_df %>%
      slice_max(dev_len, n = nrow(dev_len_rmse_df) - 2) %>%
      group_by() %>%
      summarise(weighted_rmse_excl2 = sum(dev_len_rmse * weights) / sum(weights))
    weighted_rmse_excl2 = as.data.frame(weighted_rmse_excl2)
    weighted_rmse_excl2$weighted_rmse_excl2 = ifelse(is.nan(weighted_rmse_excl2$weighted_rmse_excl2), 1, weighted_rmse_excl2$weighted_rmse_excl2)

    # Exclude first 3 development periods
    weighted_rmse_excl3 = dev_len_rmse_df %>%
      slice_max(dev_len, n = nrow(dev_len_rmse_df) - 3) %>%
      group_by() %>%
      summarise(weighted_rmse_excl3 = sum(dev_len_rmse * weights) / sum(weights))
    weighted_rmse_excl3 = as.data.frame(weighted_rmse_excl3)
    weighted_rmse_excl3$weighted_rmse_excl3 = ifelse(is.nan(weighted_rmse_excl3$weighted_rmse_excl3), 1, weighted_rmse_excl3$weighted_rmse_excl3)

    # Exclude first 4 development periods
    weighted_rmse_excl4 = dev_len_rmse_df %>%
      slice_max(dev_len, n = nrow(dev_len_rmse_df) - 4) %>%
      group_by() %>%
      summarise(weighted_rmse_excl4 = sum(dev_len_rmse * weights) / sum(weights))
    weighted_rmse_excl4 = as.data.frame(weighted_rmse_excl4)
    weighted_rmse_excl4$weighted_rmse_excl4 = ifelse(is.nan(weighted_rmse_excl4$weighted_rmse_excl4), 1, weighted_rmse_excl4$weighted_rmse_excl4)

  } else {
    # Not enough periods to compute excl2/3/4 meaningfully
    weighted_rmse_excl2 = data.frame(weighted_rmse_excl2 = 1)
    weighted_rmse_excl3 = data.frame(weighted_rmse_excl3 = 1)
    weighted_rmse_excl4 = data.frame(weighted_rmse_excl4 = 1)
  }

  # Return all 6 RMSE variants plus the underlying factors data
  results_list = list(
    weighted_rmse       = weighted_rmse,
    Factors_df          = Factors_df,
    weighted_rmse_excl1 = weighted_rmse_excl1,
    weighted_rmse_excl2 = weighted_rmse_excl2,
    weighted_rmse_excl3 = weighted_rmse_excl3,
    weighted_rmse_excl4 = weighted_rmse_excl4
  )

  return(results_list)
}




# =============================================================================
# FUNCTION 2: calc_weighted_RMSE()
#
# PURPOSE:
#   After the iteration algorithm produces many converged LDF sequences,
#   this function scores each one to find the BEST one to use for reserving.
#
#   HOW IT SCORES:
#   For a given LDF sequence, it computes what the ultimate loss would be
#   for each exposure year (using the chain ladder / DFM method). Then it
#   checks: does the actual incurred-to-ultimate ratio match the cumulative
#   percentage predicted by these LDFs?
#
#   INTUITION:
#   If our LDFs say that at 12 months, 60% of losses are developed
#   (Cum_Percentages = 0.60), then for every exposure year at 12 months
#   development, the actual incurred should be ~60% of the projected ultimate.
#   Good LDFs → actual and predicted ratios are close → low RMSE.
#   Bad LDFs → ratios diverge → high RMSE.
#
# CALLED FROM: SLU_main_code.R, once per converged iteration.
#
# PARAMETERS:
#   converged_df           — one converged iteration (LDF vector as data frame)
#   inc_by_ay              — total incurred per exposure year (for building ultimates)
#   actuals_cum            — all actual cumulative incurred data (the full triangle)
#   profile_id_analyzed    — the insurance product being processed
#   sml_flag               — "S", "M", or "L"
#   max_non_zero_inc_year  — latest year with non-zero incurred (governs lookback)
#
# RETURNS: a list with:
#   weighted_rmse     — the scalar RMSE score (lower = better iteration)
#   dfm_ultimate      — exposure-year level DFM ultimates from this iteration
#   rmse_check        — diagnostic data frame (actuals vs predicted by dev period)
#   actuals_cum_rmse  — RMSE per development period
#   Factors_df        — CDF and Cum_Percentages from this iteration
# =============================================================================

calc_weighted_RMSE = function(converged_df, inc_by_ay, actuals_cum, profile_id_analyzed, sml_flag, max_non_zero_inc_year) {

  # -------------------------------------------------------------------
  # TRIM AND ASSIGN DEVELOPMENT LENGTHS:
  # Same logic as in calc_VW_Averages_weighted_RMSE — handle YY vs YQ.
  # -------------------------------------------------------------------
  if (sml_flag == 'L') {
    converged_df = converged_df[1:years_analyzed, ]   # trim to annual rows only
  }

  if (sml_flag == 'L') {
    converged_df$dev_len = exp_year_dev_len$max_dev_len   # annual: 12, 24, 36...
  } else {
    converged_df$dev_len = as.integer(rownames(converged_df)) * 3  # quarterly: 3, 6, 9...
  }

  # -------------------------------------------------------------------
  # BUILD FACTORS_DF: reverse and compute CDF and Cum_Percentages.
  # Same approach as in calc_VW_Averages_weighted_RMSE.
  # These Cum_Percentages are the "predicted" proportion developed at each period.
  # -------------------------------------------------------------------
  Factors_df = data.frame(
    res_year     = analysis_year,
    res_qtr      = analysis_qtr,
    val_flag     = analysis_val_flag,
    profile_id   = profile_id_analyzed,
    dev_len      = rev(converged_df$dev_len),
    Incr_Factors = rev(converged_df$Iteration_Values)
  )
  Factors_df$Cum_Factors    = cumprod(Factors_df$Incr_Factors)
  Factors_df$Cum_Percentages = 1 / Factors_df$Cum_Factors

  # -------------------------------------------------------------------
  # MATCH LDF PATTERN TO EACH EXPOSURE YEAR'S "DIAGONAL" POSITION:
  # Each exposure year is observed at a specific development period
  # (its diagonal — how many months since the exposure year started).
  # We need the CDF corresponding to THAT development period for each year.
  #
  # exp_year_dev_len maps: exposure year → max_dev_len (diagonal development period)
  # Example:
  #   2026 → dev_len 9 (only 9 months of data available)
  #   2025 → dev_len 21
  #   2020 → dev_len 81
  # -------------------------------------------------------------------
  Factors_YY = inner_join(Factors_df, exp_year_dev_len, by = c('dev_len' = 'max_dev_len'))

  # Build a per-exposure-year data frame with factors at the diagonal
  dfm_ultimate = select(Factors_YY, c(exp_year, dev_len, Incr_Factors, Cum_Factors, Cum_Percentages))
  dfm_ultimate = mutate(dfm_ultimate,
    res_year   = analysis_year,
    res_qtr    = analysis_qtr,
    val_flag   = analysis_val_flag,
    profile_id = profile_id_analyzed
  )
  dfm_ultimate = select(dfm_ultimate, c(res_year, res_qtr, val_flag, profile_id, exp_year, dev_len, Incr_Factors, Cum_Factors, Cum_Percentages))

  # -------------------------------------------------------------------
  # COMPUTE DFM ULTIMATE FOR EACH EXPOSURE YEAR:
  # DFM (Development Factor Method / Chain Ladder):
  #   Ultimate = Gross_Incurred × Cum_Factors
  #
  # Example:
  #   Exposure year 2023: Gross_Incurred = $5M, Cum_Factors = 1.25
  #   DFM Ultimate = $5M × 1.25 = $6.25M
  # -------------------------------------------------------------------
  dfm_ultimate = inner_join(dfm_ultimate, inc_by_ay, by = 'exp_year')
  dfm_ultimate$Ultimate = dfm_ultimate$Cum_Factors * dfm_ultimate$Gross_Incurred

  # -------------------------------------------------------------------
  # COMPUTE inc_to_ult (Incurred-to-Ultimate Ratio):
  # For each observation in the triangle, compute:
  #   inc_to_ult = Cumulative_Gross_Incurred / Ultimate
  #
  # This is the ACTUAL proportion developed at each observation point.
  # We'll compare this to Cum_Percentages (the PREDICTED proportion).
  #
  # Example:
  #   Exposure year 2021 at dev_len 12:
  #     Cumulative_Gross_Incurred = $3.2M
  #     Ultimate (from DFM above)  = $5.5M
  #     inc_to_ult = 3.2 / 5.5 = 0.582  (actual: 58.2% developed at 12 months)
  #     Cum_Percentages = 0.60           (predicted: 60% developed at 12 months)
  #     Error = |0.582 - 0.60| = 0.018
  # -------------------------------------------------------------------
  actuals_cum = inner_join(actuals_cum,
    select(dfm_ultimate, c("exp_year", "Ultimate")),
    by = 'exp_year'
  )
  actuals_cum = mutate(actuals_cum,
    inc_to_ult = ifelse(Ultimate == 0, 0, Cumulative_Gross_Incurred / Ultimate)
  )

  # Join the predicted Cum_Percentages to each observation
  actuals_cum = left_join(actuals_cum,
    select(Factors_df, c(dev_len, Cum_Percentages)),
    by = 'dev_len'
  )

  # Assemble a diagnostic data frame for audit/export
  rmse_check = as.data.frame(actuals_cum)
  rmse_check = mutate(rmse_check, res_year = analysis_year, res_qtr = analysis_qtr, val_flag = analysis_val_flag)
  rmse_check = select(rmse_check, c(res_year, res_qtr, val_flag, profile_id, exp_year, dev_len,
                                    Gross_Incurred, lower_tri_cmbn, Cumulative_Gross_Incurred,
                                    Ultimate, inc_to_ult, Cum_Percentages))

  # -------------------------------------------------------------------
  # APPLY SML LOOKBACK WINDOW:
  # Only use exposure years within the SML-appropriate lookback.
  # Older years are less relevant and could distort the RMSE.
  #
  # S (Short):  keep last 10 years, capped at 14 from analysis_year
  # M (Medium): keep last 14 years, capped at 14
  # L (Long):   keep last 24 years, capped at 14
  # -------------------------------------------------------------------
  dev_row_count_adj = 9 - 3 * analysis_qtr   # index adjustment for number of obs per period

  if (sml_flag == 'L') {
    oldest_year = max(max_non_zero_inc_year - years_analyzed_L_tailed + 1, analysis_year - years_capped + 1)
    actuals_cum = filter(actuals_cum, exp_year >= oldest_year)
  } else if (sml_flag == 'S') {
    oldest_year = max(max_non_zero_inc_year - years_analyzed_S_tailed + 1, analysis_year - years_capped + 1)
    actuals_cum = filter(actuals_cum, exp_year >= oldest_year)
  } else {   # sml_flag == 'M'
    oldest_year = max(max_non_zero_inc_year - years_analyzed_M_tailed + 1, analysis_year - years_capped + 1)
    actuals_cum = filter(actuals_cum, exp_year >= oldest_year)
  }

  # -------------------------------------------------------------------
  # COMPUTE RMSE PER DEVELOPMENT PERIOD:
  # For each dev_len, compare inc_to_ult (actual %) vs Cum_Percentages (predicted %).
  # rmse(actual, predicted) = sqrt(mean((actual - predicted)^2))
  # -------------------------------------------------------------------
  actuals_cum_rmse = actuals_cum %>%
    group_by(dev_len) %>%
    summarise(RMSE = rmse(inc_to_ult, Cum_Percentages))

  actuals_cum_rmse = as.data.frame(actuals_cum_rmse)
  actuals_cum_rmse = left_join(actuals_cum_rmse,
    select(Factors_df, c(dev_len, Cum_Percentages)),
    by = "dev_len"
  )

  # -------------------------------------------------------------------
  # COMPUTE WEIGHTS (same logic as in calc_VW_Averages_weighted_RMSE):
  # weight = |1 - Cum_Percentages|
  # Early periods (less developed) get higher weight because they affect
  # the reserve estimate more.
  # -------------------------------------------------------------------
  actuals_cum_rmse$weights = abs(1 - actuals_cum_rmse$Cum_Percentages)
  actuals_cum_rmse = as.data.frame(actuals_cum_rmse)

  # -------------------------------------------------------------------
  # FINAL WEIGHTED RMSE:
  # weighted_rmse = sum(RMSE_per_period × weight) / sum(weights)
  #
  # This is the SINGLE NUMBER used to rank all converged iterations.
  # The iteration with the LOWEST weighted_rmse is selected as the best.
  #
  # If NaN (e.g. all ultimates are zero), default to 1 to avoid selection.
  # -------------------------------------------------------------------
  weighted_rmse = actuals_cum_rmse %>%
    group_by() %>%
    summarise(weighted_rmse = sum(RMSE * weights) / sum(weights))
  weighted_rmse = as.data.frame(weighted_rmse)
  weighted_rmse$weighted_rmse = ifelse(is.nan(weighted_rmse$weighted_rmse), 1, weighted_rmse$weighted_rmse)

  results_list = list(
    weighted_rmse    = weighted_rmse,
    dfm_ultimate     = dfm_ultimate,
    rmse_check       = rmse_check,
    actuals_cum_rmse = actuals_cum_rmse,
    Factors_df       = Factors_df
  )

  return(results_list)
}




# =============================================================================
# FUNCTION 3: filter_list()
#
# PURPOSE:
#   A small helper function used with sapply() to extract only the CONVERGED
#   iterations from the full iterations_list.
#
#   The iteration algorithm stores every attempted sequence (converged and not).
#   Before scoring with calc_weighted_RMSE(), we filter to only converged ones
#   (Convergence == 1).
#
# USAGE IN MAIN CODE:
#   converged_flags = sapply(iterations_list_final, filter_list)
#   converged_list  = iterations_list_final[converged_flags]
#
# RETURNS: TRUE if this iteration converged, FALSE if it's a dead end.
# =============================================================================

filter_list = function(x) {
  if (x$Convergence[1] == 1)
    return(TRUE)    # this iteration is valid — include it
  else
    return(FALSE)   # this iteration failed to converge — exclude it
}
