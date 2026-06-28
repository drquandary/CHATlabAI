#!/usr/bin/env python3
"""Power analysis (analytic) — statsmodels cross-check to power.R.

Supports: two.sample.t, paired.t, anova, correlation, regression.
Given two of {effect, power, n}, solves for the third.

Examples:
  python3 power.py --test two.sample.t --d 0.5 --power 0.8        # n per group
  python3 power.py --test two.sample.t --d 0.5 --n 64             # achieved power
  python3 power.py --test two.sample.t --power 0.8 --n 64        # MDE (d)
  python3 power.py --test anova --f 0.25 --k 3 --power 0.8
  python3 power.py --test correlation --r 0.3 --power 0.8
  python3 power.py --test regression --f2 0.15 --power 0.8
"""
import argparse
import math
import sys


def _have_statsmodels():
    try:
        import statsmodels  # noqa: F401
        return True
    except Exception:
        return False


def _fmt(x, nd=3):
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def _explicit_arg(name):
    """Return the int value of a CLI arg only if it was explicitly passed on the command line."""
    import sys as _sys
    flag = f"--{name}"
    if flag in _sys.argv:
        i = _sys.argv.index(flag)
        if i + 1 < len(_sys.argv):
            try:
                return int(_sys.argv[i + 1])
            except ValueError:
                return None
    return None


# ---------------------------------------------------------------- main
def main(argv=None):
    p = argparse.ArgumentParser(
        prog="power.py",
        description="Analytic power analysis (statsmodels). Cross-checks power.R. "
                    "Given two of {effect, power, n}, solves for the third.",
    )
    p.add_argument("--test", required=True,
                   choices=["two.sample.t", "paired.t", "anova", "correlation", "regression"],
                   help="Design / test type.")
    p.add_argument("--d", type=float, default=None,
                   help="Cohen's d (for t-tests).")
    p.add_argument("--f", type=float, default=None,
                   help="Cohen's f (for ANOVA).")
    p.add_argument("--f2", type=float, default=None,
                   help="Cohen's f² (for regression).")
    p.add_argument("--r", type=float, default=None,
                   help="Correlation coefficient r (for correlation test).")
    p.add_argument("--k", type=int, default=2,
                   help="Number of groups (ANOVA). Default 2.")
    p.add_argument("--power", type=float, default=None,
                   help="Target power (e.g. 0.80). Omit to solve for power given --n.")
    p.add_argument("--n", type=int, default=None,
                   help="Sample size per group. Omit to solve for n given --power.")
    p.add_argument("--alpha", type=float, default=0.05,
                   help="Significance level α. Default 0.05 (two-sided).")
    p.add_argument("--fmri", action="store_true",
                   help="Append the fMRI cluster/voxel power caveat.")
    args = p.parse_args(argv)

    if not _have_statsmodels():
        print("ERROR: statsmodels is not installed. Install with: pip install statsmodels", file=sys.stderr)
        print("       (CHATLabAI install.sh installs it into the project venv.)", file=sys.stderr)
        return 2

    # Determine which variable to solve for.
    have_effect = any(v is not None for v in (args.d, args.f, args.f2, args.r))
    if not have_effect and args.power is not None and args.n is not None:
        solve = "mde"  # solve for effect size given n + power
    elif have_effect and args.power is not None and args.n is None:
        solve = "n"
    elif have_effect and args.n is not None and args.power is None:
        solve = "power"
    else:
        p.error("Provide exactly two of: effect size, --power, --n. "
                "(e.g. --d 0.5 --power 0.8  =>  n;  --d 0.5 --n 64  =>  power;  "
                "--power 0.8 --n 64  =>  MDE)")

    from statsmodels.stats.power import (TTestIndPower, TTestPower, FTestAnovaPower,
                                          FTestPowerF2, GofChisquarePower)

    alpha = args.alpha

    # ---- t-tests
    if args.test in ("two.sample.t", "paired.t"):
        is_two_sample = args.test == "two.sample.t"
        metric = "Cohen's d"
        eff = args.d
        if eff is None and solve != "mde":
            p.error(f"--d (Cohen's d) is required for {args.test}.")

        # TTestIndPower uses nobs1 + ratio; TTestPower (paired) uses nobs (no ratio).
        def _solve_t(effect_size, power, n):
            if is_two_sample:
                return TTestIndPower().solve_power(
                    effect_size=effect_size, nobs1=n, alpha=alpha,
                    power=power, ratio=1.0, alternative="two-sided")
            return TTestPower().solve_power(
                effect_size=effect_size, nobs=n, alpha=alpha,
                power=power, alternative="two-sided")

        if solve == "n":
            n = _solve_t(effect_size=eff, power=args.power, n=None)
            n_per = int(math.ceil(n))
            _report(args, "n per group", n_per, f"{metric} = {_fmt(eff)}",
                    f"power = {_fmt(args.power)}", f"α = {_fmt(alpha)} (two-sided)",
                    plain=(f"A {args.test} detecting {metric}={_fmt(eff)} at α={_fmt(alpha)} "
                           f"(two-sided) with {_fmt(args.power)} power requires approximately "
                           f"{n_per} participants per group."))
        elif solve == "power":
            power = _solve_t(effect_size=eff, power=None, n=args.n)
            _report(args, "achieved power", power, f"{metric} = {_fmt(eff)}",
                    f"n = {args.n} per group", f"α = {_fmt(alpha)} (two-sided)",
                    plain=(f"With n={args.n} per group, a {args.test} has approximately "
                           f"{_fmt(power)} power to detect {metric}={_fmt(eff)} at α={_fmt(alpha)}."))
        else:  # mde
            eff = _solve_t(effect_size=None, power=args.power, n=args.n)
            _report(args, "minimum detectable d", eff, f"n = {args.n} per group",
                    f"power = {_fmt(args.power)}", f"α = {_fmt(alpha)} (two-sided)",
                    plain=(f"With n={args.n} per group and {_fmt(args.power)} power, the minimum "
                           f"detectable {metric} at α={_fmt(alpha)} is approximately d={_fmt(eff)}."))

    # ---- ANOVA
    elif args.test == "anova":
        power_cls = FTestAnovaPower()
        metric = "Cohen's f"
        eff = args.f
        if eff is None and solve != "mde":
            p.error("--f (Cohen's f) is required for anova.")
        k = args.k
        if solve == "n":
            n = power_cls.solve_power(effect_size=eff, power=args.power, alpha=alpha,
                                     k_groups=k)
            n_per = int(math.ceil(n))
            _report(args, "n per group", n_per, f"{metric} = {_fmt(eff)}",
                    f"k = {k} groups", f"power = {_fmt(args.power)}", f"α = {_fmt(alpha)}",
                    plain=(f"A one-way ANOVA with k={k} groups detecting {metric}={_fmt(eff)} "
                           f"at α={_fmt(alpha)} with {_fmt(args.power)} power requires approximately "
                           f"{n_per} participants per group (N={n_per*k} total)."))
        elif solve == "power":
            power = power_cls.solve_power(effect_size=eff, nobs=args.n, alpha=alpha, k_groups=k)
            _report(args, "achieved power", power, f"{metric} = {_fmt(eff)}",
                    f"n = {args.n} per group", f"k = {k} groups", f"α = {_fmt(alpha)}",
                    plain=(f"With n={args.n} per group (k={k}), a one-way ANOVA has approximately "
                           f"{_fmt(power)} power to detect {metric}={_fmt(eff)} at α={_fmt(alpha)}."))
        else:
            eff = power_cls.solve_power(effect_size=None, power=args.power, nobs=args.n,
                                        alpha=alpha, k_groups=k)
            _report(args, "minimum detectable f", eff, f"n = {args.n} per group",
                    f"k = {k} groups", f"power = {_fmt(args.power)}", f"α = {_fmt(alpha)}",
                    plain=(f"With n={args.n} per group (k={k}) and {_fmt(args.power)} power, the minimum "
                           f"detectable {metric} at α={_fmt(alpha)} is approximately f={_fmt(eff)}."))

    # ---- correlation
    elif args.test == "correlation":
        power_cls = TTestPower()  # test of r uses t-distribution
        metric = "r"
        eff = args.r
        if eff is None and solve != "mde":
            p.error("--r (correlation) is required for correlation.")
        if solve == "n":
            n = power_cls.solve_power(effect_size=eff, power=args.power, alpha=alpha,
                                     alternative="two-sided")
            n_total = int(math.ceil(n))
            _report(args, "n total", n_total, f"{metric} = {_fmt(eff)}",
                    f"power = {_fmt(args.power)}", f"α = {_fmt(alpha)} (two-sided)",
                    plain=(f"A correlation test detecting r={_fmt(eff)} at α={_fmt(alpha)} "
                           f"(two-sided) with {_fmt(args.power)} power requires approximately "
                           f"{n_total} participants."))
        elif solve == "power":
            power = power_cls.solve_power(effect_size=eff, nobs=args.n, alpha=alpha,
                                          alternative="two-sided")
            _report(args, "achieved power", power, f"{metric} = {_fmt(eff)}",
                    f"n = {args.n}", f"α = {_fmt(alpha)} (two-sided)",
                    plain=(f"With n={args.n}, a correlation test has approximately {_fmt(power)} "
                           f"power to detect r={_fmt(eff)} at α={_fmt(alpha)}."))
        else:
            eff = power_cls.solve_power(effect_size=None, power=args.power, nobs=args.n,
                                         alpha=alpha, alternative="two-sided")
            _report(args, "minimum detectable r", eff, f"n = {args.n}",
                    f"power = {_fmt(args.power)}", f"α = {_fmt(alpha)} (two-sided)",
                    plain=(f"With n={args.n} and {_fmt(args.power)} power, the minimum detectable "
                           f"correlation at α={_fmt(alpha)} is approximately r={_fmt(eff)}."))

    # ---- regression
    elif args.test == "regression":
        power_cls = FTestPowerF2()
        metric = "Cohen's f²"
        eff = args.f2
        if eff is None and solve != "mde":
            p.error("--f2 (Cohen's f²) is required for regression.")
        # F-test for regression: numerator df = number of predictors (default 1).
        # --k defaults to 2 (for ANOVA); for regression use 1 unless the user explicitly
        # passes a value > 1. We detect "explicitly passed" via command-line presence.
        k_raw = _explicit_arg("k")
        df_num = k_raw if k_raw is not None and k_raw > 1 else 1
        if solve == "n":
            # Solve for residual df, then n = resid_df + df_num + ncc(=1).
            resid_df = power_cls.solve_power(effect_size=eff, power=args.power,
                                             df_num=df_num, alpha=alpha)
            n_total = int(math.ceil(resid_df)) + df_num + 1
            _report(args, "n total", n_total, f"{metric} = {_fmt(eff)}",
                    f"df_num = {df_num} predictors", f"power = {_fmt(args.power)}", f"α = {_fmt(alpha)}",
                    plain=(f"A multiple regression ({df_num} predictor(s)) detecting {metric}={_fmt(eff)} "
                           f"at α={_fmt(alpha)} with {_fmt(args.power)} power requires approximately "
                           f"{n_total} participants."))
        elif solve == "power":
            resid_df = args.n - df_num - 1
            if resid_df < 1:
                p.error(f"n={args.n} is too small for {df_num} predictor(s) (need n > {df_num + 1}).")
            power = power_cls.solve_power(effect_size=eff, df_num=df_num, df_denom=resid_df,
                                          alpha=alpha)
            _report(args, "achieved power", power, f"{metric} = {_fmt(eff)}",
                    f"n = {args.n}", f"df_num = {df_num} predictors", f"α = {_fmt(alpha)}",
                    plain=(f"With n={args.n}, a regression ({df_num} predictor(s)) has approximately "
                           f"{_fmt(power)} power to detect {metric}={_fmt(eff)} at α={_fmt(alpha)}."))
        else:
            resid_df = args.n - df_num - 1
            if resid_df < 1:
                p.error(f"n={args.n} is too small for {df_num} predictor(s) (need n > {df_num + 1}).")
            eff = power_cls.solve_power(effect_size=None, power=args.power, df_num=df_num,
                                        df_denom=resid_df, alpha=alpha)
            _report(args, "minimum detectable f²", eff, f"n = {args.n}",
                    f"df_num = {df_num} predictors", f"power = {_fmt(args.power)}", f"α = {_fmt(alpha)}",
                    plain=(f"With n={args.n} and {_fmt(args.power)} power, the minimum detectable "
                           f"{metric} at α={_fmt(alpha)} is approximately f²={_fmt(eff)}."))

    if args.fmri:
        print()
        print("fMRI note: cluster/voxel-level power is approximate. This estimate covers the "
              "behavioral-design sample size; for fMRI, state smoothness, cluster-forming "
              "threshold, and effect location explicitly and treat as a planning estimate.")

    return 0


def _report(args, what, value, *assumptions, plain=""):
    print("=" * 60)
    print(f"  Power analysis — {args.test}")
    print("=" * 60)
    print(f"  Result: {what} = {value}")
    print("  Assumptions:")
    for a in assumptions:
        print(f"    - {a}")
    if plain:
        print()
        print(f"  {plain}")
    print("=" * 60)


if __name__ == "__main__":
    sys.exit(main())
