# R to Python/PySpark Conversion Guide

## Library Mapping

### Data Manipulation
| R (dplyr/tidyr) | Python (pandas) | Notes |
|---|---|---|
| `filter(df, col > 5)` | `df[df['col'] > 5]` or `df.query('col > 5')` | |
| `mutate(df, new=col*2)` | `df.assign(new=df['col']*2)` or `df['new'] = df['col']*2` | assign() returns new df; direct assignment modifies in place |
| `select(df, c(a, b))` | `df[['a', 'b']]` | |
| `select(df, -c(a))` | `df.drop(columns=['a'])` | |
| `arrange(df, col)` | `df.sort_values('col')` | |
| `arrange(df, desc(col))` | `df.sort_values('col', ascending=False)` | |
| `group_by(df, col) %>% summarise(m=mean(x))` | `df.groupby('col')['x'].mean()` or `df.groupby('col').agg(m=('x','mean'))` | |
| `left_join(a, b, by='key')` | `a.merge(b, on='key', how='left')` | |
| `inner_join(a, b, by='key')` | `a.merge(b, on='key', how='inner')` | |
| `anti_join(a, b, by='key')` | `a[~a['key'].isin(b['key'])]` or merge with indicator | |
| `bind_rows(list_of_dfs)` | `pd.concat(list_of_dfs, ignore_index=True)` | |
| `distinct(df)` | `df.drop_duplicates()` | |
| `ifelse(cond, a, b)` | `np.where(cond, a, b)` | |
| `lead(col)` | `col.shift(-1)` | Note: opposite sign! R's lead = pandas shift with negative |
| `lag(col)` | `col.shift(1)` | |
| `top_n(df, n, col)` | `df.nlargest(n, 'col')` | |
| `%>%` (pipe) | Method chaining: `df.method1().method2()` | Or use intermediate variables |

### Statistical Functions
| R | Python | Package |
|---|---|---|
| `lm(y ~ x, data=df)` | `LinearRegression().fit(X, y)` or `sm.OLS(y, sm.add_constant(X)).fit()` | sklearn or statsmodels |
| `summary(model)$r.squared` | `model.score(X, y)` or `model.rsquared` | sklearn or statsmodels |
| `cooks.distance(model)` | `OLSInfluence(model).cooks_distance[0]` | statsmodels |
| `predict(model, newdata)` | `model.predict(X_new)` | sklearn/statsmodels |
| `splinefun(x, y, method="natural")` | `CubicSpline(x, y, bc_type='natural')` | scipy.interpolate |
| `IQR(x)` | `scipy.stats.iqr(x)` or `np.percentile(x,75) - np.percentile(x,25)` | |
| `quantile(x, 0.25)` | `np.percentile(x, 25)` or `np.quantile(x, 0.25)` | |
| `medcouple(x)` | `statsmodels.stats.statlib.medcouple_1d(x)` | statsmodels (or implement manually) |
| `skewness(x)` | `scipy.stats.skew(x)` | scipy |
| `rmse(actual, predicted)` | `np.sqrt(np.mean((actual - predicted)**2))` | or sklearn's mean_squared_error(squared=False) |
| `cumprod(x)` | `np.cumprod(x)` | numpy |
| `which.min(x)` | `np.argmin(x)` or `pd.Series(x).idxmin()` | |

### Triangle / Actuarial
| R | Python | Notes |
|---|---|---|
| `as.triangle(df, origin, dev, value)` | `df.pivot_table(index='origin', columns='dev', values='value')` | Or use chainladder-python package |
| `incr2cum(tri)` | `tri.cumsum(axis=1)` | Apply along columns |
| ChainLadder package | `chainladder` Python package | pip install chainladder |

### I/O
| R | Python | Notes |
|---|---|---|
| `dbConnect(odbc::odbc(), ...)` | `pyodbc.connect(conn_str)` or `sqlalchemy.create_engine()` | |
| `dbGetQuery(con, sql)` | `pd.read_sql(sql, con)` | |
| `dbAppendTable(con, table, df)` | `df.to_sql(table, con, if_exists='append', index=False)` | |
| `write.xlsx(df, path, sheetName)` | `df.to_excel(path, sheet_name)` with openpyxl/xlsxwriter | |
| `write.csv(df, path)` | `df.to_csv(path, index=False)` | |

### Parallel Processing
| R | Python/PySpark | Notes |
|---|---|---|
| `makeCluster(10)` | `multiprocessing.Pool(10)` or `concurrent.futures.ProcessPoolExecutor(10)` | |
| `parLapply(cl, profiles, run_mbr)` | `pool.map(run_mbr, profiles)` | Or PySpark: `rdd.map(run_mbr)` |

## Critical Refactoring Considerations

### 1. Global State Management (HIGHEST PRIORITY)

The R code uses `<<-` (superassignment) extensively to modify global variables from within recursive calls:

```r
# R: modifies parent/global scope
function_counter[profile_id_analyzed] <<- function_counter[profile_id_analyzed] + 1
iterations_list[[profile_id_analyzed]][[c]] <<- iteration_data
```

**Python solutions (best to worst):**

**Option A: Class with instance attributes (RECOMMENDED)**
```python
class IterationAlgorithm:
    def __init__(self):
        self.iterations_list = {}
        self.function_counter = {}
        self.index_replacement_tracker = {}
        self.run_success_flag = {}
    
    def validate_iteration(self, x, level, dist, ...):
        self.function_counter[profile] += 1
        self.iterations_list[profile].append(iteration_data)
        # ... recursive calls use self.validate_iteration(...)
```

**Option B: Mutable container passed as argument**
```python
def validate_iteration(x, level, dist, state, ...):
    state['counter'] += 1
    state['iterations'].append(iteration_data)
```

**Option C: Module-level globals (least clean)**
```python
counter = {}
def validate_iteration(x, level, dist, ...):
    global counter
    counter[profile] += 1
```

### 2. Recursion Depth

`validate_iteration()` can recurse thousands of levels deep. Python's default limit is 1000.

**Option A: Increase recursion limit**
```python
import sys
sys.setrecursionlimit(15000)
```
Simple but fragile -- stack overflow risk for very deep profiles.

**Option B: Convert to iterative with explicit stack (RECOMMENDED for production)**
```python
def validate_iteration_iterative(initial_x, first_index, last_index, data, curves):
    stack = [(initial_x, 0, 'InitialSelection', copy(tracker))]
    
    while stack and function_counter < threshold:
        x, level, dist, tracker = stack.pop()
        function_counter += 1
        iterations_list.append({'values': x, 'level': level, ...})
        
        violation_index = find_violation(x, first_index, last_index)
        
        if violation_index is None:
            # Converged!
            iterations_list[-1]['convergence'] = 1
            continue
        
        replaceable_index = find_replaceable_index(x, violation_index, first_index, tracker)
        if replaceable_index is None:
            continue  # Dead end
        
        for curve_name in curves:
            curve_val = data[curve_name][replaceable_index]
            if is_valid_replacement(curve_val, x, replaceable_index, first_index):
                new_x = x.copy()
                new_x[replaceable_index] = curve_val
                new_tracker = tracker.copy()
                new_tracker[replaceable_index] = 1
                stack.append((new_x, level+1, curve_name, new_tracker))
```

### 3. Indexing (1-based vs 0-based)

R is 1-indexed; Python is 0-indexed. This affects EVERY array/list access.

**Strategy:** Create helper constants or adjust all index references:
```python
# Option: Keep 1-based logic, adjust at access time
def r_index(arr, i):
    """Access array using R's 1-based indexing"""
    return arr[i - 1]

# Or: Convert all indexes at the boundary
first_index_py = first_index_r - 1
```

### 4. Triangle Data Structure

R uses matrices with named rows/columns. Python equivalent:
```python
# pandas DataFrame with exp_year as index, dev_period as columns
triangle = pd.pivot_table(actuals, index='exp_year', columns='dev_len', values='Cumulative_Gross_Incurred')
```

## Suggested Python Module Structure

```
mbr/
    __init__.py
    config.py                  # analysis_year, analysis_qtr, thresholds, SML params
    data/
        __init__.py
        sql_connector.py       # ODBC connection, read/write helpers
        vena_transform.py      # fn_to_transform_incurred_paid, fn_to_transform_vena_all_data
        triangle_builder.py    # Build incremental/cumulative triangles, SML classification
    analysis/
        __init__.py
        outlier_detection.py   # fn_get_age_to_age_outliers (adjusted boxplot)
        weighted_average.py    # calc_weighted_average, VW period selection
        curve_fitting.py       # 4 distribution fits, Cook's distance
        iteration_algorithm.py # validate_iteration, best_rsq_replace (CLASS-based)
        rmse.py                # calc_VW_Averages_weighted_RMSE, calc_weighted_RMSE
        factor_indexes.py      # factor_one_index, less_than_one detection
        tail_factors.py        # experience method, NCCI method
    methods/
        __init__.py
        actuarial_methods.py   # DFM, BF, CC, LR, Recovery Ratio ultimates
        method_selection.py    # Rule-based + RMSE-based selection per exp year
    ceded/
        __init__.py
        ceded_calculations.py  # Reinsurance processing, ceded method selection
    output/
        __init__.py
        interpolation.py       # Cubic spline (annual->quarterly)
        sql_export.py          # Delete-then-append to SQL tables
        excel_export.py        # Excel/CSV outputs
    run_profile.py             # run_mbr() equivalent -- processes one profile
    main.py                    # Orchestrator: import data, parallel execution, export
```

## PySpark-Specific Considerations

### Per-Profile Processing with PySpark
The MBR algorithm is inherently **per-profile** -- each profile's processing is independent but sequential within itself. PySpark excels at distributing profiles across a cluster.

**Approach: Pandas UDFs with `applyInPandas()`**
```python
from pyspark.sql.functions import pandas_udf

# Group data by profile_id, process each group in parallel
result_schema = StructType([...])

def run_mbr_spark(profile_df: pd.DataFrame) -> pd.DataFrame:
    profile_id = profile_df['profile_id'].iloc[0]
    # ... full MBR processing using pandas ...
    return result_df

results = (spark_df
    .groupBy('profile_id')
    .applyInPandas(run_mbr_spark, schema=result_schema))
```

### Data I/O with PySpark
```python
# Read from SQL Server
df = spark.read.jdbc(url=jdbc_url, table="afr_analytics.MBR_vena_vectors", properties=props)

# Write results
result_df.write.jdbc(url=jdbc_url, table="afr_analytics.MBR_summary_CoU", mode="append", properties=props)
```

## Common Pitfalls

| Issue | R Behavior | Python Behavior | Fix |
|-------|-----------|----------------|-----|
| Indexing | 1-based | 0-based | Adjust all indices by -1 |
| `lead()` | Next row (positive shift) | `shift(-1)` (negative) | Use `shift(-1)` |
| Vector recycling | Silently recycles shorter vector | Raises error | Ensure equal lengths |
| `lm()` intercept | Includes by default | sklearn includes, statsmodels.OLS does NOT | Use `sm.add_constant(X)` |
| NA propagation | Most operations return NA | NaN behavior differs; some return NaN, some error | Use `pd.isna()` checks |
| `as.integer()` | Truncates toward zero | `int()` also truncates | Same behavior |
| Factor types | R factors have levels | No equivalent; use categorical | `pd.Categorical()` if needed |
| `data.frame` columns | Allow duplicates | Pandas allows but causes issues | Ensure unique column names |
| `paste0()` | Concatenates without separator | f-strings or `''.join()` | |
| `Sys.time()` | Returns POSIXct | `datetime.now()` or `time.time()` | |

## Testing Strategy

### Phase 1: Module-by-Module Validation
For each module, run R and Python side-by-side with the same input data. Compare outputs within tolerance (e.g., 1e-10 for floating point).

**Order (simple to complex):**
1. `outlier_detection.py` -- pure statistical computation
2. `weighted_average.py` -- depends on outlier detection
3. `curve_fitting.py` -- depends on weighted averages
4. `factor_indexes.py` -- pure computation on LDFs
5. `tail_factors.py` -- simple product calculation
6. `actuarial_methods.py` -- formula-based, no dependencies on algorithm
7. `method_selection.py` -- rule-based + RMSE
8. `iteration_algorithm.py` -- THE MOST COMPLEX; test last
9. `interpolation.py` -- independent (cubic spline)
10. Integration test: full pipeline for one profile

### Phase 2: Full Pipeline Comparison
Run both R and Python on all profiles. Compare final SQL output tables row-by-row.

### Phase 3: Performance Testing
Benchmark Python/PySpark against R for:
- Single profile execution time
- Full parallel execution time
- Memory usage per profile
