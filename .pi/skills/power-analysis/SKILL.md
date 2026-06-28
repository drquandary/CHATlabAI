---
name: power-analysis
description: Power analysis and sample size estimation for behavioral and fMRI designs — analytic (t-test, ANOVA, correlation, regression) and simulation-based (mixed models). Use when asked "power analysis", "sample size", "how many participants", "minimum detectable effect", "power for a mixed model", "MDE", "how many subjects do I need".
---

# Power Analysis

## Purpose

Estimate sample size / power / minimum detectable effect (MDE) for behavioral and fMRI
designs used in the Chatterjee lab. Two engines:

- **Analytic** — `power.R` (R `pwr`) and `power.py` (Python `statsmodels`) for t-test, ANOVA,
  correlation, and regression. Cross-check each against the other.
- **Simulation** — `power.R` with `simr` on `lme4` mixed-effects models for repeated-measures
  aesthetics paradigms where analytic formulas don't apply (e.g., subjects × conditions × items).

Per lab writing **rule 6**: treat small-sample local effects as exploratory. Power analysis
makes the sample-size assumption explicit before data collection.

## When to use

- Planning a study and needing n per group.
- Checking achieved power for a fixed n.
- Estimating the smallest effect detectable at a given n.
- Mixed-effects / repeated-measures designs (use the simulation path).

## Usage

### Python (analytic; cross-check)

```bash
python3 .pi/skills/power-analysis/scripts/power.py --test two.sample.t --d 0.5 --power 0.8
python3 .pi/skills/power-analysis/scripts/power.py --test paired.t       --d 0.5 --power 0.8
python3 .pi/skills/power-analysis/scripts/power.py --test anova          --f 0.25 --k 3 --power 0.8
python3 .pi/skills/power-analysis/scripts/power.py --test correlation   --r 0.3 --power 0.8
python3 .pi/skills/power-analysis/scripts/power.py --test regression    --f2 0.15 --power 0.8
python3 .pi/skills/power-analysis/scripts/power.py --test two.sample.t --d 0.5 --n 64            # power given n
python3 .pi/skills/power-analysis/scripts/power.py --test two.sample.t --power 0.8 --n 64       # MDE given n+power
```

### R (analytic + simulation)

```bash
Rscript .pi/skills/power-analysis/scripts/power.R --test two.sample.t --d 0.5 --power 0.8
Rscript .pi/skills/power-analysis/scripts/power.R --test anova --f 0.25 --k 3 --power 0.8
Rscript .pi/skills/power-analysis/scripts/power.R --test mixed.sim --help    # simr example
```

Each script reports the requested quantity (n, power, or MDE), the assumptions used, and a
plain-language sentence. All scripts support `--help`.

## What each report contains

- The requested quantity (n per group, achieved power, or MDE).
- The design and effect-size metric (Cohen's d, f, f², r).
- Assumptions: α (default 0.05), power target (default 0.80), two-sided test, equal group sizes,
  normality / homoscedasticity where assumed.
- A plain-language sentence stating the result and its assumptions.

## fMRI note

Cluster/voxel-level power for fMRI is **approximate**. These scripts cover behavioral-design
sample size and simple analytic cases; for fMRI cluster power, state assumptions (smoothness,
cluster-forming threshold, effect location) explicitly and treat results as planning estimates,
not guarantees. The report prints this caveat when relevant.

## Simulation example (simr / lme4)

The `power.R --test mixed.sim` command runs a documented example of simulation-based power for
a repeated-measures mixed model — appropriate for aesthetics paradigms (subjects rating stimuli
across conditions). It builds an `lme4::lmer` model with a fixed effect of interest, sets its
effect size, then uses `simr::powerCurve` to estimate power across sample sizes. This path
requires R with `lme4` and `simr` installed; the script prints a clear message if they are
missing. See the example block in `power.R`.

## Safety

- Read-only: these scripts only compute and print; they never modify data.
- No network access required.
