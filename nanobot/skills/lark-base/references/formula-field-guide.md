# Base Formula Writing Guide

## Mandatory Read Acknowledgement

When creating or updating a formula field with `lark-cli base +field-create/+field-update --json ...` and `type` is `formula`, you should read this guide first and only then add `--i-have-read-guide` to the command.

Do **not** proactively add `--i-have-read-guide` before reading this guide. Without it, the CLI will fail fast and direct you back to this guide.

## Default strategy

**All cross-table references, aggregations, and computed fields should use Formula fields by default.** Do NOT use Lookup fields unless the user explicitly requests it. Formula is a strict superset of Lookup — anything Lookup can do, Formula can do with a single expression.

## Usage

When creating a formula field, the Agent should:

1. Get all table names: `lark-cli base +table-list --base-token <base>` — returns `items[].table_name`
2. Get table structure: `lark-cli base +table-get --base-token <base> --table-id <table>` — returns `fields[]`
3. If the formula references other tables, also get those tables' structures
4. Write the formula expression following this guide
5. Construct the Formula field JSON and submit it to create or update the field

**Key constraints**:

- The JSON must include `"type": "formula"` — this field is required
- Table names and field names in the formula must **exactly match** those returned by `+table-list` / `+table-get`
- The `expression` value is a string containing the formula expression; double quotes inside the expression must be properly escaped in JSON (e.g. `\"text\"`)

---

## Section 1: Core Concepts — Scalar vs List

This is the foundation of formula logic. You must determine this before writing any formula.

| Syntax                | Meaning                                      | Return type            | Example                                      |
| --------------------- | -------------------------------------------- | ---------------------- | -------------------------------------------- |
| `[Field]`             | Value of this field in the current row       | Scalar (single value)  | `[Name]` → `"Alice"`                         |
| `[TableName].[Field]` | All values of this field in the target table | List (multiple values) | `[Employees].[Name]` → `["Alice","Bob",...]` |
| `[TableName]`         | The target table (entire table)              | Table reference        | Used as data range for FILTER/COUNTIF etc.   |

**Rules**:

- Scalars can be used directly in operations: `[Price] * [Quantity]`
- Lists cannot be used as scalars — they must be processed first: use `SUM()` for sum, `ARRAYJOIN(",")` for joining, `FIRST()`/`LAST()`/`NTH()` for single value extraction
- Link field access `[LinkField].[TargetField]` returns a list (values of the target field for all linked records)
- **LISTCOMBINE flattening rule**: When a FILTER's result column is itself a multi-value field (MultiSelect, Link, etc.), it produces a 2D array and **must** be flattened with `.LISTCOMBINE()`; for single-value fields (Number, Text, etc.) it can be omitted, but adding it is never wrong:

  ```
  [Table].FILTER(CurrentValue.[Field] = [Value]).[MultiSelectCol].LISTCOMBINE()    ← required for multi-value columns
  [Table].FILTER(CurrentValue.[Field] = [Value]).[NumberCol].LISTCOMBINE()          ← optional for single-value columns
  ```

---

## Section 2: Data Types and Type Conversion

### Field storage types

| Type        | Description                  | Supported operations                                                                                                                              |
| ----------- | ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| Number      | Stored as numeric value      | Math operations, comparisons, auto-converts to string for concatenation                                                                           |
| Text        | Stored as string             | String operations; can participate in math if content is numeric, otherwise errors                                                                |
| Date        | Date object                  | Date functions, add/subtract with numbers; auto-converts to default format string when using `&` — use TEXT to format first for controlled output |
| MultiSelect | Data list                    | List functions, CONTAIN checks                                                                                                                    |
| Link        | Links to other table records | Chained access `[LinkField].[Field]`, result is a list                                                                                            |
| Boolean     | TRUE/FALSE                   | Logical operations; auto-converts to number when compared with numbers                                                                            |

### Implicit type conversion

| Scenario                     | Conversion rule                                                                                             |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------- |
| Number + Float               | → Float                                                                                                     |
| Date + Number                | → Date (adds/subtracts days). Use `+`/`-` for whole days, use `DURATION()` for hour/minute/second precision |
| Date - Date                  | → Duration                                                                                                  |
| Boolean compared with Number | Boolean auto-converts to number (TRUE=1, FALSE=0)                                                           |
| `&` concatenation            | Both sides auto-convert to string                                                                           |

### Type consistency in comparisons

When using comparison operators (`>`, `>=`, `<`, `<=`, `=`, `!=`), **both sides should be the same type** to avoid semantic errors or unexpected results.

**Principle**: When types differ, explicitly convert one side rather than relying on implicit conversion:

- Number vs Text → use `VALUE()` to convert text to number
- Date vs Text → use `TEXT()` to convert date to text
- Date vs Date equality → Dates include time components, so direct `=` comparison may fail due to different hours/minutes/seconds. For day-level equality, convert to text first: `TEXT([DateA], "YYYY/MM/DD") = TEXT([DateB], "YYYY/MM/DD")`
- Select and User fields can be compared with both same-type values and text
- Text fields in numeric aggregation (SUM/AVERAGE/MIN/MAX etc.) → convert to number with `VALUE()` first. For FILTER results, use `.MAP(VALUE(CurrentValue)).SUM()`

---

## Section 3: CurrentValue

**CurrentValue is the iteration variable in FILTER/MAP/COUNTIF/SUMIF functions, representing the "current item" being processed in the data range.**

### CurrentValue meaning in different contexts

| Data range type              | CurrentValue represents | Access pattern              | Example                                                   |
| ---------------------------- | ----------------------- | --------------------------- | --------------------------------------------------------- |
| Entire table `[TableName]`   | A row in the table      | `CurrentValue.[FieldName]`  | `[Orders].FILTER(CurrentValue.[Amount] > 100).[Customer]` |
| Column `[TableName].[Field]` | A single field value    | Use `CurrentValue` directly | `[Orders].[Amount].FILTER(CurrentValue > 100)`            |
| MultiSelect field `[Tags]`   | One option              | Use `CurrentValue` directly | `[Tags].FILTER(CurrentValue = "Important")`               |
| LIST-generated list          | One element             | Use `CurrentValue` directly | `LIST(1,2,3).MAP(CurrentValue * 2)`                       |

### Key rules

1. **When data range is a table**, use `CurrentValue.[FieldName]` to access row fields
2. **When data range is a column/list**, use `CurrentValue` directly for the element value — **cannot** use `CurrentValue.[FieldName]`
3. CurrentValue can **only** appear inside the condition/mapping parameters of FILTER/MAP/COUNTIF/SUMIF functions
4. To reference the current table's field value in a condition, write `[FieldName]` directly — it refers to the formula row's value, not a property of CurrentValue

### Anti-patterns

| Wrong                                          | Reason                                                                            | Correct                                                |
| ---------------------------------------------- | --------------------------------------------------------------------------------- | ------------------------------------------------------ |
| `[Table].[Col].FILTER(CurrentValue.[Col] > 0)` | Data range is a column; CurrentValue is a scalar, cannot use `.` to access fields | `[Table].[Col].FILTER(CurrentValue > 0)`               |
| `[Table].FILTER(CurrentValue > 100)`           | Data range is a table; CurrentValue is a row, cannot compare directly             | `[Table].FILTER(CurrentValue.[Amount] > 100).[Amount]` |
| `CurrentValue + 1` (at top level)              | CurrentValue can only be used inside iteration functions                          | Use inside MAP/FILTER etc.                             |

---

## Section 4: Operators

Base formulas **only allow** the following operators. `like`, `in`, `<>`, `**`, `^` etc. are prohibited.

| Category      | Operators                  | Description                                                                |
| ------------- | -------------------------- | -------------------------------------------------------------------------- |
| Arithmetic    | `+` `-` `*` `/` `%`        | Add, subtract, multiply, divide, modulo (`%` is equivalent to `MOD()`)     |
| Comparison    | `>` `>=` `<` `<=` `=` `!=` | Greater than, greater or equal, less than, less or equal, equal, not equal |
| Logical       | `&&` `\|\|`                | AND, OR                                                                    |
| Concatenation | `&`                        | Text concatenation; non-text values auto-convert to string                 |

**Important**:

- Equality uses `=` (single equals), not `==`
- Not-equal uses `!=`, not `<>`
- String concatenation uses `&`, not `+`
- Both `&&`/`||` and AND()/OR() functions are supported

---

## Section 5: Link Fields and Cross-Table References

### Link field description

When a field type is described as `FieldName: Link [target table: X, foreign key: Y]`, it links to target table X using field Y as the join key.

### Chained cross-table access

```
[LinkField].[TargetField]
```

Retrieves the target field values for all linked records as a list. Supports continued chaining: `[LinkA].[LinkB].[Field]`.

### Equivalent expanded form

- Multi-value link: `[TargetTableX].FILTER([LinkField].CONTAIN(CurrentValue.[Y])).[TargetField].LISTCOMBINE()`
- Single-value link: `[TargetTableX].FILTER(CurrentValue.[Y] = [LinkField]).[TargetField].LISTCOMBINE()`

(`.LISTCOMBINE()` is required when `[TargetField]` is a multi-value field; optional for single-value fields)

### Notes

- Link fields typically return **lists** (possibly empty)
- To output a single value, use aggregation (SUM/MAX), joining (ARRAYJOIN), or extraction (FIRST/LAST/NTH)
- Do not nest FILTER inside FILTER for cross-table queries — prefer link field chained access

---

## Section 6: Function Call Conventions

### Two calling styles

| Style      | Format             | Description                         |
| ---------- | ------------------ | ----------------------------------- |
| Functional | `FUNC(arg1, arg2)` | Works for all functions             |
| Chained    | `arg1.FUNC(arg2)`  | Moves the first argument before `.` |

**Rules**:

- Zero-argument functions cannot be chained: `NOW()`, `TODAY()`, `PI()`, `TRUE()`, `FALSE()`
- SORTBY can **only** be chained: `[Table].SORTBY([Table].[SortCol]).[OutputCol]`. The sort column always uses the original table's column name (`[TableName].[Field]` format); the engine aligns rows internally, even when the data range is a FILTER result
- FILTER is recommended to be chained: `[Table].FILTER(condition).[OutputCol]`

### FILTER / SORTBY result column rules

- **When data range is a table** `[TableName]`, FILTER / SORTBY returns a table reference. The chain **must** end with `.[Field]` to specify the result column, otherwise the formula fails:

  ```
  Correct: [Sales].FILTER(CurrentValue.[Amount] > 100).[Customer]
  Correct: [Sales].FILTER(condition).SORTBY([Sales].[SortCol]).[Customer]  ← result column at end of chain
  Wrong:   [Sales].FILTER(CurrentValue.[Amount] > 100)                     ← missing result column
  ```

- **When data range is a column** `[TableName].[Field]` or a list, FILTER returns the filtered list directly — **no** result column needed:

  ```
  Correct: [Sales].[Amount].FILTER(CurrentValue > 100)
  ```

After the result column, it's recommended to flatten with `.LISTCOMBINE()` first (especially when the result column is a multi-value field), then chain aggregation functions:

```
[Sales].FILTER(CurrentValue.[Amount] > 100).[Amount].LISTCOMBINE().SUM()
```

---

## Section 7: Hard Constraints

1. **Nesting prohibition**: FILTER / SUMIF / COUNTIF / MAP **must not be nested** inside each other's condition/mapping expressions. None of these functions can appear inside the condition or mapping parameter of another.
   - Prohibited: `[Table1].FILTER(CurrentValue.[Col] = [Table2].FILTER(...).[Col])` ← FILTER inside FILTER condition
   - Prohibited: `[Table].MAP([Table2].MAP(...))` ← MAP inside MAP mapping
   - **Allowed**: `[Table].FILTER(cond1).[Col].FILTER(cond2)` ← chained call; the first FILTER's output is the second's data range, not nesting

2. **Function whitelist**: Only use functions listed in Section 8. No unlisted functions.

3. **Exact name matching**: Table names and field names in formulas must **exactly match** those returned by `+table-get` — no renaming or adding spaces.

4. **Operator whitelist**: Only use operators listed in Section 4.

5. **Strings use double quotes**: Strings must be wrapped in double quotes `"`, single quotes are not supported.

6. **Do not use LOOKUP**: FILTER is a superset of LOOKUP. All LOOKUP formulas can be rewritten with FILTER. Use FILTER exclusively to reduce complexity.

---

## Section 8: Complete Function Reference

### 8.1 Logic functions

| Function      | Signature                                                          | Return type          | Description                                                                                  |
| ------------- | ------------------------------------------------------------------ | -------------------- | -------------------------------------------------------------------------------------------- |
| IF            | `IF(condition, true_val, [false_val])`                             | Matches branch type  | Returns true_val when TRUE, false_val otherwise; omitting false_val returns false (not null) |
| IFS           | `IFS(cond1, val1, cond2, val2, ...)`                               | Matches branch type  | Multi-condition branching; returns value for the first TRUE condition                        |
| SWITCH        | `SWITCH(expr, match1, result1, [match2, result2, ...], [default])` | Matches branch type  | Matches expression value and returns corresponding result                                    |
| IFERROR       | `IFERROR(expr, fallback)`                                          | Matches branch type  | Returns fallback when expression errors                                                      |
| IFBLANK       | `IFBLANK(expr, fallback)`                                          | Matches branch type  | Returns fallback when expression is blank (blank = NULL/empty string/empty list)             |
| AND           | `AND(cond1, cond2, ...)`                                           | Boolean              | TRUE when all conditions are TRUE                                                            |
| OR            | `OR(cond1, cond2, ...)`                                            | Boolean              | TRUE when any condition is TRUE                                                              |
| NOT           | `NOT(condition)`                                                   | Boolean              | Logical negation                                                                             |
| ISBLANK       | `ISBLANK(value)`                                                   | Boolean              | Tests if blank (NULL/empty string/empty list are blank; 0 and FALSE are not)                 |
| ISNULL        | `ISNULL(value)`                                                    | Boolean              | Tests if NULL (only NULL is true; empty string is not)                                       |
| ISERROR       | `ISERROR(expr)`                                                    | Boolean              | Tests if expression errors                                                                   |
| ISNUMBER      | `ISNUMBER(value)`                                                  | Boolean              | Tests if value is a number                                                                   |
| CONTAIN       | `CONTAIN(search_range, value, ...)`                                | Boolean              | Tests if list/MultiSelect contains the value; **does NOT do text substring matching**        |
| CONTAINSALL   | `CONTAINSALL(search_range, value, ...)`                            | Boolean              | Tests if list/MultiSelect contains all specified values                                      |
| CONTAINSONLY  | `CONTAINSONLY(search_range, value, ...)`                           | Boolean              | Tests if list/MultiSelect contains only the specified values                                 |
| TRUE          | `TRUE()`                                                           | Boolean              | Returns TRUE                                                                                 |
| FALSE         | `FALSE()`                                                          | Boolean              | Returns FALSE                                                                                |
| RECORD_ID     | `RECORD_ID()`                                                      | Text                 | Returns the current row's record ID                                                          |
| RANDOMBETWEEN | `RANDOMBETWEEN(min_int, max_int, [keep_updating])`                 | Number               | Random integer in the specified range                                                        |
| RANDOMITEM    | `RANDOMITEM(list, [keep_updating])`                                | Matches element type | Randomly picks one element from a list                                                       |

### 8.2 Numeric functions

| Function                                                          | Signature                                | Return type | Description                                                                                                                                                                                                                                                |
| ----------------------------------------------------------------- | ---------------------------------------- | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| SUM                                                               | `SUM(val1, val2, ...)`                   | Number      | Sum; accepts multiple values or a list                                                                                                                                                                                                                     |
| AVERAGE                                                           | `AVERAGE(val1, val2, ...)`               | Number      | Average                                                                                                                                                                                                                                                    |
| MAX                                                               | `MAX(val1, val2, ...)`                   | Number      | Maximum                                                                                                                                                                                                                                                    |
| MIN                                                               | `MIN(val1, val2, ...)`                   | Number      | Minimum                                                                                                                                                                                                                                                    |
| MEDIAN                                                            | `MEDIAN(val1, val2, ...)`                | Number      | Median                                                                                                                                                                                                                                                     |
| COUNTA                                                            | `COUNTA(val1, val2, ...)`                | Number      | Count of non-blank values                                                                                                                                                                                                                                  |
| COUNTIF                                                           | `COUNTIF(data_range, condition)`         | Number      | Count matching items. Data range can be a **table** (CurrentValue is a row, use `CurrentValue.[Field]`) or a **column** (CurrentValue is a scalar value)                                                                                                   |
| SUMIF                                                             | `SUMIF(data_range, condition)`           | Number      | Sum matching values. Data range **must be a numeric column** (e.g. `[Table].[NumField]`); CurrentValue is each value in that column (scalar), cannot use `CurrentValue.[Field]` to access other fields. For cross-field conditions, use FILTER+SUM instead |
| ROUND                                                             | `ROUND(number, digits)`                  | Number      | Round. digits: 1=one decimal, 0=integer, -1=tens place                                                                                                                                                                                                     |
| ROUNDUP                                                           | `ROUNDUP(number, digits)`                | Number      | Round away from zero. Same digits semantics as ROUND                                                                                                                                                                                                       |
| ROUNDDOWN                                                         | `ROUNDDOWN(number, digits)`              | Number      | Round toward zero. Same digits semantics as ROUND                                                                                                                                                                                                          |
| FLOOR                                                             | `FLOOR(number, [base])`                  | Number      | Round down to nearest multiple of base (default 1)                                                                                                                                                                                                         |
| CEILING                                                           | `CEILING(number, [base])`                | Number      | Round up to nearest multiple of base (default 1)                                                                                                                                                                                                           |
| ABS                                                               | `ABS(number)`                            | Number      | Absolute value                                                                                                                                                                                                                                             |
| INT                                                               | `INT(number)`                            | Integer     | Truncate to integer                                                                                                                                                                                                                                        |
| MOD                                                               | `MOD(dividend, divisor)`                 | Number      | Modulo                                                                                                                                                                                                                                                     |
| POWER                                                             | `POWER(base, exponent)`                  | Number      | Exponentiation                                                                                                                                                                                                                                             |
| QUOTIENT                                                          | `QUOTIENT(dividend, divisor)`            | Number      | Integer division                                                                                                                                                                                                                                           |
| VALUE                                                             | `VALUE(text)`                            | Number      | Convert text to number                                                                                                                                                                                                                                     |
| ISODD                                                             | `ISODD(number)`                          | Boolean     | Tests if number is odd                                                                                                                                                                                                                                     |
| RANK                                                              | `RANK(value, search_range, [ascending])` | Number      | Rank of value in range; default descending                                                                                                                                                                                                                 |
| SEQUENCE                                                          | `SEQUENCE(start, end, [step])`           | List        | Generate number sequence                                                                                                                                                                                                                                   |
| PI                                                                | `PI()`                                   | Number      | Pi constant                                                                                                                                                                                                                                                |
| SIN/COS/TAN/ASIN/ACOS/ATAN/ATAN2/SINH/COSH/TANH/ASINH/ACOSH/ATANH | `func(radians_or_value)`                 | Number      | Trigonometric and hyperbolic functions; arguments in radians                                                                                                                                                                                               |

### 8.3 Text functions

| Function        | Signature                                            | Return type | Description                                                                                              |
| --------------- | ---------------------------------------------------- | ----------- | -------------------------------------------------------------------------------------------------------- |
| CONCATENATE     | `CONCATENATE(text1, text2, ...)`                     | Text        | Concatenate multiple texts; supports lists as input                                                      |
| LEN             | `LEN(text)`                                          | Number      | Character count                                                                                          |
| LEFT            | `LEFT(text, [count])`                                | Text        | Extract from left; default 1                                                                             |
| RIGHT           | `RIGHT(text, [count])`                               | Text        | Extract from right; default 1                                                                            |
| MID             | `MID(text, start, count)`                            | Text        | Extract from middle                                                                                      |
| FIND            | `FIND(search_val, search_range, [start])`            | Number      | Find substring position (case-sensitive); returns -1 if not found                                        |
| REPLACE         | `REPLACE(text, start, count, new_text)`              | Text        | Replace by position                                                                                      |
| SUBSTITUTE      | `SUBSTITUTE(text, old_text, new_text, [occurrence])` | Text        | Replace by content; can specify which occurrence                                                         |
| UPPER           | `UPPER(text)`                                        | Text        | Convert to uppercase                                                                                     |
| LOWER           | `LOWER(text)`                                        | Text        | Convert to lowercase                                                                                     |
| TRIM            | `TRIM(text)`                                         | Text        | Remove leading/trailing spaces                                                                           |
| TEXT            | `TEXT(value, format)`                                | Text        | Format output. Date formats: `"YYYY-MM-DD"`, `"YYYY/MM/DD hh:mm:ss"`; number formats: `"00"`, `"000.00"` |
| CONTAINTEXT     | `CONTAINTEXT(text, search_text)`                     | Boolean     | Tests if text contains substring (text substring matching)                                               |
| SPLIT           | `SPLIT(text, delimiter)`                             | List        | Split text by delimiter                                                                                  |
| TODATE          | `TODATE(value)`                                      | Date        | Convert date string to date type                                                                         |
| CHAR            | `CHAR(number)`                                       | Text        | ASCII code to character                                                                                  |
| FORMAT          | `FORMAT(template, [val1, val2, ...])`                | Text        | Template string formatting; use `{1}`, `{2}` as placeholders                                             |
| HYPERLINK       | `HYPERLINK(url, [display_text])`                     | Hyperlink   | Create a hyperlink                                                                                       |
| ENCODEURL       | `ENCODEURL(text)`                                    | Text        | URL encode                                                                                               |
| REGEXMATCH      | `REGEXMATCH(text, regex)`                            | Boolean     | Regex match test                                                                                         |
| REGEXEXTRACT    | `REGEXEXTRACT(text, regex)`                          | List        | Extract first match's capture groups                                                                     |
| REGEXEXTRACTALL | `REGEXEXTRACTALL(text, regex)`                       | 2D List     | Extract all matches                                                                                      |
| REGEXREPLACE    | `REGEXREPLACE(text, regex, replacement)`             | Text        | Regex replace                                                                                            |

### 8.4 Date functions

| Function    | Signature                                       | Return type | Description                                                                                             |
| ----------- | ----------------------------------------------- | ----------- | ------------------------------------------------------------------------------------------------------- |
| NOW         | `NOW()`                                         | Date        | Current date and time                                                                                   |
| TODAY       | `TODAY()`                                       | Date        | Current date (midnight)                                                                                 |
| DATE        | `DATE(year, month, day)`                        | Date        | Construct a date                                                                                        |
| YEAR        | `YEAR(date)`                                    | Number      | Extract year                                                                                            |
| MONTH       | `MONTH(date)`                                   | Number      | Extract month                                                                                           |
| DAY         | `DAY(date)`                                     | Number      | Extract day                                                                                             |
| HOUR        | `HOUR(date)`                                    | Number      | Extract hour                                                                                            |
| MINUTE      | `MINUTE(date)`                                  | Number      | Extract minute                                                                                          |
| SECOND      | `SECOND(date)`                                  | Number      | Extract second                                                                                          |
| WEEKDAY     | `WEEKDAY(date, [type])`                         | Number      | Day of week                                                                                             |
| WEEKNUM     | `WEEKNUM(date, [type])`                         | Number      | Week number                                                                                             |
| DAYS        | `DAYS(end_date, start_date)`                    | Number      | Days between two dates (end - start), includes decimals. **Note parameter order: end date comes first** |
| DATEDIF     | `DATEDIF(start_date, end_date, [unit])`         | Number      | Whole days/months/years between dates. Unit: `"D"`(default)/`"M"`/`"Y"`. **Start must be before end**   |
| DURATION    | `DURATION(days, [hours], [minutes], [seconds])` | Duration    | Create a duration for date arithmetic                                                                   |
| EDATE       | `EDATE(date, months)`                           | Date        | Date N months later                                                                                     |
| EOMONTH     | `EOMONTH(date, [months])`                       | Date        | End of month N months later; months default 0                                                           |
| WORKDAY     | `WORKDAY(start_date, days, [holidays])`         | Date        | Date N workdays later (skips weekends and holidays)                                                     |
| NETWORKDAYS | `NETWORKDAYS(start_date, end_date, [holidays])` | Number      | Workdays between dates (inclusive)                                                                      |

### 8.5 List functions

| Function    | Signature                                                                    | Return type | Description                                                                                                                                                                                                      |
| ----------- | ---------------------------------------------------------------------------- | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| LIST        | `LIST(val1, val2, ...)`                                                      | List        | Create a list                                                                                                                                                                                                    |
| FIRST       | `FIRST(list)`                                                                | Scalar      | First element                                                                                                                                                                                                    |
| LAST        | `LAST(list)`                                                                 | Scalar      | Last element                                                                                                                                                                                                     |
| NTH         | `NTH(list, index)`                                                           | Scalar      | Nth element (1-based)                                                                                                                                                                                            |
| FILTER      | `[Table].FILTER(condition).[ResultCol]` or `[Table].[Col].FILTER(condition)` | List        | Filter by condition. When data range is a table, result column is **required**; when it's a column/list, it's not needed. Use CurrentValue in conditions. Add `.LISTCOMBINE()` when result column is multi-value |
| MAP         | `data_range.MAP(mapping_expr)`                                               | List        | Apply mapping to each element. Use CurrentValue in mapping                                                                                                                                                       |
| SORT        | `SORT(list, [ascending])`                                                    | List        | Sort; default ascending (TRUE)                                                                                                                                                                                   |
| SORTBY      | `[Table].SORTBY([Table].[SortCol], [ascending]).[OutputCol]`                 | List        | Sort by column then extract output column. **Chain-only, must include output column**                                                                                                                            |
| UNIQUE      | `UNIQUE(list)`                                                               | List        | Deduplicate                                                                                                                                                                                                      |
| ARRAYJOIN   | `ARRAYJOIN(list, [delimiter])`                                               | Text        | Join list elements as text; default comma-separated                                                                                                                                                              |
| LISTCOMBINE | `LISTCOMBINE(val1, [val2, ...])` or `list.LISTCOMBINE()`                     | List        | Two uses: (1) merge values/lists into one list; (2) chained call to flatten 2D array (commonly used when FILTER result column is a multi-value field)                                                            |
| DISTANCE    | `DISTANCE(location1, location2)`                                             | Number      | Distance between two geographic locations (km)                                                                                                                                                                   |

---

## Section 9: Commonly Confused Functions

### CONTAIN vs CONTAINTEXT

|             | CONTAIN                                                        | CONTAINTEXT                                                |
| ----------- | -------------------------------------------------------------- | ---------------------------------------------------------- |
| Purpose     | Tests if **list/MultiSelect** contains a value                 | Tests if **text** contains a substring                     |
| Example     | `[Tags].CONTAIN("Urgent")`                                     | `[Notes].CONTAINTEXT("completed")`                         |
| Wrong usage | `CONTAIN([Notes], "completed")` — cannot do substring matching | `CONTAINTEXT([Tags], "Urgent")` — Tags is a list, not text |

### ISBLANK vs ISNULL

|                   | ISBLANK | ISNULL |
| ----------------- | ------- | ------ |
| NULL              | TRUE    | TRUE   |
| `""` empty string | TRUE    | FALSE  |
| Empty list `[]`   | TRUE    | FALSE  |
| `0`               | FALSE   | FALSE  |
| `FALSE`           | FALSE   | FALSE  |

### DAYS vs DATEDIF

|                 | DAYS                                                         | DATEDIF                                   |
| --------------- | ------------------------------------------------------------ | ----------------------------------------- |
| Parameter order | `DAYS(end, start)` — end first                               | `DATEDIF(start, end, unit)` — start first |
| Precision       | Includes decimals (hours/minutes/seconds as fractional days) | Integer only (whole days/months/years)    |
| Negative values | Returns negative when start is after end                     | **Errors** when start is after end        |

### SUM vs SUMIF

|           | SUM                                            | SUMIF                                                          |
| --------- | ---------------------------------------------- | -------------------------------------------------------------- |
| Purpose   | Sum all values                                 | Sum values **matching a condition**                            |
| Arguments | `SUM(val1, val2, ...)` or `SUM([Table].[Col])` | `SUMIF(data_range, condition)` with CurrentValue in condition  |
| Example   | `SUM([Orders].[Amount])` — sum all             | `SUMIF([Orders].[Amount], CurrentValue > 100)` — sum only >100 |

### FILTER+aggregation vs COUNTIF/SUMIF

|             | FILTER+aggregation                                    | COUNTIF/SUMIF                                                                  |
| ----------- | ----------------------------------------------------- | ------------------------------------------------------------------------------ |
| Nature      | Filter then aggregate (two steps)                     | One-step (syntactic sugar)                                                     |
| Equivalence | `[Table].FILTER(cond).[Col].LISTCOMBINE().SUM()`      | `SUMIF([Table].[Col], cond)` (only when condition involves only column values) |
| When to use | Conditions span multiple fields, or multi-step needed | Conditions only involve column values (e.g. `CurrentValue > 100`)              |

---

## Section 10: Decision Trees

### Cross-table queries: which approach?

```
Need data from another table?
├─ Current table has a link field to the target table?
│   ├─ Yes → Use chained access: [LinkField].[TargetField]
│   │         Need aggregation? → .SUM() / .ARRAYJOIN(",") / .FIRST()
│   └─ No → Need to match by field value?
│       ├─ Field matching or complex filtering → [TargetTable].FILTER(CurrentValue.[MatchField] = [Value]).[OutputCol]
│       └─ Only counting or summing → COUNTIF([TargetTable], condition) / FILTER+SUM
```

### Conditional logic: IF vs IFS vs SWITCH?

```
Need conditional logic?
├─ Single condition → IF(condition, true_val, false_val)
├─ Multiple mutually exclusive conditions (if-elseif-else) → IFS(cond1, val1, cond2, val2, ...)
├─ Matching a value against fixed options → SWITCH(expr, option1, result1, option2, result2, ..., default)
└─ Need error handling?
    ├─ Catch errors → IFERROR(expr, fallback)
    └─ Catch blanks → IFBLANK(expr, fallback)
```

### Aggregation: which function?

```
Need to aggregate data?
├─ Sum/average/max/min for entire column → SUM/AVERAGE/MAX/MIN([Table].[Col])
├─ Count non-blank → COUNTA([Table].[Col])
├─ Conditional count → COUNTIF([Table], CurrentValue.[Field] = [Value])
├─ Conditional sum (column-only condition) → SUMIF([Table].[Col], CurrentValue > threshold)
├─ Conditional sum (cross-field condition) → [Table].FILTER(CurrentValue.[Field]=value).[NumCol].LISTCOMBINE().SUM()
├─ Count unique → [Table].[Col].UNIQUE().COUNTA()
└─ Ranking → RANK([Value], [Table].[Col])
```

---

## Section 11: Common Formula Patterns

### Pattern 1: Cross-table conditional count

Count rows in target table matching a condition:

```
[TargetTable].COUNTIF(CurrentValue.[MatchField] = [CurrentTableField])
```

### Pattern 2: Cross-table conditional sum

Filter target table by current row's value, then sum:

```
[TargetTable].FILTER(CurrentValue.[MatchField] = [CurrentTableField]).[NumCol].LISTCOMBINE().SUM()
```

SUMIF works when data range is a column and conditions only involve column values:

```
SUMIF([TargetTable].[NumCol], CurrentValue > 100)
```

Note: COUNTIF can use a table as data range (only counting, no specific column needed), but SUMIF's data range **must be a numeric column** (needs values to sum), so `CurrentValue` is each value in that column (scalar) — cannot use `CurrentValue.[OtherField]` to access other fields. For cross-field conditions, use FILTER with a table as data range.

### Pattern 3: Cross-table lookup

```
[TargetTable].FILTER(CurrentValue.[MatchCol] = [CurrentTableField]).[ReturnCol]
```

### Pattern 4: Link field values + aggregation

```
SUM([LinkField].[NumField])
[LinkField].[TextField].UNIQUE().ARRAYJOIN(",")
```

### Pattern 5: Conditional text concatenation

```
IF([Condition], "prefix" & [Field] & "suffix", "default text")
```

### Pattern 6: Date difference

```
DATEDIF([StartDate], [EndDate], "D") & " days"
DAYS([EndDate], [StartDate])
```

### Pattern 7: List element mapping

```
[MultiSelectField].MAP(CurrentValue & " tag")
SPLIT([TextField], ",").MAP(TRIM(CurrentValue))
```

### Pattern 8: Cross-table with sorting

```
[TargetTable].SORTBY([TargetTable].[SortCol], FALSE).[OutputCol]
[TargetTable].FILTER(CurrentValue.[Field] = [Value]).SORTBY([TargetTable].[SortCol]).[OutputCol]
```

---

## Section 12: Anti-Pattern Collection

### Mistake 1: Extra argument in MAP

```
Wrong:   [Table].[Col].MAP([Table2].[Col], CurrentValue + 1)
Correct: [Table].[Col].MAP(CurrentValue + 1)
```

Reason: MAP takes only two arguments (data range + mapping expression), no "lookup range".

### Mistake 2: Inverted FILTER syntax

```
Wrong:   condition.[Table].FILTER()
Correct: [Table].FILTER(condition).[ResultCol]    (result column required when data range is a table)
```

Reason: FILTER's data range comes first, condition is passed as the argument.

### Mistake 3: Using CurrentValue.[Field] on a column range

```
Wrong:   SUMIF([Sales].[Revenue], CurrentValue.[Salesperson] = [Name])
Correct: [Sales].FILTER(CurrentValue.[Salesperson] = [Name]).[Revenue].LISTCOMBINE().SUM()
```

Reason: `SUMIF([Sales].[Revenue], ...)` uses "Revenue" column as data range. CurrentValue is each revenue value (scalar), not a row — cannot use `.` to access other fields. Use FILTER with the table as data range for cross-field conditions.

### Mistake 4: Missing result column after FILTER

```
Wrong:   [Sales].FILTER(CurrentValue.[Amount] > 100)
Correct: [Sales].FILTER(CurrentValue.[Amount] > 100).[Customer]
```

Reason: FILTER on a table returns a table reference; must specify result column with `.[Field]` at the end.

### Mistake 5: Nested FILTER

```
Wrong:   [Table1].FILTER(CurrentValue.[ID] = [Table2].FILTER(CurrentValue.[Status]="Done").[ID])
Correct: [Table1].FILTER(CurrentValue.[ID] = [CurrentRowField]).[OutputCol]
```

Reason: FILTER/MAP/SUMIF/COUNTIF cannot be nested inside each other's conditions. Split into multiple steps or use link fields.

### Mistake 6: SORTBY without output column

```
Wrong:   [Table].SORTBY([Table].[Col])
Correct: [Table].SORTBY([Table].[Col]).[OutputCol]
```

Reason: SORTBY must have an output column at the end; otherwise the result cannot be represented as an array.

### Mistake 7: SORTBY sort column without table name

```
Wrong:   [Table].SORTBY([Col]).[OutputCol]
Correct: [Table].SORTBY([Table].[Col]).[OutputCol]
```

Reason: SORTBY's sort column must use `[TableName].[FieldName]` format.

### Mistake 8: Using CONTAIN for text substring matching

```
Wrong:   CONTAIN([Notes], "urgent")
Correct: CONTAINTEXT([Notes], "urgent")
```

Reason: CONTAIN checks if a list/MultiSelect contains a whole value, not substring matching. Use CONTAINTEXT for text substrings.

### Mistake 9: Date concatenation without formatting

```
Not recommended: "Deadline: " & [DateField]                          ← output format is uncontrolled
Recommended:     "Deadline: " & TEXT([DateField], "YYYY-MM-DD")
```

Reason: Concatenating a date with `&` won't error, but uses the default format. Use TEXT to specify the format explicitly.

### Mistake 10: Reversed DAYS parameter order

```
Wrong:   DAYS([StartDate], [EndDate])  → returns negative
Correct: DAYS([EndDate], [StartDate])  → returns positive
```

Reason: DAYS parameter order is end date first, start date second.

### Mistake 11: Chaining zero-argument functions

```
Wrong:   TODAY.DAYS([Date])
Correct: TODAY().DAYS([Date])
```

Reason: NOW, TODAY, PI and other zero-argument functions must include parentheses.

---

## Section 13: Complete Examples

### Example 1: Employee sales summary

**Table structure** (from `+table-get`):

- Employees: EmployeeID (Text), Name (Text), Department (Text)
- Sales: ContractID (Number), SalespersonID (Text), Quantity (Number), Total (Number)

**Current table**: Employees

**Requirement**: For each employee, output "Sold XX orders" if they have sales records, otherwise "No sales records".

**Formula**:

```
IF(
  [Sales].COUNTIF(CurrentValue.[SalespersonID] = [EmployeeID]) >= 1,
  "Sold " & [Sales].COUNTIF(CurrentValue.[SalespersonID] = [EmployeeID]) & " orders",
  "No sales records"
)
```

**Field JSON**:

```json
{
  "type": "formula",
  "name": "Sales Summary",
  "expression": "IF([Sales].COUNTIF(CurrentValue.[SalespersonID] = [EmployeeID]) >= 1, \"Sold \" & [Sales].COUNTIF(CurrentValue.[SalespersonID] = [EmployeeID]) & \" orders\", \"No sales records\")"
}
```

**Explanation**: `[Sales].COUNTIF(...)` uses the entire Sales table as data range. CurrentValue represents each row in Sales, accessing `CurrentValue.[SalespersonID]` for that row's salesperson. `[EmployeeID]` refers to the current row in the Employees table (where the formula lives).

### Example 2: Chained cross-table access via link fields

**Table structure**:

- Orders: ID (AutoNumber), OrderItems (Link [target: OrderItems, foreign key: ID])
- OrderItems: ID (AutoNumber), Product (Link [target: Products, foreign key: ID])
- Products: ID (AutoNumber), ProductName (Text)

**Current table**: Orders

**Requirement**: Deduplicate and comma-join all product names from linked order items.

**Formula**:

```
[OrderItems].[Product].[ProductName].UNIQUE().ARRAYJOIN(",")
```

**Field JSON**:

```json
{
  "type": "formula",
  "name": "Product List",
  "expression": "[OrderItems].[Product].[ProductName].UNIQUE().ARRAYJOIN(\",\")"
}
```

**Explanation**: `[OrderItems]` gets linked order item records, `.[Product]` expands to each item's linked product, `.[ProductName]` gets all product names, `.UNIQUE()` deduplicates, `.ARRAYJOIN(",")` joins with commas.

### Example 3: Cross-table filter + sort

**Table structure**:

- Projects: ProjectName (Text), Status (Text), Owner (Text)
- Tasks: TaskName (Text), Project (Text), Priority (Number), DueDate (Date)

**Current table**: Projects

**Requirement**: Find the highest-priority (lowest number) task name for the current project.

**Formula**:

```
FIRST(
  [Tasks].FILTER(CurrentValue.[Project] = [ProjectName]).SORTBY([Tasks].[Priority], TRUE).[TaskName]
)
```

**Field JSON**:

```json
{
  "type": "formula",
  "name": "Top Priority Task",
  "expression": "FIRST([Tasks].FILTER(CurrentValue.[Project] = [ProjectName]).SORTBY([Tasks].[Priority], TRUE).[TaskName])"
}
```

**Explanation**: `[Tasks].FILTER(CurrentValue.[Project] = [ProjectName])` filters tasks belonging to the current project. `.SORTBY([Tasks].[Priority], TRUE)` sorts by priority ascending. `.[TaskName]` extracts task names. `FIRST(...)` gets the first one (highest priority).

---

## Section 14: Translating User Requirements to Formulas

When the user describes their formula need in natural language, follow these rules to convert it into a precise expression:

1. **Numbers must use precise values**: "less than 80%" → field value less than `0.8`. "above 1000" → `>= 1000`.
2. **Interval boundaries**: "above/below/within" = closed (inclusive); "less than/more than/outside" = open (exclusive).
3. **Branching logic** must be organized as an ordered list with a fallback branch. Each branch has a condition and output.
   - Example: "return risk level for 1-3" → `IFS([Value] = 1, "low", [Value] = 2, "medium", [Value] = 3, "high")` with an `IFERROR` or trailing empty-string fallback.
4. **Multi-level branches must be flattened** to a single level. Nested if-else chains → flat IFS.
5. **Branch conditions must be mutually exclusive**. If the user's conditions overlap, rewrite to eliminate ambiguity.
6. **Reorder branches by logical priority** if the user's order is illogical (e.g., check specific conditions before catch-all).

---

## Section 15: Constraint Summary

- Request body must include `"type": "formula"` — this field is required
- Only use functions and operators listed in this document
- FILTER/SUMIF/COUNTIF/MAP must not be nested inside each other's conditions (chained calls are not nesting)
- Do not use LOOKUP — use FILTER exclusively
- Table and field names must exactly match `+table-get` output
- Strings must use double quotes `"`
- Format dates with TEXT before concatenating, to control output format
- SORTBY can only be chained and must include an output column
- Link fields return lists — aggregate or extract single values before output
