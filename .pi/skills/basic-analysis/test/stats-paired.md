# Stats Report

**Test:** ttest_paired  
**DV:** score  
**Predictor/Group:** group  
**N:** 20

## Descriptives

| group   |   n |   mean |     sd |   median |   min |   max |
|:--------|----:|-------:|-------:|---------:|------:|------:|
| post    |  10 | 6.0944 | 0.9327 |   5.895  | 4.517 | 7.695 |
| pre     |  10 | 5.1321 | 0.6556 |   5.2215 | 3.543 | 5.871 |
| Overall |  20 | 5.6132 | 0.927  |   5.596  | 3.543 | 7.695 |

## Assumption checks

| test                                    | group   |   n |   statistic |      p | pass   |
|:----------------------------------------|:--------|----:|------------:|-------:|:-------|
| Shapiro-Wilk (normality of differences) | —       |  10 |      0.9019 | 0.2301 | yes    |

## Results

### Global / omnibus (primary — Chatterjee rule 6)

| test          | comparison   |   statistic |      p | effect_size   |   dof | CI95        |
|:--------------|:-------------|------------:|-------:|:--------------|------:|:------------|
| Paired t-test | post vs pre  |      2.3644 | 0.0423 | d=1.1937      |     9 | [0.04 1.88] |

## Note (Chatterjee writing rule 6)

Global/omnibus results are primary. Treat local/node-level effects as exploratory unless the sample is large and stable.
