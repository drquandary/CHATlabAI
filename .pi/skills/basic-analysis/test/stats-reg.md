# Stats Report

**Test:** regression  
**DV:** y  
**Predictor/Group:** x  
**N:** 30

## Descriptives

| group   |   n |   mean |    sd |   median |     min |    max |
|:--------|----:|-------:|------:|---------:|--------:|-------:|
| Overall |  30 | 0.2098 | 0.892 |   0.3179 | -1.5323 | 1.9237 |

## Assumption checks

| test                              | group   |   n |   statistic |     p | pass   |
|:----------------------------------|:--------|----:|------------:|------:|:-------|
| Shapiro-Wilk (residual normality) | —       |  30 |      0.9737 | 0.645 | yes    |

## Results

### Global / omnibus (primary — Chatterjee rule 6)

| test                   | comparison   | statistic       |      p | effect_size   | dof   | CI95   |
|:-----------------------|:-------------|:----------------|-------:|:--------------|:------|:-------|
| Regression (omnibus F) | y ~ x        | F(1,28)=12.0747 | 0.0017 | R²=0.3013     | —     | —      |

### Local contrasts (secondary / exploratory)

Post-hoc and coefficient-level tests follow the omnibus result.

| test                           | comparison   | statistic   |      p | effect_size   |   dof | CI95             |
|:-------------------------------|:-------------|:------------|-------:|:--------------|------:|:-----------------|
| Regression coefficient [LOCAL] | Intercept    | t=1.0568    | 0.2997 | β=0.1476      |    28 | [-0.1385,0.4338] |
| Regression coefficient [LOCAL] | x            | t=3.4749    | 0.0017 | β=0.5894      |    28 | [0.242,0.9369]   |

## Note (Chatterjee writing rule 6)

Global/omnibus results are primary. Treat local/node-level effects as exploratory unless the sample is large and stable.
