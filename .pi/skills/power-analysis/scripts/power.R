#!/usr/bin/env Rscript
# Power analysis (analytic + simulation) — pwr + simr/lme4.
# Companion to power.py (cross-check).
#
# Usage:
#   Rscript power.R --test two.sample.t --d 0.5 --power 0.8
#   Rscript power.R --test paired.t       --d 0.5 --power 0.8
#   Rscript power.R --test anova          --f 0.25 --k 3 --power 0.8
#   Rscript power.R --test correlation    --r 0.3 --power 0.8
#   Rscript power.R --test regression     --f2 0.15 --power 0.8
#   Rscript power.R --test two.sample.t --d 0.5 --n 64            # power given n
#   Rscript power.R --test mixed.sim --help                      # simr example (documented)

# ---- minimal argument parser (avoid optparse dependency) -------------------
args <- commandArgs(trailingOnly = TRUE)

get_arg <- function(name, default = NA) {
  idx <- which(args == name)
  if (length(idx) == 0) return(default)
  if (idx == length(args)) return(default)
  args[idx + 1]
}
has_flag <- function(name) name %in% args

print_usage <- function() {
  cat("Usage: Rscript power.R --test <TYPE> [options]\n")
  cat("\nTypes: two.sample.t, paired.t, anova, correlation, regression, mixed.sim\n")
  cat("\nOptions:\n")
  cat("  --d <float>      Cohen's d (t-tests)\n")
  cat("  --f <float>      Cohen's f (ANOVA)\n")
  cat("  --f2 <float>     Cohen's f^2 (regression)\n")
  cat("  --r <float>      correlation r\n")
  cat("  --k <int>        number of groups (ANOVA, default 2)\n")
  cat("  --power <float>  target power (e.g. 0.80)\n")
  cat("  --n <int>        sample size per group\n")
  cat("  --alpha <float>  significance level (default 0.05)\n")
  cat("  --fmri           append fMRI cluster/voxel power caveat\n")
  cat("  --help           show this message\n")
  cat("\nProvide exactly two of: effect size, --power, --n.\n")
  cat("( --d 0.5 --power 0.8 => n;  --d 0.5 --n 64 => power;  --power 0.8 --n 64 => MDE )\n")
}

if (length(args) == 0 || has_flag("--help") || has_flag("-h")) {
  print_usage()
  if (length(args) > 0 && (has_flag("--help") || has_flag("-h")) && "--test" %in% args) {
    test <- get_arg("--test", "")
    if (test == "mixed.sim") {
      cat("\n--- mixed.sim (simr example) ---\n")
      cat("Estimates power for a repeated-measures mixed-effects model via simulation.\n")
      cat("Builds an lme4::lmer model with a fixed effect, sets its effect size, then uses\n")
      cat("simr::powerCurve to estimate power across sample sizes.\n")
      cat("Requires R packages: lme4, simr (and lmerTest optional).\n\n")
      cat("Example model (repeated-measures aesthetics paradigm):\n")
      cat("  rating ~ condition + (1 + condition | subject) + (1 | item)\n")
      cat("  condition effect coded; fixed effect size set via fixef(model)['condition'] <- d\n")
      cat("  powerCurve extends the number of subjects.\n\n")
      cat("To run: Rscript power.R --test mixed.sim --d 0.4 --n 30\n")
    }
  }
  quit(status = 0)
}

test <- get_arg("--test", NA)
if (is.na(test)) {
  cat("ERROR: --test is required. Use --help for usage.\n")
  quit(status = 2)
}

alpha <- as.numeric(get_arg("--alpha", "0.05"))
power_target <- as.numeric(get_arg("--power", NA))
n_given <- as.integer(get_arg("--n", NA))
d <- as.numeric(get_arg("--d", NA))
f <- as.numeric(get_arg("--f", NA))
f2 <- as.numeric(get_arg("--f2", NA))
r <- as.numeric(get_arg("--r", NA))
k <- as.integer(get_arg("--k", "2"))
fmri <- has_flag("--fmri")

report <- function(test, what, value, assumptions, plain) {
  cat(strrep("=", 60), "\n")
  cat(sprintf("  Power analysis (R) - %s\n", test))
  cat(strrep("=", 60), "\n")
  cat(sprintf("  Result: %s = %s\n", what, value))
  cat("  Assumptions:\n")
  for (a in assumptions) cat(sprintf("    - %s\n", a))
  cat("\n")
  cat(sprintf("  %s\n", plain))
  cat(strrep("=", 60), "\n")
  if (fmri) {
    cat("\nfMRI note: cluster/voxel-level power is approximate. State smoothness,\n")
    cat("cluster-forming threshold, and effect location explicitly; treat as planning estimate.\n")
  }
}

# ---- check for pwr (analytic cases) ---------------------------------------
need_pwr <- test %in% c("two.sample.t", "paired.t", "anova", "correlation", "regression")
if (need_pwr && !requireNamespace("pwr", quietly = TRUE)) {
  cat("ERROR: R package 'pwr' is not installed.\n", file = "")
  cat("       Install with:  install.packages(\"pwr\")\n")
  cat("       (CHATLabAI install.sh attempts to install pwr into the R user library.)\n")
  cat("       The Python script power.py covers the same analytic cases as a fallback:\n")
  cat("         python3 power.py --test ", test, sep = "", "\n")
  quit(status = 2)
}

# ---- determine what to solve for ------------------------------------------
solve <- NA
have_effect <- !is.na(d) || !is.na(f) || !is.na(f2) || !is.na(r)
if (have_effect && !is.na(power_target) && is.na(n_given)) solve <- "n"
else if (have_effect && !is.na(n_given) && is.na(power_target)) solve <- "power"
else if (!have_effect && !is.na(power_target) && !is.na(n_given)) solve <- "mde"
else if (test == "mixed.sim") solve <- "sim"
else {
  cat("ERROR: provide exactly two of: effect size, --power, --n.\n")
  cat("       ( --d 0.5 --power 0.8 => n;  --d 0.5 --n 64 => power;  --power 0.8 --n 64 => MDE )\n")
  quit(status = 2)
}

# ---- analytic cases via pwr -----------------------------------------------
if (test %in% c("two.sample.t", "paired.t")) {
  if (is.na(d) && solve != "mde") { cat("ERROR: --d (Cohen's d) required.\n"); quit(status = 2) }
  if (solve == "n") {
    res <- if (test == "two.sample.t") pwr::pwr.t.test(d = d, power = power_target, sig.level = alpha, type = "two.sample")
           else pwr::pwr.t.test(d = d, power = power_target, sig.level = alpha, type = "paired")
    nval <- ceiling(res$n)
    report(test, "n per group", nval,
           c(sprintf("Cohen's d = %.3f", d), sprintf("power = %.3f", power_target),
             sprintf("alpha = %.3f (two-sided)", alpha)),
           sprintf("A %s detecting d=%.3f at alpha=%.3f (two-sided) with %.0f%% power requires approximately %g participants per group.",
                   test, d, alpha, power_target * 100, nval))
  } else if (solve == "power") {
    res <- if (test == "two.sample.t") pwr::pwr.t.test(d = d, n = n_given, sig.level = alpha, type = "two.sample")
           else pwr::pwr.t.test(d = d, n = n_given, sig.level = alpha, type = "paired")
    report(test, "achieved power", round(res$power, 3),
           c(sprintf("Cohen's d = %.3f", d), sprintf("n = %g per group", n_given),
             sprintf("alpha = %.3f (two-sided)", alpha)),
           sprintf("With n=%g per group, a %s has approximately %.1f%% power to detect d=%.3f at alpha=%.3f.",
                   n_given, test, res$power * 100, d, alpha))
  } else {
    res <- if (test == "two.sample.t") pwr::pwr.t.test(power = power_target, n = n_given, sig.level = alpha, type = "two.sample")
           else pwr::pwr.t.test(power = power_target, n = n_given, sig.level = alpha, type = "paired")
    report(test, "minimum detectable d", round(res$d, 3),
           c(sprintf("n = %g per group", n_given), sprintf("power = %.3f", power_target),
             sprintf("alpha = %.3f (two-sided)", alpha)),
           sprintf("With n=%g per group and %.0f%% power, the minimum detectable d at alpha=%.3f is approximately %.3f.",
                   n_given, power_target * 100, alpha, res$d))
  }

} else if (test == "anova") {
  if (is.na(f) && solve != "mde") { cat("ERROR: --f (Cohen's f) required.\n"); quit(status = 2) }
  if (solve == "n") {
    res <- pwr::pwr.anova.test(k = k, f = f, power = power_target, sig.level = alpha)
    nval <- ceiling(res$n)
    report(test, "n per group", nval,
           c(sprintf("Cohen's f = %.3f", f), sprintf("k = %g groups", k),
             sprintf("power = %.3f", power_target), sprintf("alpha = %.3f", alpha)),
           sprintf("A one-way ANOVA (k=%g) detecting f=%.3f at alpha=%.3f with %.0f%% power requires ~%g/group (N=%g).",
                   k, f, alpha, power_target * 100, nval, nval * k))
  } else if (solve == "power") {
    res <- pwr::pwr.anova.test(k = k, f = f, n = n_given, sig.level = alpha)
    report(test, "achieved power", round(res$power, 3),
           c(sprintf("Cohen's f = %.3f", f), sprintf("k = %g groups", k),
             sprintf("n = %g per group", n_given), sprintf("alpha = %.3f", alpha)),
           sprintf("With n=%g/group (k=%g), a one-way ANOVA has ~%.1f%% power to detect f=%.3f at alpha=%.3f.",
                   n_given, k, res$power * 100, f, alpha))
  } else {
    res <- pwr::pwr.anova.test(k = k, power = power_target, n = n_given, sig.level = alpha)
    report(test, "minimum detectable f", round(res$f, 3),
           c(sprintf("k = %g groups", k), sprintf("n = %g per group", n_given),
             sprintf("power = %.3f", power_target), sprintf("alpha = %.3f", alpha)),
           sprintf("With n=%g/group (k=%g) and %.0f%% power, the minimum detectable f at alpha=%.3f is ~%.3f.",
                   n_given, k, power_target * 100, alpha, res$f))
  }

} else if (test == "correlation") {
  if (is.na(r) && solve != "mde") { cat("ERROR: --r required.\n"); quit(status = 2) }
  if (solve == "n") {
    res <- pwr::pwr.r.test(r = r, power = power_target, sig.level = alpha)
    nval <- ceiling(res$n)
    report(test, "n total", nval,
           c(sprintf("r = %.3f", r), sprintf("power = %.3f", power_target),
             sprintf("alpha = %.3f (two-sided)", alpha)),
           sprintf("A correlation test detecting r=%.3f at alpha=%.3f with %.0f%% power requires ~%g participants.",
                   r, alpha, power_target * 100, nval))
  } else if (solve == "power") {
    res <- pwr::pwr.r.test(r = r, n = n_given, sig.level = alpha)
    report(test, "achieved power", round(res$power, 3),
           c(sprintf("r = %.3f", r), sprintf("n = %g", n_given),
             sprintf("alpha = %.3f (two-sided)", alpha)),
           sprintf("With n=%g, a correlation test has ~%.1f%% power to detect r=%.3f at alpha=%.3f.",
                   n_given, res$power * 100, r, alpha))
  } else {
    res <- pwr::pwr.r.test(power = power_target, n = n_given, sig.level = alpha)
    report(test, "minimum detectable r", round(res$r, 3),
           c(sprintf("n = %g", n_given), sprintf("power = %.3f", power_target),
             sprintf("alpha = %.3f (two-sided)", alpha)),
           sprintf("With n=%g and %.0f%% power, the minimum detectable r at alpha=%.3f is ~%.3f.",
                   n_given, power_target * 100, alpha, res$r))
  }

} else if (test == "regression") {
  if (is.na(f2) && solve != "mde") { cat("ERROR: --f2 (Cohen's f^2) required.\n"); quit(status = 2) }
  u <- 1  # numerator df = one predictor
  if (solve == "n") {
    res <- pwr::pwr.f2.test(u = u, f2 = f2, power = power_target, sig.level = alpha)
    nval <- ceiling(res$v) + u + 1
    report(test, "n total", nval,
           c(sprintf("Cohen's f^2 = %.3f", f2), sprintf("u = %g (predictors)", u),
             sprintf("power = %.3f", power_target), sprintf("alpha = %.3f", alpha)),
           sprintf("A regression (1 predictor) detecting f^2=%.3f at alpha=%.3f with %.0f%% power requires ~%g participants.",
                   f2, alpha, power_target * 100, nval))
  } else if (solve == "power") {
    v <- n_given - u - 1
    res <- pwr::pwr.f2.test(u = u, f2 = f2, v = v, sig.level = alpha)
    report(test, "achieved power", round(res$power, 3),
           c(sprintf("Cohen's f^2 = %.3f", f2), sprintf("u = %g", u), sprintf("n = %g", n_given),
             sprintf("alpha = %.3f", alpha)),
           sprintf("With n=%g, a regression (1 predictor) has ~%.1f%% power to detect f^2=%.3f at alpha=%.3f.",
                   n_given, res$power * 100, f2, alpha))
  } else {
    v <- n_given - u - 1
    res <- pwr::pwr.f2.test(u = u, power = power_target, v = v, sig.level = alpha)
    report(test, "minimum detectable f^2", round(res$f2, 3),
           c(sprintf("u = %g", u), sprintf("n = %g", n_given), sprintf("power = %.3f", power_target),
             sprintf("alpha = %.3f", alpha)),
           sprintf("With n=%g and %.0f%% power, the minimum detectable f^2 at alpha=%.3f is ~%.3f.",
                   n_given, power_target * 100, alpha, res$f2))
  }

} else if (test == "mixed.sim") {
  # ---- simulation-based power for a repeated-measures mixed model (simr) ----
  # Requires lme4 + simr. Documented example for repeated-measures aesthetics paradigms
  # (subjects rating stimuli across conditions).
  if (!requireNamespace("lme4", quietly = TRUE) || !requireNamespace("simr", quietly = TRUE)) {
    cat("ERROR: R packages 'lme4' and/or 'simr' are not installed.\n")
    cat("       Install with:  install.packages(c(\"lme4\",\"simr\"))\n")
    cat("       (CHATLabAI install.sh attempts to install these into the R user library.)\n")
    cat("       The analytic cases (two.sample.t, anova, etc.) do not require simr.\n")
    quit(status = 2)
  }
  d_sim <- if (!is.na(d)) d else 0.4
  n_sim <- if (!is.na(n_given)) as.integer(n_given) else 30L

  suppressPackageStartupMessages({
    library(lme4)
    library(simr)
  })

  # Build a pilot mixed-effects model for a repeated-measures design:
  #   rating ~ condition + (1 + condition | subject) + (1 | item)
  # 'condition' is effect-coded (-0.5, 0.5). We set the fixed effect (slope) to d_sim
  # to represent the target effect size, then use simr::powerCurve to extend subjects.
  #
  # This is a synthetic pilot (no data file needed) — appropriate when planning a study
  # before data collection.
  set.seed(42)
  n_subj <- n_sim
  n_item <- 20
  dat <- expand.grid(subject = factor(seq_len(n_subj)),
                     item = factor(seq_len(n_item)),
                     condition = c(-0.5, 0.5))
  dat$rating <- rnorm(nrow(dat), mean = 0, sd = 1)

  model <- lmer(rating ~ condition + (1 + condition | subject) + (1 | item), data = dat)

  # Set the fixed effect to the target effect size (Cohen's d on the effect-coded slope).
  fixef(model)["condition"] <- d_sim

  # Power curve: extend the number of subjects from the pilot n upward.
  pc <- powerCurve(model, along = "subject", breaks = c(n_subj, n_subj + 10, n_subj + 20, n_subj + 30),
                   nsim = 100)

  cat(strrep("=", 60), "\n")
  cat("  Power analysis (R) - mixed.sim (simr)\n")
  cat(strrep("=", 60), "\n")
  cat(sprintf("  Model: rating ~ condition + (1 + condition | subject) + (1 | item)\n"))
  cat(sprintf("  Fixed effect 'condition' set to d = %.3f\n", d_sim))
  cat(sprintf("  Pilot: %g subjects x %g items x 2 conditions\n", n_subj, n_item))
  cat(sprintf("  nsim = 100\n"))
  cat("  Power curve (by number of subjects):\n")
  print(pc)
  cat("\n")
  cat("  NOTE: This is a simulation-based estimate for a repeated-measures mixed model.\n")
  cat("  Increase nsim for tighter estimates. Report the curve, not a single number.\n")
  if (fmri) {
    cat("\nfMRI note: cluster/voxel-level power is approximate. State smoothness,\n")
    cat("cluster-forming threshold, and effect location explicitly.\n")
  }
  cat(strrep("=", 60), "\n")

} else {
  cat("ERROR: unknown --test '", test, "'. Use --help.\n", sep = "")
  quit(status = 2)
}
