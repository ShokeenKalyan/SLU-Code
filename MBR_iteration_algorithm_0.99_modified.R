
# =============================================================================
# FILE: MBR_iteration_algorithm_0.99_modified.R
#
# PURPOSE:
#   This file contains the HEART of the MBR system — the algorithm that builds
#   valid Loss Development Factor (LDF) sequences.
#
#   BACKGROUND:
#   After computing volume-weighted average LDFs, those values may violate two
#   actuarial rules:
#     Rule 1: Every LDF must be >= 0.99  (claims shouldn't shrink more than 1%)
#     Rule 2: LDFs must be non-increasing (development slows over time)
#
#   This algorithm explores many possible "fixes" by swapping problem values with
#   values from the 4 fitted curves (Exponential, Inverse Power, Power, Weibull).
#   Each valid fixed sequence is called a "converged iteration". The best one
#   (lowest RMSE) is then used for reserving.
#
#   ANALOGY:
#   Think of it like a GPS rerouting. You have a planned route (the VW averages).
#   Some roads are blocked (constraint violations). The GPS tries replacing
#   segments with alternatives (curve values) until it finds a route that works.
#
# FUNCTIONS IN THIS FILE:
#   1. best_rsq_replace()    — fills in the "tail" of a converged iteration
#   2. validate_iteration()  — the main recursive tree-search algorithm
# =============================================================================



# =============================================================================
# FUNCTION 1: best_rsq_replace()
#
# PURPOSE:
#   After validate_iteration() finishes working on its core range
#   (first_index to default_last_index), there is often a "tail zone"
#   from default_last_index+1 to factor_one_index-1 that still needs values.
#   This function fills that tail zone using whichever fitted curve has the
#   best R-squared (best statistical fit).
#
# WHEN IS IT CALLED?
#   In the main code (SLU_main_code.R), after validate_iteration() completes,
#   best_rsq_replace() is called to extend each converged iteration into the tail.
#
# PARAMETERS:
#   iteration   — a single converged iteration (data frame with LDF values)
#   start_index — first index of the tail zone to fill
#   end_index   — last index of the tail zone to fill
#   data        — data frame containing curve-fit LDF values for all 4 curves
#                 (columns: Exponential_Decay, Inverse_Power, Power, Weibull)
#   r_sq_data   — data frame of R-squared values, sorted best-first
#                 (so r_sq_data[1,] is the best-fitting curve)
#
# RETURNS:
#   The same iteration data frame, but with Iteration_Values replaced
#   in the tail zone (start_index to end_index) by the best valid curve.
#
# EXAMPLE:
#   Suppose the algorithm handled indices 1–15 and factor_one_index = 20.
#   best_rsq_replace fills indices 16–19 with the best-fitting curve values.
#   Before: [1.50, 1.30, 1.25, 1.15, ..., 1.02, NA,  NA,  NA,  NA ]
#   After:  [1.50, 1.30, 1.25, 1.15, ..., 1.02, 1.01, 1.01, 1.00, 1.00]
# =============================================================================

best_rsq_replace = function(iteration, start_index, end_index, data, r_sq_data) {

  # Only process iterations that have successfully converged (Convergence == 1).
  # Non-converged iterations are dead ends and don't need tail filling.
  if (unique(iteration$Convergence) == 1) {

    best_rsq_df = r_sq_data        # copy of R-squared ranking table
    best_rsq_df$replaceable = 0   # default: no curve is eligible yet

    # -------------------------------------------------------------------
    # ELIGIBILITY CHECK: can a curve's value at start_index smoothly
    # connect to the iteration's last known value (at start_index - 1)?
    #
    # The rule: curve_value_at_start < iteration_value_just_before_start
    # This preserves the "non-increasing" constraint across the boundary.
    #
    # Example:
    #   iteration$Iteration_Values[start_index - 1] = 1.05  (last algo value)
    #   Exponential_Decay at start_index            = 1.03  → eligible (1.03 < 1.05)
    #   Inverse_Power at start_index                = 1.07  → NOT eligible (1.07 > 1.05)
    # -------------------------------------------------------------------

    if (data[, as.character(best_rsq_df[1, 'Distribution'])][start_index] < iteration$Iteration_Values[start_index - 1]) {
      best_rsq_df$replaceable[1] = 1   # best R-sq curve is eligible
    }
    if (data[, as.character(best_rsq_df[2, 'Distribution'])][start_index] < iteration$Iteration_Values[start_index - 1]) {
      best_rsq_df$replaceable[2] = 1   # 2nd best curve is eligible
    }
    if (data[, as.character(best_rsq_df[3, 'Distribution'])][start_index] < iteration$Iteration_Values[start_index - 1]) {
      best_rsq_df$replaceable[3] = 1   # 3rd best curve is eligible
    }
    if (data[, as.character(best_rsq_df[4, 'Distribution'])][start_index] < iteration$Iteration_Values[start_index - 1]) {
      best_rsq_df$replaceable[4] = 1   # 4th (worst) curve is eligible
    }

    # -------------------------------------------------------------------
    # FALLBACK: if NO curve is geometrically eligible (all curve values
    # are larger than the last iteration value), we force-use the best
    # R-squared curve anyway. It's better to have some smooth values in
    # the tail than to leave it unfilled.
    # -------------------------------------------------------------------
    if (sum(best_rsq_df$replaceable) == 0) {
      print(paste("Iteration values cannot be replaced. Still replacing from the curve with max R-Sq:", best_rsq_df$Distribution[1]))
      best_rsq_df$replaceable[1] = 1   # force the best R-sq curve
    }

    # -------------------------------------------------------------------
    # REPLACEMENT: use the first eligible curve (highest R-squared among
    # those that passed the eligibility check).
    #
    # We save the original values before overwriting so we can audit what
    # changed (stored in Iteration_Values_Original column).
    # -------------------------------------------------------------------
    for (i in 1:length(best_rsq_df$Distribution)) {
      if (best_rsq_df$replaceable[i] == 1) {
        print(paste("Best R Sq Curve Replacement Curve:", best_rsq_df$Distribution[i]))

        # Keep a copy of what was there before
        iteration$Iteration_Values_Original = iteration$Iteration_Values

        # Replace the entire tail zone with this curve's values
        # Example: indices 16, 17, 18, 19 all get the Weibull curve values
        iteration$Iteration_Values[start_index:end_index] = data[, as.character(best_rsq_df[i, 'Distribution'])][start_index:end_index]

        break   # stop after the first eligible curve — we only want one replacement
      } else
        next
    }

  }

  return(iteration)
}




# =============================================================================
# FUNCTION 2: validate_iteration()
#
# PURPOSE:
#   This is a RECURSIVE function that performs a depth-first tree search
#   to find LDF sequences that satisfy both actuarial constraints:
#     1. Every LDF >= 0.99
#     2. LDFs are non-increasing (each <= the previous one)
#
#   HOW IT WORKS — THE TREE METAPHOR:
#   Imagine a decision tree. Each node is a candidate LDF sequence.
#   - Start with the initial VW average LDFs (the "root" of the tree)
#   - Scan left to right for the first constraint violation
#   - Walk backwards to find the earliest index where a curve can fix it
#   - For each eligible curve, create a new "branch" (copy the sequence,
#     swap in the curve value) and call validate_iteration() on it
#   - If no violations found → the sequence has "converged" → save it
#   - If no fix possible → this branch is a dead end → abandon it
#
#   GLOBAL STATE (<<- operator):
#   R's <<- modifies variables in the PARENT/GLOBAL scope (not just locally).
#   This is how all recursive calls share:
#     - iterations_list: the growing collection of all candidate sequences
#     - function_counter: how many times the function has been called
#   In Python, you'd use a class or mutable dict to achieve the same thing.
#
# PARAMETERS:
#   x                      — the LDF sequence being tested (numeric vector)
#                            Example: c(1.50, 1.30, 1.25, 0.98, 1.10, 1.02)
#   l                      — recursion LEVEL (how deep in the tree we are)
#                            Level 0 = initial VW selection
#                            Level 1 = first replacement made
#                            Level 2 = second replacement made, etc.
#   d                      — which curve generated this branch
#                            ("ExponentialDecay", "InversePower", "Power", "Weibull")
#   c                      — the function call count at the time this call started
#                            Used to index into iterations_list
#   t                      — index_replacement_tracker (integer vector, same length as x)
#                            t[k] = 1 means index k has already been replaced in this branch
#                            t[k] = 0 means index k is still available for replacement
#                            This prevents infinite loops (can't replace the same index twice)
#   first_index            — leftmost index the algorithm is allowed to modify
#   last_index             — rightmost index the algorithm is allowed to modify
#   data                   — data frame with curve-fit LDF values for all 4 curves
#   profile_id_analyzed    — the insurance product being processed (e.g. "ProductA_Gross")
#   iter_algo_curves_to_use — which curves to try: top 2 in Phase 1, all 4 in Phase 2
#
# RETURNS: always 0 (return value is unused; results go into global iterations_list)
# =============================================================================

validate_iteration = function(x, l, d, c, t, first_index, last_index, data, profile_id_analyzed, iter_algo_curves_to_use) {

  # -------------------------------------------------------------------
  # SAFETY VALVE: stop if we've done too many iterations.
  #
  # The tree can theoretically be enormous. With 4 curves × many indices,
  # the branching can explode. We cap at iteration_num_threshold (11,000)
  # to ensure the program finishes in reasonable time.
  #
  # If we hit the cap, profile_run_success_flag is set to 0, signalling
  # to the main code that this profile hit its limit (the initial selection
  # will be used as a fallback).
  # -------------------------------------------------------------------
  if (function_counter[profile_id_analyzed] > iteration_num_threshold) {
    profile_run_success_flag[profile_id_analyzed] <<- 0   # <<- writes to global scope
    return(0)
  }

  # Increment the global call counter for this profile.
  # <<- is R's way of modifying a variable in the parent/global environment.
  function_counter[profile_id_analyzed] <<- function_counter[profile_id_analyzed] + 1

  # -------------------------------------------------------------------
  # RECORD THIS ITERATION in the global list.
  #
  # Every call to validate_iteration() — whether it converges or not —
  # is saved to iterations_list. Converged ones (Convergence=1) will
  # later be scored by RMSE. Non-converged ones (Convergence=0) are
  # dead ends and will be filtered out.
  #
  # Example entry:
  #   Iteration_Values: [1.50, 1.30, 1.03, 1.01, 1.00]
  #   Level: 2
  #   Gen_From_Dist: "ExponentialDecay"
  #   Func_Call_Count: 47
  #   Convergence: 0  (will be updated to 1 if this sequence passes all checks)
  # -------------------------------------------------------------------
  iterations_list[[profile_id_analyzed]][[c]] <<- as.data.frame(
    cbind.data.frame(
      Iteration_Values  = x,
      Level             = l,
      Gen_From_Dist     = d,
      Func_Call_Count   = function_counter[profile_id_analyzed],
      Convergence       = 0         # pessimistic default; set to 1 below if valid
    )
  )

  # -------------------------------------------------------------------
  # CONSTRAINT SCAN: walk through the LDF sequence from left to right
  # and find the FIRST violation.
  #
  # Two rules:
  #   - At the very first index: LDF must be >= 0.99
  #   - At every subsequent index: LDF must be >= 0.99 AND <= previous LDF
  #
  # Example sequence: [1.50, 1.30, 1.25, 0.98, 1.10, 1.02]
  #   Index 1 (1.50): OK
  #   Index 2 (1.30): OK (1.30 < 1.50 and >= 0.99)
  #   Index 3 (1.25): OK
  #   Index 4 (0.98): VIOLATION — 0.98 < 0.99  → j=1, break here, i=4
  #
  # j = 1 means "violation found at index i"
  # j = 0 means "no violation — this sequence is valid!"
  # -------------------------------------------------------------------
  for (i in (first_index):(last_index)) {
    if (i == first_index)
      j = ifelse(x[i] < 0.99, 1, 0)   # at the first index: only check minimum
    else
      j = ifelse(x[i] < 0.99 | x[i] > x[i - 1], 1, 0)  # also check monotonicity

    if (j == 1)
      break   # found a violation at index i — stop scanning, go fix it
  }


  # =================================================================
  # BRANCH A: VIOLATION FOUND (j == 1)
  # =================================================================
  if (j == 1) {
    print(paste("Incorrect value found at index:", i))

    # ---------------------------------------------------------------
    # FIND REPLACEABLE INDEX: walk BACKWARDS from the violation.
    #
    # WHY backwards? Because we want to fix the earliest possible index
    # that is still causing the violation. This prevents over-replacing.
    #
    # We look for an index k (from i back to first_index) where:
    #   (a) t[k] == 0 (this index hasn't been replaced yet on this branch)
    #   (b) At least one curve provides a valid replacement value:
    #       - curve_value >= 1.0  (must be a real development factor)
    #       - curve_value < x[k-1]  (must be less than the previous LDF)
    #       - Special case at first_index: no predecessor to check
    #
    # Example:
    #   Violation at i=4. Walk back: k=4, k=3, k=2...
    #   At k=4: t[4]=0 and Exponential_Decay[4]=1.03, which is < x[3]=1.25 ✓
    #   → we can fix at k=4. Break out of the backwards loop.
    # ---------------------------------------------------------------
    for (k in i:first_index) {
      if (t[k] == 0 & k > first_index) {

        # Check if any allowed curve can replace at this non-first index
        if (any(iter_algo_curves_to_use == 'Exponential_Decay') & data$Exponential_Decay[k] >= 1 & data$Exponential_Decay[k] < x[k - 1] |
            any(iter_algo_curves_to_use == 'Inverse_Power')    & data$Inverse_Power[k] >= 1    & data$Inverse_Power[k] < x[k - 1]    |
            any(iter_algo_curves_to_use == 'Power')            & data$Power[k] >= 1             & data$Power[k] < x[k - 1]            |
            any(iter_algo_curves_to_use == 'Weibull')          & data$Weibull[k] >= 1           & data$Weibull[k] < x[k - 1]) {
          print(paste("Value can be replaced from curve at index", k))
          break   # found a replaceable index — exit the backwards loop
        } else
          next    # no valid curve here — keep walking backwards

      } else if (t[k] == 0 & k == first_index) {

        # At first_index: only require curve_value >= 1 (no predecessor check)
        if (any(iter_algo_curves_to_use == 'Exponential_Decay') & data$Exponential_Decay[k] >= 1 |
            any(iter_algo_curves_to_use == 'Inverse_Power')    & data$Inverse_Power[k] >= 1    |
            any(iter_algo_curves_to_use == 'Power')            & data$Power[k] >= 1             |
            any(iter_algo_curves_to_use == 'Weibull')          & data$Weibull[k] >= 1) {
          print(paste("Value can be replaced from curve at index", k))
          break
        } else
          next

      } else {
        # t[k] == 1 means this index was already replaced on this branch.
        # No point trying it again — it's already a curve value and still
        # didn't fix things. This is a dead-end branch.
        print('Value cannot be replaced from curve fits. Algorithm did not converge. Stopping code execution')
        k = 0   # k=0 signals "no replaceable index found"
        break
      }
    }

    # Mark index k as "used" in THIS branch's tracker.
    # This prevents future recursive calls on this branch from replacing k again.
    t[k] = 1

    # ---------------------------------------------------------------
    # CREATE BRANCHES: for each valid curve, make a copy of the sequence,
    # swap in the curve's value at index k, and recurse.
    #
    # This is where the "tree" grows. If 2 curves are valid at index k,
    # we create 2 new branches and recurse into each one.
    #
    # CASE A: k > first_index (the replaceable index is not the very first)
    #   → replacement must satisfy: curve_value >= 1 AND < x[k-1]
    # ---------------------------------------------------------------
    if (k > first_index) {

      # Branch with Exponential Decay curve
      if (any(iter_algo_curves_to_use == 'Exponential_Decay') & data$Exponential_Decay[k] >= 1 & data$Exponential_Decay[k] < x[k - 1]) {
        x_Exponential_Decay = x                              # copy the current sequence
        x_Exponential_Decay[k] = data$Exponential_Decay[k]  # swap in the curve value at k
        # Recurse: validate this new sequence (now one level deeper in the tree)
        validate_iteration(x_Exponential_Decay, l + 1, 'ExponentialDecay', function_counter[profile_id_analyzed], t, first_index, last_index, data, profile_id_analyzed, iter_algo_curves_to_use)
      }

      # Branch with Inverse Power curve
      if (any(iter_algo_curves_to_use == 'Inverse_Power') & data$Inverse_Power[k] >= 1 & data$Inverse_Power[k] < x[k - 1]) {
        x_Inverse_Power = x
        x_Inverse_Power[k] = data$Inverse_Power[k]
        validate_iteration(x_Inverse_Power, l + 1, 'InversePower', function_counter[profile_id_analyzed], t, first_index, last_index, data, profile_id_analyzed, iter_algo_curves_to_use)
      }

      # Branch with Power curve
      if (any(iter_algo_curves_to_use == 'Power') & data$Power[k] >= 1 & data$Power[k] < x[k - 1]) {
        x_Power = x
        x_Power[k] = data$Power[k]
        validate_iteration(x_Power, l + 1, 'Power', function_counter[profile_id_analyzed], t, first_index, last_index, data, profile_id_analyzed, iter_algo_curves_to_use)
      }

      # Branch with Weibull curve
      if (any(iter_algo_curves_to_use == 'Weibull') & data$Weibull[k] >= 1 & data$Weibull[k] < x[k - 1]) {
        x_Weibull = x
        x_Weibull[k] = data$Weibull[k]
        validate_iteration(x_Weibull, l + 1, 'Weibull', function_counter[profile_id_analyzed], t, first_index, last_index, data, profile_id_analyzed, iter_algo_curves_to_use)
      }
    }

    # ---------------------------------------------------------------
    # CASE B: k == first_index (the replaceable index IS the very first)
    #   → only require curve_value >= 1 (no predecessor to compare against)
    # ---------------------------------------------------------------
    if (k == first_index) {

      if (any(iter_algo_curves_to_use == 'Exponential_Decay') & data$Exponential_Decay[k] >= 1) {
        x_Exponential_Decay = x
        x_Exponential_Decay[k] = data$Exponential_Decay[k]
        validate_iteration(x_Exponential_Decay, l + 1, 'ExponentialDecay', function_counter[profile_id_analyzed], t, first_index, last_index, data, profile_id_analyzed, iter_algo_curves_to_use)
      }

      if (any(iter_algo_curves_to_use == 'Inverse_Power') & data$Inverse_Power[k] >= 1) {
        x_Inverse_Power = x
        x_Inverse_Power[k] = data$Inverse_Power[k]
        validate_iteration(x_Inverse_Power, l + 1, 'InversePower', function_counter[profile_id_analyzed], t, first_index, last_index, data, profile_id_analyzed, iter_algo_curves_to_use)
      }

      if (any(iter_algo_curves_to_use == 'Power') & data$Power[k] >= 1) {
        x_Power = x
        x_Power[k] = data$Power[k]
        validate_iteration(x_Power, l + 1, 'Power', function_counter[profile_id_analyzed], t, first_index, last_index, data, profile_id_analyzed, iter_algo_curves_to_use)
      }

      if (any(iter_algo_curves_to_use == 'Weibull') & data$Weibull[k] >= 1) {
        x_Weibull = x
        x_Weibull[k] = data$Weibull[k]
        validate_iteration(x_Weibull, l + 1, 'Weibull', function_counter[profile_id_analyzed], t, first_index, last_index, data, profile_id_analyzed, iter_algo_curves_to_use)
      }
    }

    # This message prints after all recursive branches have returned.
    # At this point we're back at this level — all branches from here are exhausted.
    print("Value cannot be replaced from curve fits. Algorithm did not converge")
  }


  # =================================================================
  # BRANCH B: NO VIOLATION (j == 0) → SEQUENCE IS VALID!
  # =================================================================
  if (j == 0) {
    print("Algorithm converged")

    # Mark this iteration as converged by setting column 5 (Convergence) to 1.
    # <<- writes to the global iterations_list, so every other recursive call
    # can see this update.
    #
    # Example: iterations_list[["ProductA_Gross"]][[47]]$Convergence = 1
    iterations_list[[profile_id_analyzed]][[c]][5] <<- 1
  }

  return(0)
}
