# =============================================================================
# FILE: iteration.py
#
# PURPOSE:
#   The CORE algorithm of the MBR system — finds valid Loss Development Factor
#   (LDF) sequences by exploring a tree of possible curve-fit substitutions.
#
# CONVERTED FROM:
#   MBR_iteration_algorithm_0.99_modified.R
#
# KEY CONVERSION CHANGE:
#   The R version uses deep RECURSION with global state (<<-).
#   This Python version uses an ITERATIVE approach with an explicit stack.
#   The logic is identical — we just replaced "call yourself" with
#   "push onto a stack and loop."
#
#   Why? Python has a default recursion limit of 1,000 calls. The R code
#   can recurse thousands of levels deep. The stack-based approach has no
#   such limit and is also easier to debug (you can inspect the stack).
#
# BACKGROUND:
#   After computing volume-weighted average LDFs, those values may violate
#   two actuarial rules:
#     Rule 1: Every LDF must be >= 0.99 (claims shouldn't shrink more than 1%)
#     Rule 2: LDFs must be non-increasing (development slows over time)
#
#   This algorithm explores many possible "fixes" by swapping problem values
#   with values from the 4 fitted curves (Exponential Decay, Inverse Power,
#   Power, Weibull). Each valid fixed sequence is a "converged iteration".
#   The best one (lowest RMSE, scored elsewhere) is used for reserving.
#
# FUNCTIONS:
#   1. run_iteration()        — main entry point (runs the two-phase strategy)
#   2. validate_iteration()   — the core tree-search (stack-based)
#   3. best_rsq_replace()     — fills the tail zone of a converged iteration
#   4. _find_violation()      — helper: scans an LDF sequence for constraint violations
#   5. _find_replaceable_index() — helper: walks backwards to find where a curve can fix
#   6. _get_eligible_curves() — helper: checks which curves are valid at a given index
# =============================================================================

import copy
import logging
from dataclasses import dataclass, field

import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structure for the explicit stack.
#
# Each entry on the stack represents one "branch" of the search tree.
# In the R version, each branch was a separate recursive function call.
# Here, each branch is an item on the stack that we process in a loop.
# ---------------------------------------------------------------------------
@dataclass
class IterationState:
    """One candidate branch in the iteration search tree.

    Attributes:
        ldfs:         Current LDF sequence (list of floats). Modified from
                      the initial VW averages by substituting curve values.
        replaced:     Set of indexes that have already been replaced on THIS
                      branch. Prevents replacing the same index twice (which
                      would cause infinite loops).
        position:     The index from which to start scanning for violations.
                      When we create a branch by replacing index k, the new
                      branch starts scanning from k (not from the beginning)
                      because everything before k was already validated.
        level:        How deep in the tree this branch is (0 = initial VW
                      selection, 1 = one replacement, 2 = two, etc.).
        gen_from_dist: Which curve distribution generated this branch
                      (e.g., "Exponential_Decay"). "Initial" for the root.
    """
    ldfs: list
    replaced: set = field(default_factory=set)
    position: int = 0
    level: int = 0
    gen_from_dist: str = "Initial"


# ---------------------------------------------------------------------------
# Default configuration for the iteration algorithm.
# These can be overridden by passing a config dictionary.
# ---------------------------------------------------------------------------
DEFAULT_ITERATION_CONFIG = {
    # Maximum number of iterations (branches explored) before stopping.
    # In R, this is iteration_num_threshold = 50000.
    "max_iterations": 50000,

    # The minimum allowed LDF value. In R code this is hardcoded as 0.99.
    "min_ldf": 0.99,

    # The four curve names, matching the column names in the curve_fits DataFrame.
    "all_curves": ["Exponential_Decay", "Inverse_Power", "Power", "Weibull"],
}


# =============================================================================
# FUNCTION 1: run_iteration()
#
# Main entry point. Implements the two-phase strategy from SLU_main_code.R:
#   Phase 1: Try with only the top-2 curves (by R-squared) — faster, often enough
#   Phase 2: If Phase 1 finds no converged iterations, retry with all 4 curves
#
# The initial VW selection is always added as a fallback converged iteration
# (it may not satisfy all constraints, but it is the "best we have" if nothing
# else converges).
#
# Parameters:
#   initial_ldfs  — list/array of initial VW average LDFs
#   curve_fits    — DataFrame with columns for each curve's fitted LDFs
#                   (e.g., columns: "Exponential_Decay", "Inverse_Power", "Power", "Weibull")
#   r_squared     — DataFrame with columns ["Distribution", "R_Squared"],
#                   sorted by R_Squared descending (best first)
#   first_index   — leftmost index the algorithm is allowed to modify (0-based)
#   last_index    — rightmost index the algorithm is allowed to modify (0-based)
#   config        — optional dict overriding DEFAULT_ITERATION_CONFIG
#
# Returns:
#   List of dicts, each representing a converged iteration:
#     {
#       "ldfs": [...],             # the LDF sequence
#       "level": int,              # tree depth
#       "gen_from_dist": str,      # which curve generated this branch
#       "call_count": int,         # when this iteration was recorded
#       "converged": True/False    # whether it passed all constraints
#     }
# =============================================================================
def run_iteration(initial_ldfs, curve_fits, r_squared, first_index, last_index, config=None):
    """Run the full iteration algorithm with two-phase curve strategy.

    R equivalent: The iteration workflow in SLU_main_code.R that calls
    validate_iteration() first with top-2 curves, then with all 4 if needed.
    """

    cfg = {**DEFAULT_ITERATION_CONFIG, **(config or {})}

    # --- Determine curve order from R-squared ranking ---
    # r_squared is sorted best-first, so r_squared["Distribution"][0] is the best curve
    all_curves_ranked = r_squared["Distribution"].tolist()

    # --- Phase 1: try with top 2 curves only ---
    top_2_curves = all_curves_ranked[:2]

    logger.info("Phase 1: Running iteration with top 2 curves: %s", top_2_curves)
    converged_phase1, total_count_1 = validate_iteration(
        initial_ldfs=initial_ldfs,
        curve_fits=curve_fits,
        curves_to_use=top_2_curves,
        first_index=first_index,
        last_index=last_index,
        config=cfg,
    )

    # --- Phase 2: if Phase 1 found nothing, retry with all 4 curves ---
    if len(converged_phase1) == 0:
        logger.info(
            "Phase 1 found no converged iterations after %d branches. "
            "Retrying with all 4 curves.",
            total_count_1,
        )
        converged_phase2, total_count_2 = validate_iteration(
            initial_ldfs=initial_ldfs,
            curve_fits=curve_fits,
            curves_to_use=all_curves_ranked,
            first_index=first_index,
            last_index=last_index,
            config=cfg,
        )
        converged = converged_phase2
        total_count = total_count_1 + total_count_2
    else:
        converged = converged_phase1
        total_count = total_count_1

    # --- Always include the initial VW selection as a fallback ---
    # In R, the initial selection is always kept as iteration #1 with Convergence=1.
    # Even if it violates constraints, it serves as a "best we have" baseline.
    initial_entry = {
        "ldfs": list(initial_ldfs),
        "level": 0,
        "gen_from_dist": "Initial",
        "call_count": 0,
        "converged": True,  # treated as converged for scoring purposes
    }
    converged.insert(0, initial_entry)

    logger.info(
        "Iteration complete. %d converged iterations found (including initial). "
        "%d total branches explored.",
        len(converged),
        total_count,
    )

    return converged


# =============================================================================
# FUNCTION 2: validate_iteration()
#
# The core tree-search algorithm, converted from R's recursive version to
# Python's iterative stack-based version.
#
# HOW THE STACK REPLACES RECURSION:
#
#   R recursive version:
#     validate_iteration(modified_ldfs, level+1, ...)
#       → calls itself, going deeper into the call stack
#       → each call modifies global iterations_list via <<-
#
#   Python iterative version:
#     stack.append(IterationState(modified_ldfs, level+1, ...))
#       → instead of calling itself, we push a new state onto the stack
#       → the while loop picks it up and processes it
#       → converged results go into a list (no global state needed)
#
#   The two approaches explore the SAME tree in the SAME order (depth-first),
#   because we use stack.pop() (LIFO = last in, first out = depth-first).
#
# Parameters:
#   initial_ldfs  — list of initial VW average LDFs
#   curve_fits    — DataFrame with curve-fit LDF columns
#   curves_to_use — list of curve names to try (e.g., ["Exponential_Decay", "Weibull"])
#   first_index   — leftmost modifiable index (0-based)
#   last_index    — rightmost modifiable index (0-based)
#   config        — configuration dict
#
# Returns:
#   (converged_list, iteration_count)
#   converged_list: list of dicts for each converged iteration
#   iteration_count: total number of branches explored
# =============================================================================
def validate_iteration(initial_ldfs, curve_fits, curves_to_use, first_index, last_index, config):
    """Stack-based iterative tree-search for valid LDF sequences.

    R equivalent: validate_iteration() in MBR_iteration_algorithm_0.99_modified.R
    (converted from recursion to iteration).
    """

    max_iterations = config["max_iterations"]
    min_ldf = config["min_ldf"]

    # --- Initialize the stack with the root state (the initial VW averages) ---
    root = IterationState(
        ldfs=list(initial_ldfs),
        replaced=set(),
        position=first_index,
        level=0,
        gen_from_dist="Initial",
    )
    stack = [root]

    # --- Storage for converged (valid) iterations ---
    converged = []

    # --- Iteration counter (equivalent to R's function_counter) ---
    iteration_count = 0

    # ===================================================================
    # MAIN LOOP: process one branch from the stack per iteration.
    #
    # This replaces the recursive calls in R. Each pass through the loop
    # is equivalent to one call of validate_iteration() in R.
    # ===================================================================
    while stack and iteration_count < max_iterations:
        # Pop the most recent branch (depth-first search)
        current = stack.pop()
        iteration_count += 1

        # --- Step 1: Scan for constraint violations ---
        # Walk the LDF sequence from first_index to last_index.
        # Find the first index where a rule is broken.
        violation_index = _find_violation(
            current.ldfs, first_index, last_index, min_ldf
        )

        # --- Step 2a: No violation found → this sequence is VALID ---
        if violation_index is None:
            logger.debug(
                "Converged at iteration %d (level %d, from %s)",
                iteration_count,
                current.level,
                current.gen_from_dist,
            )
            converged.append({
                "ldfs": list(current.ldfs),
                "level": current.level,
                "gen_from_dist": current.gen_from_dist,
                "call_count": iteration_count,
                "converged": True,
            })
            continue  # move to next branch on the stack

        # --- Step 2b: Violation found → try to fix it ---
        # Walk BACKWARDS from the violation to find an index where
        # a curve substitution can fix the problem.
        replaceable_index = _find_replaceable_index(
            ldfs=current.ldfs,
            curve_fits=curve_fits,
            curves_to_use=curves_to_use,
            violation_index=violation_index,
            first_index=first_index,
            already_replaced=current.replaced,
        )

        # No fixable index found → this branch is a dead end
        if replaceable_index is None:
            logger.debug(
                "Dead end at iteration %d: no replaceable index for violation at %d",
                iteration_count,
                violation_index,
            )
            continue  # abandon this branch, move to next on stack

        # --- Step 3: Create new branches for each eligible curve ---
        # For each curve that provides a valid replacement at replaceable_index,
        # make a copy of the current LDF sequence, swap in the curve's value,
        # and push it onto the stack.
        eligible_curves = _get_eligible_curves(
            ldfs=current.ldfs,
            curve_fits=curve_fits,
            curves_to_use=curves_to_use,
            index=replaceable_index,
            first_index=first_index,
        )

        for curve_name in eligible_curves:
            # Copy the current LDFs and swap in the curve value at the replaceable index
            new_ldfs = list(current.ldfs)
            new_ldfs[replaceable_index] = curve_fits[curve_name].iloc[replaceable_index]

            # Copy the replacement tracker and mark this index as used
            new_replaced = current.replaced | {replaceable_index}

            new_state = IterationState(
                ldfs=new_ldfs,
                replaced=new_replaced,
                position=replaceable_index,
                level=current.level + 1,
                gen_from_dist=curve_name,
            )
            stack.append(new_state)

    # --- Check if we hit the iteration cap ---
    if iteration_count >= max_iterations and stack:
        logger.warning(
            "Iteration cap reached (%d). %d branches remain unexplored. "
            "%d converged iterations found so far.",
            max_iterations,
            len(stack),
            len(converged),
        )

    return converged, iteration_count


# =============================================================================
# FUNCTION 3: best_rsq_replace()
#
# After the iteration algorithm handles the core range (first_index to
# last_index), there is often a "tail zone" beyond last_index that still
# needs LDF values. This function fills that tail zone using whichever
# fitted curve has the best R-squared AND can smoothly connect to the
# last iteration value.
#
# R equivalent: best_rsq_replace() in MBR_iteration_algorithm_0.99_modified.R
#
# Parameters:
#   iteration     — dict with "ldfs" key (a converged iteration from validate_iteration)
#   start_index   — first index of the tail zone to fill (0-based)
#   end_index     — last index of the tail zone to fill (0-based, inclusive)
#   curve_fits    — DataFrame with curve-fit LDF columns
#   r_squared     — DataFrame with ["Distribution", "R_Squared"], sorted best-first
#
# Returns:
#   Updated iteration dict with tail zone filled.
# =============================================================================
def best_rsq_replace(iteration, start_index, end_index, curve_fits, r_squared):
    """Fill the tail zone of a converged iteration with the best-fit curve.

    R equivalent: best_rsq_replace() in MBR_iteration_algorithm_0.99_modified.R
    """

    # Only process converged iterations
    if not iteration.get("converged", False):
        return iteration

    # Edge case: nothing to fill (start beyond end, or invalid range)
    if start_index > end_index or start_index <= 0:
        return iteration

    ldfs = iteration["ldfs"]

    # Save original values before modification (for audit trail)
    iteration["ldfs_original"] = list(ldfs)

    # --- Eligibility check ---
    # A curve is "eligible" if its value at start_index is less than the
    # iteration's value at start_index - 1. This preserves the non-increasing
    # constraint across the boundary between the algo zone and the tail zone.
    #
    # Example:
    #   ldfs[start_index - 1] = 1.05 (last value from the algorithm)
    #   Weibull at start_index = 1.03 → eligible (1.03 < 1.05)
    #   Power at start_index   = 1.07 → NOT eligible (1.07 > 1.05)
    last_algo_value = ldfs[start_index - 1]

    eligible = []
    for _, row in r_squared.iterrows():
        dist_name = row["Distribution"]
        curve_value_at_start = curve_fits[dist_name].iloc[start_index]
        if curve_value_at_start < last_algo_value:
            eligible.append(dist_name)

    # --- Fallback: if no curve is geometrically eligible, force the best-R² curve ---
    if len(eligible) == 0:
        best_curve = r_squared["Distribution"].iloc[0]
        logger.info(
            "No curve is geometrically eligible for tail replacement. "
            "Force-using best R² curve: %s",
            best_curve,
        )
        eligible = [best_curve]

    # --- Replace tail zone with the best eligible curve ---
    # eligible[0] is the highest-R² curve among those that passed the check
    # (r_squared is already sorted best-first, and we iterate in that order)
    chosen_curve = eligible[0]
    logger.info("Tail replacement using curve: %s", chosen_curve)

    for idx in range(start_index, end_index + 1):
        if idx < len(curve_fits):
            ldfs[idx] = curve_fits[chosen_curve].iloc[idx]

    iteration["ldfs"] = ldfs
    iteration["tail_curve"] = chosen_curve

    return iteration


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _find_violation(ldfs, first_index, last_index, min_ldf):
    """Scan an LDF sequence for the first constraint violation.

    R equivalent: The for-loop in validate_iteration() that sets j=1 on violation.

    Constraints:
      - At first_index: LDF must be >= min_ldf (0.99)
      - At every subsequent index: LDF must be >= min_ldf AND <= previous LDF

    Parameters:
        ldfs        — list of LDF values
        first_index — start of the scan range (0-based)
        last_index  — end of the scan range (0-based, inclusive)
        min_ldf     — minimum allowed LDF value (default 0.99)

    Returns:
        The index of the first violation, or None if no violation found.
    """
    for i in range(first_index, min(last_index + 1, len(ldfs))):
        if i == first_index:
            # At the very first index: only check minimum value
            if ldfs[i] < min_ldf:
                return i
        else:
            # At subsequent indexes: check minimum AND monotonicity
            if ldfs[i] < min_ldf or ldfs[i] > ldfs[i - 1]:
                return i

    return None  # no violation found — sequence is valid


def _find_replaceable_index(ldfs, curve_fits, curves_to_use, violation_index,
                            first_index, already_replaced):
    """Walk backwards from the violation to find an index where a curve can help.

    R equivalent: The backwards for-loop in validate_iteration() that finds k.

    We look for an index k (from violation_index back to first_index) where:
      (a) k has NOT already been replaced on this branch
      (b) At least one allowed curve provides a valid value at k:
          - curve_value >= 1.0 (real development factor)
          - curve_value < ldfs[k-1] (preserves monotonicity) — except at first_index

    Parameters:
        ldfs              — current LDF sequence
        curve_fits        — DataFrame with curve-fit LDF columns
        curves_to_use     — list of curve names allowed in this phase
        violation_index   — where the violation was found
        first_index       — leftmost modifiable index
        already_replaced  — set of indexes already replaced on this branch

    Returns:
        The replaceable index, or None if no fix is possible (dead end).
    """
    for k in range(violation_index, first_index - 1, -1):
        # Skip indexes that have already been replaced on this branch
        if k in already_replaced:
            # In R, when t[k]==1 and we've exhausted all options going backwards,
            # the algorithm sets k=0 and breaks (dead end). We replicate that by
            # returning None if we hit an already-replaced index.
            return None

        # Check if any allowed curve has a valid value at this index
        eligible = _get_eligible_curves(ldfs, curve_fits, curves_to_use, k, first_index)
        if len(eligible) > 0:
            return k

    return None  # walked all the way back, nothing replaceable


def _get_eligible_curves(ldfs, curve_fits, curves_to_use, index, first_index):
    """Check which curves provide a valid replacement at a given index.

    R equivalent: The series of if-statements checking each curve in validate_iteration().

    A curve is eligible at index k if:
      - curve_value >= 1.0 (must be a real development factor, not shrinkage)
      - If k > first_index: curve_value < ldfs[k-1] (preserves monotonicity)
      - If k == first_index: no predecessor to check (just needs >= 1.0)

    Parameters:
        ldfs          — current LDF sequence
        curve_fits    — DataFrame with curve-fit columns
        curves_to_use — list of curve names to check
        index         — the index where we want to substitute
        first_index   — leftmost modifiable index

    Returns:
        List of eligible curve names (may be empty).
    """
    eligible = []

    for curve_name in curves_to_use:
        # Skip curves that don't exist in the DataFrame
        if curve_name not in curve_fits.columns:
            continue

        curve_value = curve_fits[curve_name].iloc[index]

        # Must be a real development factor (>= 1.0)
        if curve_value < 1.0:
            continue

        # At first_index: no predecessor to check
        if index == first_index:
            eligible.append(curve_name)
            continue

        # At other indexes: must be less than the previous LDF (monotonicity)
        if curve_value < ldfs[index - 1]:
            eligible.append(curve_name)

    return eligible
