#!/usr/bin/env Rscript
# CHATLabAI basic-analysis: mixed-effects models via afex + lme4.
#
# Usage:
#   Rscript mixed.R --data data.csv --dv score --fixed condition --subject id
#   Rscript mixed.R --data data.csv --dv score --fixed "condition+session" --subject id --random "condition|id"
#
# Degrades gracefully: if R, afex, or lme4 are missing, prints a clear message.
# Writes a mixed-report.md summary.

args <- commandArgs(trailingOnly = TRUE)

# ---- minimal arg parser (no optparse dependency) ----
get_arg <- function(name, default = NA_character_) {
  idx <- which(args == name)
  if (length(idx) == 0) return(default)
  if (idx == length(args)) return(default)
  args[idx + 1]
}

data_file <- get_arg("--data")
dv        <- get_arg("--dv")
fixed     <- get_arg("--fixed")
subject   <- get_arg("--subject")
random_eff <- get_arg("--random", NA_character_)
out_file  <- get_arg("--out", "mixed-report.md")

if (is.na(data_file) || is.na(dv) || is.na(fixed) || is.na(subject)) {
  cat("Usage: Rscript mixed.R --data data.csv --dv score --fixed condition --subject id [--random 'condition|id'] [--out mixed-report.md]\n")
  cat("  --data     CSV data file (required)\n")
  cat("  --dv       dependent variable column (required)\n")
  cat("  --fixed     fixed effects, e.g. 'condition' or 'condition+session' (required)\n")
  cat("  --subject   subject/participant ID column (required)\n")
  cat("  --random    random effect in lme4 syntax, e.g. 'condition|id' (default: intercept-only: '1|id')\n")
  cat("  --out       output report path (default: mixed-report.md)\n")
  quit(status = 0)
}

# ---- check packages ----
check_pkg <- function(pkg) {
  if (!requireNamespace(pkg, quietly = TRUE)) {
    cat(sprintf("ERROR: R package '%s' is not installed.\n", pkg))
    cat(sprintf("Install it with:  Rscript -e \"install.packages('%s', repos='https://cloud.r-project.org')\"\n", pkg))
    cat("Or run the workspace installer:  ./install.sh\n")
    FALSE
  } else {
    TRUE
  }
}

if (!check_pkg("lme4")) {
  cat("\nNOTE: lme4 is required for mixed-effects models.\n")
  cat("The Python analyze.py script can handle t-tests, ANOVA, correlation, and regression without R.\n")
  quit(status = 2)
}
have_afex <- check_pkg("afex")

suppressWarnings(suppressMessages({
  library(lme4)
  if (have_afex) library(afex)
}))

# ---- load data ----
if (!file.exists(data_file)) {
  cat(sprintf("ERROR: data file not found: %s\n", data_file))
  quit(status = 2)
}
df <- read.csv(data_file, stringsAsFactors = FALSE)
for (col in c(dv, subject, strsplit(fixed, "\\+")[[1]])) {
  if (!col %in% names(df)) {
    cat(sprintf("ERROR: column '%s' not found in %s. Columns: %s\n",
                col, data_file, paste(names(df), collapse = ", ")))
    quit(status = 2)
  }
}

# ---- build formula ----
if (is.na(random_eff)) {
  random_eff <- paste0("1|", subject)
}
# afex::mixed uses lme4-style random: (1|subject) or (condition|subject)
rand_formula <- sub("\\|", "|", random_eff)
if (!grepl("^\\s*\\(", rand_formula)) {
  # convert "1|id" -> "(1|id)"
  parts <- strsplit(rand_formula, "\\|")[[1]]
  rand_formula <- paste0("(", trimws(parts[1]), "|", trimws(parts[2]), ")")
}

fixed_terms <- paste(strsplit(fixed, "\\+")[[1]], collapse = " + ")
formula_str <- paste0(dv, " ~ ", fixed_terms, " + ", rand_formula)

cat(sprintf("Fitting mixed model: %s\n\n", formula_str))

# ---- fit ----
if (have_afex) {
  # afex::mixed gives omnibus LRT + p-values per effect (rule 6: global first)
  m <- tryCatch({
    mixed(as.formula(formula_str), data = df, method = "LRT", progress = FALSE)
  }, error = function(e) {
    cat(sprintf("afex::mixed failed (%s); falling back to lme4::lmer.\n", conditionMessage(e)))
    NULL
  })
  if (!is.null(m)) {
    cat("=== Mixed-effects model (afex, LRT) ===\n")
    print(m)
    cat("\n(Omnibus likelihood-ratio tests per effect — global results primary, rule 6.)\n")
  } else {
    have_afex <- FALSE
  }
}

if (!have_afex) {
  m <- lmer(as.formula(formula_str), data = df, REML = TRUE)
  cat("=== Mixed-effects model (lme4::lmer) ===\n")
  print(summary(m))
  cat("\nNOTE: afex not installed — only fixed-effect estimates shown (no omnibus LRT p-values).\n")
  cat("Install afex for omnibus tests per effect:  Rscript -e \"install.packages('afex')\"\n")
}

# ---- write report ----
sink(out_file)
cat("# Mixed-Effects Model Report\n\n")
cat(sprintf("**Formula:** `%s`\n", formula_str))
cat(sprintf("**Data:** %s  |  **N:** %d\n\n", data_file, nrow(df)))
cat("## Results\n\n")
if (have_afex) {
  print(m)
  cat("\n_Omnibus LRT tests per effect (global/primary, rule 6). Treat local coefficient contrasts as exploratory._\n")
} else {
  print(summary(m))
  cat("\n_NOTE: afex not installed; coefficient table only. Install afex for omnibus tests._\n")
}
cat("\n## Chatterjee rule 6\n")
cat("Global/omnibus effects are primary. Treat local/node-level effects as exploratory unless the sample is large and stable.\n")
sink()

cat(sprintf("\nReport written: %s\n", out_file))
