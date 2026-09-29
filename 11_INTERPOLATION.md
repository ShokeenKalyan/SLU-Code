# Interpolation — Annual to Quarterly Conversion

## Purpose

Long-tailed profiles use **Year-Year (YY) triangles** with annual development periods (12, 24, 36, ...). However, downstream systems and reporting need **quarterly** granularity (3, 6, 9, 12, 15, ...). 

Interpolation converts the annual cumulative percentages into quarterly values using a smooth mathematical curve.

Source: `MBR_interpolation.R.txt`

## When Applied

Only for profiles where `sml_flag == 'L'` (Long-tailed). Short and Medium-tailed profiles already use quarterly (YQ) triangles.

## calc_interpolation() Function

### Input
The best iteration's factors for a long-tailed profile:
```
dev_len:          12     24     36     48     60     72     84
Cum_Percentages:  0.15   0.35   0.55   0.72   0.84   0.92   0.97
```

### Process

1. **Set up known points**: The annual Cum_Percentages values are the "knots" for the spline
2. **Create interpolation function** using R's natural cubic spline:
```r
spline_func = splinefun(x = dev_periods_annual, y = cum_pct_annual, method = "natural")
```
3. **Evaluate at quarterly points**:
```r
quarterly_dev_periods = seq(3, max_dev, by=3)  # 3, 6, 9, 12, 15, ...
quarterly_cum_pct = spline_func(quarterly_dev_periods)
```

### Output
```
dev_len:          3     6     9     12    15    18    21    24    27    ...
Cum_Percentages:  0.04  0.08  0.12  0.15  0.20  0.25  0.30  0.35  0.40 ...
```

## Natural Cubic Spline

A natural cubic spline:
- Passes through ALL input data points exactly
- Uses cubic polynomials between consecutive points
- Ensures smoothness (continuous first and second derivatives)
- "Natural" means the second derivative is zero at the endpoints (no artificial curvature at the edges)

### Visual Representation
```
Cum%
1.0 |                                          ●─────
    |                                     ●
0.8 |                                ●
    |                          ●
0.6 |                    ●
    |              ●
0.4 |         ●               ← Interpolated quarterly values
    |     ●                      fill in the gaps between annual
0.2 |  ●                         data points (●)
    | ●
0.0 |●_________________________________
    0   12  24  36  48  60  72  84  Dev Period
        Annual data points: ●
        Quarterly interpolated: connected smooth curve
```

## func_convert_after_first_one()

After interpolation, this function ensures that once Cum_Percentages reaches 1.0, it stays at 1.0:

```r
func_convert_after_first_one = function(profile) {
  first_one_index = which(profile$Cum_Percentages >= 1)[1]
  if(!is.na(first_one_index)) {
    profile$Cum_Percentages[first_one_index:nrow(profile)] = 1
  }
  return(profile)
}
```

**Why?** The cubic spline might overshoot slightly above 1.0 or oscillate. Once claims are 100% developed, they stay at 100%.

## Example Walkthrough

**Annual input (from best iteration):**
```
Dev 12: 0.10
Dev 24: 0.25
Dev 36: 0.45
Dev 48: 0.65
Dev 60: 0.80
Dev 72: 0.90
Dev 84: 0.95
Dev 96: 1.00
```

**After cubic spline interpolation:**
```
Dev  3: 0.025    Dev 48: 0.65     ← exact (knot)
Dev  6: 0.055    Dev 51: 0.69
Dev  9: 0.080    Dev 54: 0.73
Dev 12: 0.10     ← exact (knot)    Dev 57: 0.77
Dev 15: 0.13     Dev 60: 0.80     ← exact (knot)
Dev 18: 0.17     ...
Dev 21: 0.21     Dev 96: 1.00     ← exact (knot)
Dev 24: 0.25     ← exact (knot)    Dev 99: 1.00  ← forced to 1
...
```
