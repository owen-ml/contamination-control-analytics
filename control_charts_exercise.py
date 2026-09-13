"""
control_charts_exercise.py

THIS IS THE FILE WHERE THE ACTUAL LEARNING HAPPENS.

`freeman_tukey()` is implemented for you -- it's straight out of your own
paper's Equation 2, and you'll need it again in Module 2, so there's no
value in re-deriving it.

The four control chart functions below are NOT implemented. Each has:
  - the formula, in comments, that you need
  - a short explanation of WHY it works the way it does
  - a self-check block at the bottom of the file that tells you immediately
    whether your implementation is correct (no need to ask me to grade it)

Work top to bottom. Don't skip to CUSUM before Shewhart/Poisson -- each one
builds your intuition for the next.

Run with:
    python control_charts_exercise.py
Until you see "ALL CHECKS PASSED" at the bottom, something's off.
"""

import numpy as np


# ----------------------------------------------------------------------------
# Provided: Freeman-Tukey variance-stabilizing transform (your paper, Eq. 2)
# ----------------------------------------------------------------------------
def freeman_tukey(counts: np.ndarray) -> np.ndarray:
    """
    y = sqrt(x) + sqrt(x + 1)

    For Poisson-distributed counts, variance = mean, which means the noise
    level of your data changes depending on how big the counts are (a room
    running at baseline lambda=2 is noisier, relatively, than one running at
    lambda=50). This transform makes the variance approximately constant
    (~1) regardless of the underlying rate, which is what lets you compare
    trends across rooms/sensors on equal footing, and is required before
    feeding count data into most ML models (Module 2 will use this).
    """
    counts = np.asarray(counts, dtype=float)
    return np.sqrt(counts) + np.sqrt(counts + 1)


# ----------------------------------------------------------------------------
# TODO 1: Shewhart limits (the "naive" approach -- assumes counts are
# approximately normal, which is often WRONG for low counts, but it's the
# default most off-the-shelf tools use, and you need to understand it before
# you can explain why the Poisson-based version below is better)
# ----------------------------------------------------------------------------
def shewhart_limits(baseline_counts: np.ndarray, n_sigma: float = 3.0):
    """
    Formula:
        center = mean(baseline_counts)
        std    = sample standard deviation of baseline_counts (use ddof=1)
        UCL    = center + n_sigma * std
        LCL    = max(0, center - n_sigma * std)   # counts can't go negative

    Returns:
        (center, ucl, lcl)
    """
    center = np.mean(baseline_counts)
    std = np.std(baseline_counts, ddof=1)
    ucl = center + n_sigma * std
    lcl = max(0, center - n_sigma * std)
    return center, ucl, lcl

# ----------------------------------------------------------------------------
# TODO 2: Poisson-based ("c-chart") limits
# ----------------------------------------------------------------------------
def poisson_limits(baseline_counts: np.ndarray, n_sigma: float = 3.0):
    """
    Why this differs from Shewhart: for a Poisson process, variance equals
    the mean (Var[X] = lambda). So instead of estimating a separate std from
    the sample, you derive the spread DIRECTLY from the estimated rate:

    Formula:
        lambda_hat = mean(baseline_counts)
        UCL = lambda_hat + n_sigma * sqrt(lambda_hat)
        LCL = max(0, lambda_hat - n_sigma * sqrt(lambda_hat))

    This is the statistically correct approach for count data and is the
    kind of detail that signals real subject-matter fluency -- most
    homegrown EM trending tools apply Shewhart-style limits (built for
    continuous, normally-distributed measurements like temperature or pH)
    directly to particle counts, which is a subtly wrong assumption.

    Returns:
        (lambda_hat, ucl, lcl)
    """
    lambda_hat = np.mean(baseline_counts)
    ucl = lambda_hat + n_sigma * np.sqrt(lambda_hat)
    lcl = max(0, lambda_hat - n_sigma * np.sqrt(lambda_hat))
    return lambda_hat, ucl, lcl


# ----------------------------------------------------------------------------
# TODO 3: EWMA (Exponentially Weighted Moving Average) chart
# ----------------------------------------------------------------------------
def ewma_chart(baseline_counts: np.ndarray, test_counts: np.ndarray,
               lam: float = 0.2, L: float = 3.0):
    """
    Shewhart/Poisson limits only look at ONE reading at a time, so they're
    slow to notice a small, sustained drift (like your paper's HVAC drift
    mechanism). EWMA solves this by giving each new point a weighted
    "memory" of recent history.

    Formula:
        center = mean(baseline_counts)
        sigma  = std(baseline_counts, ddof=1)
        z_0    = center
        z_t    = lam * x_t + (1 - lam) * z_(t-1)      for each x_t in test_counts

        Time-varying control limits (they widen from t=1 and converge as
        t grows -- this accounts for the estimate being less certain early on):
            UCL_t = center + L * sigma * sqrt( (lam / (2 - lam)) * (1 - (1-lam)^(2t)) )
            LCL_t = center - L * sigma * sqrt( (lam / (2 - lam)) * (1 - (1-lam)^(2t)) )
        where t is the 1-indexed position within test_counts (t = 1, 2, 3, ...)

    Returns:
        z          -- np.ndarray of length len(test_counts), the EWMA statistic at each t
        ucl        -- np.ndarray, same length, the upper limit at each t
        flags      -- np.ndarray of bool, True where z_t > ucl_t (out of control)
    """
    center = np.mean(baseline_counts)
    sigma = np.std(baseline_counts, ddof=1)

    z = []
    z_prev = center
    for x in test_counts:
        z_prev = lam * x + (1 - lam) * z_prev
        z.append(z_prev)
    z = np.array(z)

    t = np.arange(1, len(test_counts) + 1)
    width = L * sigma * np.sqrt((lam / (2 - lam)) * (1 - (1 - lam) ** (2 * t)))
    ucl = center + width

    flags = z > ucl
    return z, ucl, flags

# ----------------------------------------------------------------------------
# TODO 4: Tabular CUSUM (Cumulative Sum) chart
# ----------------------------------------------------------------------------
def cusum_chart(baseline_counts: np.ndarray, test_counts: np.ndarray,
                 k_multiplier: float = 0.5, h_multiplier: float = 5.0):
    """
    CUSUM is the most sensitive of the three to small, sustained shifts,
    because it accumulates evidence over time rather than resetting each
    point (Shewhart) or decaying old evidence (EWMA).

    Formula:
        target = mean(baseline_counts)
        std    = std(baseline_counts, ddof=1)
        k      = k_multiplier * std      # the "slack" -- how big a shift to ignore
        h      = h_multiplier * std      # the decision threshold

        C+_0 = 0
        C+_t = max(0, C+_(t-1) + (x_t - target - k))    for each x_t in test_counts

        Flag t as out-of-control where C+_t > h.

        (This is the one-sided upper CUSUM, which is what you care about for
        contamination -- you're watching for counts going UP, not down.)

    Returns:
        c_plus  -- np.ndarray of length len(test_counts), the cumulative sum at each t
        flags   -- np.ndarray of bool, True where c_plus_t > h
    """
    target = np.mean(baseline_counts)
    std = np.std(baseline_counts, ddof=1)
    k = k_multiplier * std
    h = h_multiplier * std

    c_plus = []
    c_prev = 0.0
    for x in test_counts:
        c_prev = max(0, c_prev + (x - target - k))
        c_plus.append(c_prev)
    c_plus = np.array(c_plus)

    flags = c_plus > h
    return c_plus, flags

# ============================================================================
# SELF-CHECK -- do not edit below this line.
# Run this file. If everything is implemented correctly, all asserts pass
# and you'll see "ALL CHECKS PASSED" printed at the end.
# ============================================================================
if __name__ == "__main__":
    rng = np.random.default_rng(0)
    baseline = rng.poisson(lam=3.0, size=30).astype(float)
    # a stable run, then a sustained excursion starting at index 6
    test = np.array([2, 4, 3, 5, 3, 4, 20, 18, 15, 4, 3], dtype=float)

    # --- Freeman-Tukey sanity check (given, should already pass) ---
    ft = freeman_tukey(np.array([0, 1, 4, 9]))
    assert np.allclose(ft, [1.0, 2.414213562373095, 4.23606797749979, 6.16227766016838]), \
        "freeman_tukey is broken -- did you edit the provided function?"
    print("[ok] freeman_tukey")

    # --- Shewhart ---
    center, ucl, lcl = shewhart_limits(baseline)
    assert np.isclose(center, 3.2, atol=0.01), f"expected center ~3.2, got {center}"
    assert np.isclose(ucl, 8.848, atol=0.05), f"expected UCL ~8.848, got {ucl}"
    assert lcl == 0, f"expected LCL 0 (floored), got {lcl}"
    print("[ok] shewhart_limits")

    # --- Poisson ---
    lam_hat, ucl_p, lcl_p = poisson_limits(baseline)
    assert np.isclose(lam_hat, 3.2, atol=0.01), f"expected lambda_hat ~3.2, got {lam_hat}"
    assert np.isclose(ucl_p, 8.567, atol=0.05), f"expected UCL ~8.567, got {ucl_p}"
    print("[ok] poisson_limits")
    print(f"    note: Shewhart UCL ({ucl:.3f}) vs Poisson UCL ({ucl_p:.3f}) --"
          f" close here because baseline mean is moderate; the gap widens"
          f" at very low counts, which is exactly the heteroscedasticity"
          f" problem your paper addresses.")

    # --- EWMA ---
    z, ewma_ucl, ewma_flags = ewma_chart(baseline, test)
    assert np.isclose(z[-1], 7.797, atol=0.01), f"expected final z ~7.797, got {z[-1]}"
    assert np.isclose(ewma_ucl[-1], 5.076, atol=0.01), f"expected final UCL ~5.076, got {ewma_ucl[-1]}"
    assert list(ewma_flags) == [False, False, False, False, False, False,
                                 True, True, True, True, True], \
        f"expected excursion to be flagged starting at index 6 and persist, got {list(ewma_flags)}"
    print("[ok] ewma_chart")

    # --- CUSUM ---
    c_plus, cusum_flags = cusum_chart(baseline, test)
    assert np.isclose(c_plus[8], 40.576, atol=0.1), f"expected c_plus[8] ~40.576, got {c_plus[8]}"
    assert list(cusum_flags) == [False, False, False, False, False, False,
                                  True, True, True, True, True], \
        f"expected excursion flagged starting at index 6 and persist, got {list(cusum_flags)}"
    print("[ok] cusum_chart")

    print("\nALL CHECKS PASSED -- compare how quickly each method reacted:")
    print(f"  Shewhart/Poisson: flags a single point the instant it crosses the limit")
    print(f"  EWMA:             {list(ewma_flags).index(True)}th test point onward")
    print(f"  CUSUM:            {list(cusum_flags).index(True)}th test point onward")
    print("  (In this example they tie, because the injected shift is large and")
    print("   sudden. Try lowering the spike values in `test` to ~7-8 instead of")
    print("   15-20 and re-run -- CUSUM/EWMA will catch the smaller, sustained")
    print("   shift while Shewhart/Poisson miss it. That's the whole point of")
    print("   using all four together.)")
