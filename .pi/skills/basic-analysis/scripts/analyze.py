#!/usr/bin/env python3
"""CHATLabAI basic-analysis: descriptives + inferential tests with assumption checks.

Usage:
  python3 analyze.py --data data.csv --test ttest_ind  --dv score --group group
  python3 analyze.py --data data.csv --test ttest_paired --dv score --group group --subject id
  python3 analyze.py --data data.csv --test anova --dv score --iv group
  python3 analyze.py --data data.csv --test correlation --dv score --iv other
  python3 analyze.py --data data.csv --test regression --dv score --iv predictor

Emits a human-readable stats-report.md (--out) and a tidy results.csv.
Presents global/omnibus results before local contrasts (Chatterjee rule 6).
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------- imports
def _need(pkg: str):
    try:
        return __import__(pkg)
    except ImportError:
        print(f"ERROR: required package '{pkg}' is not installed.\n"
              f"Install it with:  python3 -m pip install {pkg}\n"
              f"Or run the workspace installer:  ./install.sh", file=sys.stderr)
        sys.exit(2)

pd = _need("pandas")
np = _need("numpy")
# scipy.stats — import the module so stats.shapiro / stats.levene etc. resolve
import scipy.stats as stats

# pingouin is optional but preferred for t-test/ANOVA; fall back to scipy.
try:
    import pingouin as pg
    HAVE_PG = True
except ImportError:
    HAVE_PG = False

# statsmodels for regression
try:
    import statsmodels.formula.api as smf
    import statsmodels.api as sm
    HAVE_SM = True
except ImportError:
    HAVE_SM = False


# ---------------------------------------------------------------- helpers
def descriptives(df: "pd.DataFrame", dv: str, groupcol: str | None = None):
    """Return a tidy descriptives table. If groupcol given, per-group; else overall."""
    rows = []
    if groupcol and groupcol in df.columns:
        for g, sub in df.groupby(groupcol):
            s = sub[dv].dropna()
            rows.append(_desc_row(s, label=str(g)))
        # overall
        rows.append(_desc_row(df[dv].dropna(), label="Overall"))
    else:
        rows.append(_desc_row(df[dv].dropna(), label="Overall"))
    return pd.DataFrame(rows)


def _desc_row(s: "pd.Series", label: str) -> dict:
    return {
        "group": label,
        "n": int(s.count()),
        "mean": round(float(s.mean()), 4),
        "sd": round(float(s.std(ddof=1)), 4) if s.count() > 1 else float("nan"),
        "median": round(float(s.median()), 4),
        "min": round(float(s.min()), 4),
        "max": round(float(s.max()), 4),
    }


def shapiro_by_group(df, dv, groupcol):
    """Shapiro-Wilk normality test per group. Returns list of dicts."""
    out = []
    if groupcol and groupcol in df.columns:
        for g, sub in df.groupby(groupcol):
            s = sub[dv].dropna()
            if len(s) >= 3:
                W, p = stats.shapiro(s)
                out.append({"test": "Shapiro-Wilk (normality)", "group": str(g),
                            "n": int(len(s)), "statistic": round(W, 4),
                            "p": _fmt_p(p), "pass": "yes" if p > 0.05 else "NO"})
    s = df[dv].dropna()
    if len(s) >= 3:
        W, p = stats.shapiro(s)
        out.append({"test": "Shapiro-Wilk (normality)", "group": "Overall",
                    "n": int(len(s)), "statistic": round(W, 4),
                    "p": _fmt_p(p), "pass": "yes" if p > 0.05 else "NO"})
    return out


def levene_test(df, dv, groupcol):
    """Levene's homogeneity of variance across groups."""
    groups = [sub[dv].dropna().values for _, sub in df.groupby(groupcol)]
    groups = [g for g in groups if len(g) >= 2]
    if len(groups) < 2:
        return None
    W, p = stats.levene(*groups, center="median")
    return {"test": "Levene (homogeneity)", "group": "—",
            "n": int(sum(len(g) for g in groups)),
            "statistic": round(W, 4), "p": _fmt_p(p),
            "pass": "yes" if p > 0.05 else "NO"}


def _fmt_p(p):
    if p < 0.001:
        return "<0.001"
    return round(float(p), 4)


def _assumption_table(rows):
    if not rows:
        return "_No assumption checks applicable for this test/design._"
    return pd.DataFrame(rows).to_markdown(index=False)


# ---------------------------------------------------------------- tests
def run_ttest_ind(df, dv, group):
    groups = sorted(df[group].dropna().unique())
    if len(groups) != 2:
        sys.exit(f"ERROR: ttest_ind needs exactly 2 groups in '{group}'; found {len(groups)}: {groups}")
    a = df.loc[df[group] == groups[0], dv].dropna()
    b = df.loc[df[group] == groups[1], dv].dropna()
    # assumption checks
    assum = shapiro_by_group(df, dv, group)
    lev = levene_test(df, dv, group)
    if lev:
        assum.append(lev)
    # test
    if HAVE_PG:
        res = pg.ttest(a, b, correction="auto")
        t = float(res["T"].iloc[0]); p = float(res["p-val"].iloc[0])
        dof = float(res["dof"].iloc[0])
        eff = float(res["cohen-d"].iloc[0])
        ci = res.get("CI95%")
        ci_str = str(ci.iloc[0]) if ci is not None else "—"
        alt = "Welch" if bool(res.get("Tail", False)) else "Student"
    else:
        lev_ok = lev and lev["pass"] == "yes"
        t, p = stats.ttest_ind(a, b, equal_var=lev_ok)
        dof = (len(a) + len(b) - 2) if lev_ok else None
        # cohen's d
        pooled = math.sqrt(((len(a)-1)*a.var(ddof=1) + (len(b)-1)*b.var(ddof=1)) / (len(a)+len(b)-2))
        eff = (a.mean() - b.mean()) / pooled if pooled else float("nan")
        ci_str = "—"; alt = "Student" if lev_ok else "Welch"
    results = [{
        "test": f"Independent t-test ({alt})", "comparison": f"{groups[0]} vs {groups[1]}",
        "statistic": round(t, 4), "p": _fmt_p(p),
        "effect_size": f"d={round(eff,4)}", "dof": round(dof,4) if dof is not None else "—",
        "CI95": ci_str,
    }]
    return results, assum, {"global": results, "local": []}


def run_ttest_paired(df, dv, group, subject):
    groups = sorted(df[group].dropna().unique())
    if len(groups) != 2:
        sys.exit(f"ERROR: ttest_paired needs exactly 2 groups in '{group}'; found {len(groups)}")
    wide = df.pivot_table(index=subject, columns=group, values=dv).dropna()
    a, b = wide[groups[0]], wide[groups[1]]
    diff = a - b
    # assumption: normality of differences
    assum = []
    if len(diff) >= 3:
        W, p = stats.shapiro(diff)
        assum.append({"test": "Shapiro-Wilk (normality of differences)", "group": "—",
                      "n": int(len(diff)), "statistic": round(W,4),
                      "p": _fmt_p(p), "pass": "yes" if p > 0.05 else "NO"})
    if HAVE_PG:
        res = pg.ttest(a, b, paired=True)
        t = float(res["T"].iloc[0]); p = float(res["p-val"].iloc[0])
        dof = float(res["dof"].iloc[0]); eff = float(res["cohen-d"].iloc[0])
        ci = res.get("CI95%"); ci_str = str(ci.iloc[0]) if ci is not None else "—"
    else:
        t, p = stats.ttest_rel(a, b)
        dof = len(a) - 1; eff = diff.mean() / diff.std(ddof=1) if diff.std(ddof=1) else float("nan")
        ci_str = "—"
    results = [{
        "test": "Paired t-test", "comparison": f"{groups[0]} vs {groups[1]}",
        "statistic": round(t, 4), "p": _fmt_p(p),
        "effect_size": f"d={round(eff,4)}", "dof": round(dof,4), "CI95": ci_str,
    }]
    return results, assum, {"global": results, "local": []}


def run_anova(df, dv, iv):
    groups = sorted(df[iv].dropna().unique())
    # assumption checks
    assum = shapiro_by_group(df, dv, iv)
    lev = levene_test(df, dv, iv)
    if lev:
        assum.append(lev)
    # omnibus (GLOBAL — rule 6)
    if HAVE_PG:
        res = pg.anova(dv=dv, between=iv, data=df, detailed=True)
        F = float(res["F"].iloc[0]); p = float(res["p-unc"].iloc[0])
        ddof1 = float(res["DF"].iloc[0]); ddof2 = float(res["DF"].iloc[1])
        # partial eta-squared (np2)
        eta = float(res["np2"].iloc[0])
    else:
        gvals = [sub[dv].dropna().values for _, sub in df.groupby(iv)]
        F, p = stats.f_oneway(*gvals)
        ddof1 = len(gvals) - 1
        ddof2 = sum(len(g) for g in gvals) - len(gvals)
        # eta-squared
        grand = df[dv].mean()
        ss_between = sum(len(g) * (g.mean() - grand)**2 for g in gvals)
        ss_total = ((df[dv] - grand)**2).sum()
        eta = ss_between / ss_total if ss_total else float("nan")
    global_res = [{
        "test": "One-way ANOVA (omnibus)", "comparison": f"{len(groups)} groups: {', '.join(map(str,groups))}",
        "statistic": f"F({int(ddof1)},{int(ddof2)})={round(F,4)}", "p": _fmt_p(p),
        "effect_size": f"η²={round(eta,4)}", "dof": "—", "CI95": "—",
    }]
    # post-hoc (LOCAL — rule 6) — only if omnibus significant & small-sample caveat
    local_res = []
    if p < 0.05 and HAVE_PG and len(groups) > 2:
        pt = pg.pairwise_tests(dv=dv, between=iv, data=df, padjust="bonf")
        for _, r in pt.iterrows():
            local_res.append({
                "test": "Pairwise (Bonferroni) [LOCAL/exploratory]",
                "comparison": f"{r.get('A','?')} vs {r.get('B','?')}",
                "statistic": f"t={round(float(r['T']),4)}", "p": _fmt_p(float(r['p-corr'])),
                "effect_size": f"hedges={round(float(r['hedges']),4)}", "dof": round(float(r['dof']),4), "CI95": "—",
            })
    small_sample = any(len(df.loc[df[iv]==g]) < 30 for g in groups)
    return global_res, assum, {"global": global_res, "local": local_res,
                               "small_sample_local": small_sample}


def run_correlation(df, dv, iv):
    a, b = df[dv].dropna(), df[iv].dropna()
    pair = df[[dv, iv]].dropna()
    assum = []
    if len(pair) >= 3:
        for col, name in [(dv, dv), (iv, iv)]:
            W, p = stats.shapiro(pair[col])
            assum.append({"test": "Shapiro-Wilk (normality)", "group": name,
                          "n": int(len(pair)), "statistic": round(W,4),
                          "p": _fmt_p(p), "pass": "yes" if p > 0.05 else "NO"})
    r, p = stats.pearsonr(pair[dv], pair[iv])
    try:
        sr, sp = stats.spearmanr(pair[dv], pair[iv])
    except Exception:
        sr, sp = float("nan"), float("nan")
    results = [{
        "test": "Pearson correlation", "comparison": f"{dv} ~ {iv}",
        "statistic": f"r={round(r,4)}", "p": _fmt_p(p),
        "effect_size": f"r²={round(r*r,4)}", "dof": int(len(pair)-2), "CI95": "—",
    }]
    if not math.isnan(sr):
        results.append({
            "test": "Spearman correlation", "comparison": f"{dv} ~ {iv}",
            "statistic": f"ρ={round(sr,4)}", "p": _fmt_p(sp),
            "effect_size": "—", "dof": int(len(pair)-2), "CI95": "—",
        })
    return results, assum, {"global": results, "local": []}


def run_regression(df, dv, iv):
    if not HAVE_SM:
        sys.exit("ERROR: statsmodels is required for regression. Install: python3 -m pip install statsmodels")
    model = smf.ols(f"{dv} ~ {iv}", data=df).fit()
    assum = []
    # normality of residuals
    resid = model.resid
    if len(resid) >= 3:
        W, p = stats.shapiro(resid)
        assum.append({"test": "Shapiro-Wilk (residual normality)", "group": "—",
                      "n": int(len(resid)), "statistic": round(W,4),
                      "p": _fmt_p(p), "pass": "yes" if p > 0.05 else "NO"})
    results = []
    # omnibus model F (GLOBAL)
    results.append({
        "test": "Regression (omnibus F)", "comparison": f"{dv} ~ {iv}",
        "statistic": f"F({int(model.df_model)},{int(model.df_resid)})={round(model.fvalue,4)}",
        "p": _fmt_p(model.f_pvalue), "effect_size": f"R²={round(model.rsquared,4)}",
        "dof": "—", "CI95": "—",
    })
    # coefficients (LOCAL)
    for name in model.params.index:
        results.append({
            "test": "Regression coefficient [LOCAL]",
            "comparison": f"{name}",
            "statistic": f"t={round(model.tvalues[name],4)}",
            "p": _fmt_p(model.pvalues[name]),
            "effect_size": f"β={round(model.params[name],4)}",
            "dof": int(model.df_resid), "CI95": f"[{round(model.conf_int().loc[name,0],4)},{round(model.conf_int().loc[name,1],4)}]",
        })
    return results, assum, {"global": results[:1], "local": results[1:],
                            "small_sample_local": len(df) < 30}


# ---------------------------------------------------------------- report
def write_report(out_path, test_name, df, dv, iv_group, desc, results_blocks, assum, small_note):
    lines = []
    lines.append("# Stats Report\n")
    lines.append(f"**Test:** {test_name}  ")
    lines.append(f"**DV:** {dv}  ")
    lines.append(f"**Predictor/Group:** {iv_group}  ")
    lines.append(f"**N:** {len(df)}\n")
    # descriptives
    lines.append("## Descriptives\n")
    lines.append(desc.to_markdown(index=False) + "\n")
    # assumptions
    lines.append("## Assumption checks\n")
    lines.append(_assumption_table(assum) + "\n")
    # rule 6 ordering: global before local
    gb = results_blocks
    lines.append("## Results\n")
    lines.append("### Global / omnibus (primary — Chatterjee rule 6)\n")
    lines.append(pd.DataFrame(gb["global"]).to_markdown(index=False) + "\n")
    if gb.get("local"):
        caveat = ""
        if small_note or gb.get("small_sample_local"):
            caveat = "  \n⚠️ **Small sample: local contrasts below are exploratory.**"
        lines.append("### Local contrasts (secondary / exploratory)\n")
        lines.append("Post-hoc and coefficient-level tests follow the omnibus result." + caveat + "\n")
        lines.append(pd.DataFrame(gb["local"]).to_markdown(index=False) + "\n")
    # rule 6 reminder
    lines.append("## Note (Chatterjee writing rule 6)\n")
    lines.append("Global/omnibus results are primary. Treat local/node-level effects as exploratory "
                 "unless the sample is large and stable.\n")
    Path(out_path).write_text("\n".join(lines))


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(
        description="CHATLabAI basic-analysis: descriptives + inferential tests with assumption checks.")
    ap.add_argument("--data", required=True, help="Path to CSV data file.")
    ap.add_argument("--test", required=True,
                    choices=["ttest_ind", "ttest_paired", "anova", "correlation", "regression"],
                    help="Type of test to run.")
    ap.add_argument("--dv", required=True, help="Dependent variable column.")
    ap.add_argument("--iv", help="Independent variable / predictor column (anova, correlation, regression).")
    ap.add_argument("--group", help="Grouping column (t-tests).")
    ap.add_argument("--subject", help="Subject/participant ID column (paired t-test).")
    ap.add_argument("--out", default="stats-report.md", help="Output report path (markdown).")
    args = ap.parse_args()

    data_path = Path(args.data)
    if not data_path.exists():
        sys.exit(f"ERROR: data file not found: {data_path}")
    df = pd.read_csv(data_path)

    # validate columns
    for needed, name in [(args.dv, "--dv"), (args.iv, "--iv"), (args.group, "--group"), (args.subject, "--subject")]:
        if needed and needed not in df.columns:
            sys.exit(f"ERROR: column '{needed}' (from {name}) not found in {data_path}. Columns: {list(df.columns)}")

    test = args.test
    if test == "ttest_ind":
        results, assum, blocks = run_ttest_ind(df, args.dv, args.group)
        iv_group = args.group
    elif test == "ttest_paired":
        if not args.subject:
            sys.exit("ERROR: --subject is required for ttest_paired.")
        results, assum, blocks = run_ttest_paired(df, args.dv, args.group, args.subject)
        iv_group = args.group
    elif test == "anova":
        if not args.iv:
            sys.exit("ERROR: --iv is required for anova.")
        results, assum, blocks = run_anova(df, args.dv, args.iv)
        iv_group = args.iv
    elif test == "correlation":
        if not args.iv:
            sys.exit("ERROR: --iv is required for correlation.")
        results, assum, blocks = run_correlation(df, args.dv, args.iv)
        iv_group = args.iv
    elif test == "regression":
        if not args.iv:
            sys.exit("ERROR: --iv is required for regression.")
        results, assum, blocks = run_regression(df, args.dv, args.iv)
        iv_group = args.iv
    else:
        sys.exit(f"ERROR: unknown test '{test}'")

    # descriptives: per-group only when the predictor is categorical (t-tests, anova);
    # overall-only for continuous predictors (correlation, regression)
    if test in ("correlation", "regression"):
        desc = descriptives(df, args.dv, groupcol=None)
    else:
        groupcol = args.group or args.iv
        desc = descriptives(df, args.dv, groupcol)

    # write report
    write_report(args.out, test, df, args.dv, iv_group, desc, blocks, assum,
                 blocks.get("small_sample_local", False))

    # tidy results.csv
    tidy = pd.DataFrame(results)
    tidy.insert(0, "dv", args.dv)
    tidy.insert(1, "predictor", iv_group)
    tidy.insert(2, "test_type", test)
    tidy.to_csv("results.csv", index=False)

    # console summary
    print(f"\n=== {test} ===")
    print(f"DV: {args.dv} | predictor/group: {iv_group} | N: {len(df)}")
    print("\n--- Descriptives ---")
    print(desc.to_string(index=False))
    print("\n--- Assumption checks ---")
    print(_assumption_table(assum))
    print("\n--- Results (global first, rule 6) ---")
    print(pd.DataFrame(blocks["global"]).to_string(index=False))
    if blocks.get("local"):
        print("\n--- Local contrasts (exploratory) ---")
        print(pd.DataFrame(blocks["local"]).to_string(index=False))
    print(f"\nReport written: {args.out}")
    print("Tidy results:  results.csv")


if __name__ == "__main__":
    main()
