# Stats Report

**Test:** correlation  
**DV:** y  
**Predictor/Group:** x  
**N:** 30

## Descriptives

| group   |   n |   mean |    sd |   median |     min |    max |
|:--------|----:|-------:|------:|---------:|--------:|-------:|
| Overall |  30 | 0.2098 | 0.892 |   0.3179 | -1.5323 | 1.9237 |

## Assumption checks

| test                     | group   |   n |   statistic |      p | pass   |
|:-------------------------|:--------|----:|------------:|-------:|:-------|
| Shapiro-Wilk (normality) | y       |  30 |      0.9787 | 0.7897 | yes    |
| Shapiro-Wilk (normality) | x       |  30 |      0.9835 | 0.9095 | yes    |

## Results

### Global / omnibus (primary — Chatterjee rule 6)

| test                 | comparison   | statistic   |      p | effect_size   |   dof | CI95   |
|:---------------------|:-------------|:------------|-------:|:--------------|------:|:-------|
| Pearson correlation  | y ~ x        | r=0.5489    | 0.0017 | r²=0.3013     |    28 | —      |
| Spearman correlation | y ~ x        | ρ=0.5568    | 0.0014 | —             |    28 | —      |

## Note (Chatterjee writing rule 6)

Global/omnibus results are primary. Treat local/node-level effects as exploratory unless the sample is large and stable.
