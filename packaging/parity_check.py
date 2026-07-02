#!/usr/bin/env python3
"""packaging/parity_check.py — keep the CHATLabAI macOS/Linux and Windows
launchers in lockstep.

Compares packaging/chatlab-bootstrap.sh and packaging/chatlab-bootstrap.ps1 and
asserts they implement the same behaviour:

  * Both reference the shared packaging/environment.yml and neither hardcodes
    its own inline conda dependency list of R/python packages.
  * Both contain the SAME provider constants, checked as literal substrings.
  * Both implement the same logical steps (micromamba download, env create,
    simr install, npm install of pi, a pi-config writer, and a launch of the
    CHATLabAI assistant).
  * Both expose help / check / dry-run entry points (sh: --check/--dry-run/--help;
    ps1: -Check/-DryRun/-Help).

Usage:
  python3 packaging/parity_check.py            # compare the two default files
  python3 packaging/parity_check.py --help      # this message
  python3 packaging/parity_check.py --ps1 PATH --sh PATH   # override inputs

Exit status: 0 if every check passes (prints "PARITY OK"), 1 otherwise (prints
each mismatch).
"""

import argparse
import os
import re
import sys

# ---------------------------------------------------------------------------
# Constants under test. These are the literal substrings both launchers must
# contain. If a launcher changes one of these values, parity breaks here.
# ---------------------------------------------------------------------------
PROVIDER_CONSTANTS = [
    "https://litellm.parcc.upenn.edu/v1",
    "openai-completions",
    "zai-org/GLM-5.2-FP8",
    "GLM 5.2 FP8",
    "1048576",
    "@earendil-works/pi-coding-agent",
    "chatlab",  # env name
]

# Logical steps: each label maps to a list of case-insensitive tokens, ANY of
# which being present in a file counts as that step being implemented. We accept
# multiple spellings so both the sh and ps1 idioms match.
STEP_TOKENS = {
    "micromamba download": ["micro.mamba.pm", "micromamba"],
    "env create":           ["create", "-f", "environment.yml", "create -n chatlab"],
    "simr":                 ["simr"],
    "npm install":          ["npm install", "npm install -g"],
    "pi-config writer":     ["write_pi_config", "write-piconfig", "models.json", "piconfig"],
    "auto-update pi":       ["pi update --all", "pi update", "update --all"],
    "callosum setup":       ["callosum", "ensure_callosum", "ensure-callosum", ".mcp-venv", "mcp_server", "CALLOSUM_BASE_URL"],
    "launch chatlabai":     ["bin/chatlab", "launch", "pi --provider", "invoke-mm run -n", "run -n chatlab"],
}

# Entry points: sh uses --foo, ps1 uses -Foo. We look for each file's own
# spelling; the checker maps the conceptual entry point to both.
ENTRY_POINTS = {
    "help":    {"sh": "--help",  "ps1": "-Help"},
    "check":   {"sh": "--check", "ps1": "-Check"},
    "dry-run": {"sh": "--dry-run", "ps1": "-DryRun"},
}

# Tokens that indicate a HARDCODED inline conda dependency list. If both an
# R-package list and a python-package list appear inline in a launcher, that
# launcher is (re)defining the env instead of reading environment.yml. We only
# flag genuine conda-dependency-block duplications, not incidental mentions.
# We detect an inline list by seeing several known conda package names grouped
# together (>= 4 of them) — that's a strong signal of a duplicated package list.
CONDA_PKG_NEEDLES = [
    "r-base", "r-pwr", "r-lme4", "r-afex", "r-ggplot2", "r-simr",
    "pandas", "statsmodels", "nilearn", "matplotlib", "seaborn",
    "lxml", "icalendar", "pingouin", "pybtex", "python-docx",
]


def read_text(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def has_substring(haystack, needle):
    return needle in haystack


def count_inline_conda_pkgs(text):
    """How many distinct conda package needles appear in the file. >= 4 means
    the file is very likely carrying an inline dependency list (a duplicate of
    environment.yml) rather than just referencing the shared file."""
    lower = text.lower()
    seen = set()
    for pkg in CONDA_PKG_NEEDLES:
        # word-ish boundary: the pkg name as a standalone token (avoid matching
        # 'r-base' inside a URL etc. — require it not be immediately preceded by
        # '/' or '=' which would indicate a version/channel path mention only).
        if re.search(r"(?<![A-Za-z0-9_/.-])" + re.escape(pkg.lower()) + r"(?![A-Za-z0-9_.-])", lower):
            seen.add(pkg)
    return len(seen)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Check parity between CHATLabAI macOS/Linux and Windows launchers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    here = os.path.dirname(os.path.abspath(__file__))
    default_sh = os.path.join(here, "chatlab-bootstrap.sh")
    default_ps1 = os.path.join(here, "chatlab-bootstrap.ps1")
    parser.add_argument("--sh", default=default_sh, help="path to chatlab-bootstrap.sh")
    parser.add_argument("--ps1", default=default_ps1, help="path to chatlab-bootstrap.ps1")
    args = parser.parse_args(argv)

    sh_path = args.sh
    ps1_path = args.ps1

    # The spec says: running it prints which files it compared.
    print("CHATLabAI launcher parity check")
    print(f"  sh  : {sh_path}  ({'exists' if os.path.exists(sh_path) else 'MISSING'})")
    print(f"  ps1 : {ps1_path}  ({'exists' if os.path.exists(ps1_path) else 'MISSING'})")
    print()

    if not os.path.exists(sh_path):
        print(f"FAIL: sh launcher not found: {sh_path}")
        return 1
    if not os.path.exists(ps1_path):
        print(f"FAIL: ps1 launcher not found: {ps1_path}")
        return 1

    sh_text = read_text(sh_path)
    ps1_text = read_text(ps1_path)
    # The sh launch chain is bootstrap.sh -> exec bin/chatlab -> exec pi, so
    # bin/chatlab's content is part of the sh launch behavior. Fold it in so
    # steps that live in the shared launcher (e.g. the pi auto-update hook) are
    # counted on the sh side. The ps1's no-bash fallback inlines the same logic,
    # so it needs no supplementary file.
    bin_chatlab_path = os.path.join(os.path.dirname(here), "bin", "chatlab")
    if os.path.exists(bin_chatlab_path):
        sh_text = sh_text + "\n" + read_text(bin_chatlab_path)
    files = [("sh", sh_path, sh_text), ("ps1", ps1_path, ps1_text)]

    failures = []
    rows = []  # (check, sh_status, ps1_status, ok)

    # -----------------------------------------------------------------------
    # CHECK A: both reference the shared environment.yml, neither hardcodes an
    # inline conda dependency list of R/python packages.
    # -----------------------------------------------------------------------
    a_sh_env = "environment.yml" in sh_text
    a_ps1_env = "environment.yml" in ps1_text
    a_sh_inline = count_inline_conda_pkgs(sh_text) >= 4
    a_ps1_inline = count_inline_conda_pkgs(ps1_text) >= 4
    a_sh_ok = a_sh_env and not a_sh_inline
    a_ps1_ok = a_ps1_env and not a_ps1_inline
    a_ok = a_sh_ok and a_ps1_ok
    rows.append((
        "A. references shared environment.yml (no inline pkg list)",
        "yes" if a_sh_env else "no",
        "yes" if a_ps1_env else "no",
        "OK" if a_ok else "FAIL",
    ))
    if a_sh_inline:
        failures.append(f"sh: appears to hardcode an inline conda dependency list "
                        f"({count_inline_conda_pkgs(sh_text)} conda package names found)")
    if a_ps1_inline:
        failures.append(f"ps1: appears to hardcode an inline conda dependency list "
                        f"({count_inline_conda_pkgs(ps1_text)} conda package names found)")
    if not a_sh_env:
        failures.append("sh: does not reference environment.yml")
    if not a_ps1_env:
        failures.append("ps1: does not reference environment.yml")

    # -----------------------------------------------------------------------
    # CHECK B: both contain the SAME provider constants (literal substrings).
    # -----------------------------------------------------------------------
    missing_sh = [c for c in PROVIDER_CONSTANTS if not has_substring(sh_text, c)]
    missing_ps1 = [c for c in PROVIDER_CONSTANTS if not has_substring(ps1_text, c)]
    b_ok = not missing_sh and not missing_ps1
    rows.append((
        "B. provider constants match (7 substrings)",
        f"all present" if not missing_sh else f"MISSING {missing_sh}",
        f"all present" if not missing_ps1 else f"MISSING {missing_ps1}",
        "OK" if b_ok else "FAIL",
    ))
    if missing_sh:
        failures.append(f"sh: missing provider constants: {missing_sh}")
    if missing_ps1:
        failures.append(f"ps1: missing provider constants: {missing_ps1}")

    # -----------------------------------------------------------------------
    # CHECK C: both implement the same logical steps.
    # -----------------------------------------------------------------------
    c_sh_missing = []
    c_ps1_missing = []
    for step, tokens in STEP_TOKENS.items():
        sh_has = any(t.lower() in sh_text.lower() for t in tokens)
        ps1_has = any(t.lower() in ps1_text.lower() for t in tokens)
        if not sh_has:
            c_sh_missing.append(step)
        if not ps1_has:
            c_ps1_missing.append(step)
    c_ok = not c_sh_missing and not c_ps1_missing
    rows.append((
        f"C. same logical steps ({len(STEP_TOKENS)} steps)",
        "all present" if not c_sh_missing else f"MISSING {c_sh_missing}",
        "all present" if not c_ps1_missing else f"MISSING {c_ps1_missing}",
        "OK" if c_ok else "FAIL",
    ))
    if c_sh_missing:
        failures.append(f"sh: missing steps: {c_sh_missing}")
    if c_ps1_missing:
        failures.append(f"ps1: missing steps: {c_ps1_missing}")

    # -----------------------------------------------------------------------
    # CHECK D: both expose help/check/dry-run entry points.
    # -----------------------------------------------------------------------
    d_sh_missing = []
    d_ps1_missing = []
    for ep, spellings in ENTRY_POINTS.items():
        if spellings["sh"] not in sh_text:
            d_sh_missing.append(ep)
        if spellings["ps1"] not in ps1_text:
            d_ps1_missing.append(ep)
    d_ok = not d_sh_missing and not d_ps1_missing
    rows.append((
        "D. entry points (help/check/dry-run)",
        "all present" if not d_sh_missing else f"MISSING {d_sh_missing}",
        "all present" if not d_ps1_missing else f"MISSING {d_ps1_missing}",
        "OK" if d_ok else "FAIL",
    ))
    if d_sh_missing:
        failures.append(f"sh: missing entry points: {d_sh_missing}")
    if d_ps1_missing:
        failures.append(f"ps1: missing entry points: {d_ps1_missing}")

    # -----------------------------------------------------------------------
    # Print the per-check table.
    # -----------------------------------------------------------------------
    # Column widths.
    w0 = max(len(r[0]) for r in rows) + 2
    w1 = max(len(str(r[1])) for r in rows + [("x", "sh launcher", "", "")]) + 2
    w2 = max(len(str(r[2])) for r in rows + [("x", "", "ps1 launcher", "")]) + 2
    w3 = 6
    header = f"{'CHECK'.ljust(w0)}{'sh'.ljust(w1)}{'ps1'.ljust(w2)}{'RESULT'.ljust(w3)}"
    print(header)
    print("-" * len(header))
    for (check, s, p, result) in rows:
        print(f"{check.ljust(w0)}{str(s).ljust(w1)}{str(p).ljust(w2)}{result.ljust(w3)}")
    print()

    if not failures:
        print("PARITY OK")
        return 0
    else:
        print("PARITY FAILED — mismatches:")
        for f in failures:
            print(f"  - {f}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
