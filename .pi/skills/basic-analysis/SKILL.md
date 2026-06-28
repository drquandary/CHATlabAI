---
name: basic-analysis
description: "Run statistics and analyze this data — t-test (independent, paired), ANOVA (one-way, repeated measures), correlation, regression, mixed model, mixed-effects, lme4, afex. Computes descriptives, assumption checks (Shapiro-Wilk normality, Levene homogeneity, Mauchly sphericity), and tidy reporting into stats-report.md + results.csv. Present global/omnibus results before local contrasts; mark small-sample local effects exploratory per Chatterjee rule 6."
---

# basic-analysis

## Purpose

Descriptive statistics + standard inferential tests with assumption checks, reported in a tidy,
manuscript-ready format. Python handles t-tests, ANOVA, correlation, and regression; R handles
mixed-effects models.

## When to use

- "analyze this data", "run stats", "t-test", "ANOVA", "mixed model", "correlation", "regression"
- You have a CSV and need descriptives + a significance test with assumption checks
- You need a mixed-effects / repeated-measures model (R path)

## Behavior

- Compute descriptives (n, mean, SD, median, min, max) per group/condition.
- Run the requested test via pingouin (t-tests, ANOVA, correlation) or statsmodels (regression).
- **Assumption checks reported alongside results**:
  - Normality: Shapiro-Wilk per group.
  - Homogeneity of variance: Levene's test.
  - Sphericity (repeated measures): Mauchly's test (pingouin reports this in `eps` columns).
- **Per Chatterjee writing rule 6**: present global/omnibus results (overall F, main effects)
  *before* any local contrasts (post-hoc, pairwise). Mark small-sample local effects exploratory.
- Emit `stats-report.md` (human-readable) and `results.csv` (tidy machine-readable).

## Usage

### Python (t-test, ANOVA, correlation, regression)

```bash
# Independent t-test
python3 scripts/analyze.py --data data.csv --test ttest_ind --dv score --group group --out stats-report.md

# Paired t-test
python3 scripts/analyze.py --data data.csv --test ttest_paired --dv score --group group --subject id --out stats-report.md

# One-way ANOVA
python3 scripts/analyze.py --data data.csv --test anova --dv score --iv group --out stats-report.md

# Correlation
python3 scripts/analyze.py --data data.csv --test correlation --dv score --iv other_var --out stats-report.md

# Linear regression
python3 scripts/analyze.py --data data.csv --test regression --dv score --iv predictor --out stats-report.md
```

### R (mixed-effects models)

```bash
# Random intercept by subject
Rscript scripts/mixed.R --data data.csv --dv score --fixed condition --subject id

# Multiple fixed effects + random slope
Rscript scripts/mixed.R --data data.csv --dv score --fixed "condition+session" --subject id --random "condition|id"
```

## Scripts

- `scripts/analyze.py` — Python inferential tests (pingouin + statsmodels). `--help` for all options.
- `scripts/mixed.R` — R mixed-effects models (afex + lme4). Degrades gracefully if R/packages missing.

## Safety

- Read-only on input data; writes only to the `--out` report and `results.csv`.
- No network. No destructive operations.
- Fails with a clear message if a required package is missing.

## Dependencies

Python: `pandas pingouin statsmodels scipy numpy` · R: `afex lme4 ggplot2`
