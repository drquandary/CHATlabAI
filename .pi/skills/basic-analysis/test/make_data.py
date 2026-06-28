#!/usr/bin/env python3
"""Generate toy test data for basic-analysis acceptance tests (reproducible, fixed seed)."""
import numpy as np
import pandas as pd

rng = np.random.default_rng(42)

# 2-group data (A, B) — independent t-test fixture
n_per = 10
df2 = pd.DataFrame({
    "subject": range(1, 2 * n_per + 1),
    "group": ["A"] * n_per + ["B"] * n_per,
    "score": np.concatenate([rng.normal(5.0, 1.0, n_per),
                              rng.normal(6.5, 1.0, n_per)]).round(3),
})
df2.to_csv("test/data.csv", index=False)
print("Wrote test/data.csv (2 groups, n=10 each):")
print(df2.to_string(index=False))

# 3-group data (A, B, C) — ANOVA fixture
n_per3 = 8
df3 = pd.DataFrame({
    "subject": range(1, 3 * n_per3 + 1),
    "group": ["A"] * n_per3 + ["B"] * n_per3 + ["C"] * n_per3,
    "score": np.concatenate([rng.normal(5.0, 1.0, n_per3),
                              rng.normal(6.0, 1.0, n_per3),
                              rng.normal(7.5, 1.0, n_per3)]).round(3),
})
df3.to_csv("test/data3.csv", index=False)
print("\nWrote test/data3.csv (3 groups, n=8 each):")
print(df3.to_string(index=False))

# paired data fixture
dfp = pd.DataFrame({
    "subject": list(range(1, n_per + 1)) * 2,
    "group": ["pre"] * n_per + ["post"] * n_per,
    "score": np.concatenate([rng.normal(5.0, 1.0, n_per),
                              rng.normal(6.2, 1.0, n_per)]).round(3),
})
dfp.to_csv("test/data_paired.csv", index=False)
print("\nWrote test/data_paired.csv (paired, n=10):")
print(dfp.to_string(index=False))
