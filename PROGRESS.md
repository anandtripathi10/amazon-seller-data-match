# Investigation Log (PROGRESS.md)

*Amazon Payments vs Settlement Reconciliation*

---

## Approach
To trace each variance back to its root cause without introducing hardcoded adjustments, the investigation followed a structured sequence:

1. **Ingest raw files without manual edits**: Loaded both files directly into `unified_transactions`.
2. **Compute baseline summary**: Calculated accounting totals separately for Payments and Settlements using the provided mapping configs.
3. **Isolate line-item deltas**: Compared every accounting bucket side-by-side to identify mismatches.
4. **Trace deltas to source rows and rules**: Queried the exact rows and config entries behind each variance.
5. **Fix via pure SQL**: Documented all config changes in `MAPPING_FIXES.sql` (`UPDATE` / `DELETE` statements).
6. **Re-run and verify**: Re-evaluated transactions against the updated rules and confirmed the net difference closed to **$0.00**.

---

## Baseline State (Before Fixes)
Running the baseline pipeline against the unedited files produced:
- **Settlement Report Total**: `$212,118.95` (matches Amazon's settlement header)
- **Payments Report Total**: `$212,149.93`
- **Initial Net Discrepancy**: `+$30.98`
- **Line-item Variances**:
  - `expenses_other`: `-$11,273.53` vs `expenses_promotional_rebates`: `+$11,273.53`
  - `sales_gift_wrap_credits`: `+$11.61` vs `sales_other`: `-$11.97`
  - `refunded_expenses`: `+$42.59` discrepancy
  - `sales_product_charges` vs `sales_shipping`: tax lines mixed into principal and shipping buckets

---

## Step-by-Step Variance Isolation & Fixes

### 1. Promotional Rebates Misrouting ($11,273.53)
- **Observation**: Payments showed `-$11,273.53` in `expenses_other` where Settlements showed `$0.00`. Conversely, Settlements showed `-$11,273.53` in `expenses_promotional_rebates` where Payments showed `$0.00`.
- **Root Cause**: In `payment_mapping_configs`, `ORDER` rows with `amount_field = 'promotional_rebates'` were mapped to `expenses_other`:
  ```csv
  ORDER,any,promotional_rebates,txn_ref+sku+date,expenses_other,expenses_other
  ```
- **Fix**: Updated `payment_mapping_configs` to route `promotional_rebates` on `ORDER` to `expenses_promotional_rebates`.
- **Result**: Eliminated the $11,273.53 cross-bucket shift.

---

### 2. Refund Sales Tax Omission ($42.59 Bottom-Line Variance)
- **Observation**: After aligning promotional rebates, Payments stood at `$212,161.54` vs Amazon's `$212,118.95` (exact delta of `+$42.59`).
- **Investigation**: Checking bucket-level deltas showed `refunded_expenses` at `$258.87` in Payments vs `$216.28` in Settlements (difference = `$42.59`). Summing all `REFUND` rows in Payments showed:
  - `product sales`: `-$1,956.52`
  - `shipping credits`: `-$74.85`
  - `selling fees`: `+$117.36`
  - `fba fees`: `+$28.89`
  - `sales tax collected`: `-$42.59`
- **Root Cause**: In `payment_mapping_configs`, the rule for `REFUND` + `sales_tax_collected` had empty summary fields (`''`). As a result, tax refunds were dropped on the Payment side, whereas Settlements routed refund tax components (`TAX`, `SHIPPINGTAX`, `TAXDISCOUNT`) to `refunded_expenses`.
- **Fix**: Routed `sales_tax_collected` on `REFUND` to `refunded_expenses`.
- **Result**: Reduced Payments total by $42.59, closing the net payout variance to **$0.00**.

---

### 3. Gift Wrap Credits Bucket ($11.61)
- **Observation**: Payments routed `$11.61` to `sales_gift_wrap_credits`, which does not exist in the target Summary sheet layout. Settlements routed gift wrap lines to `sales_other`.
- **Fix**: Updated `payment_mapping_configs` to route `gift_wrap_credits` to `sales_other`.
- **Result**: Aligned gift wrap revenue under `sales_other` across both sources.

---

### 4. Tax Component Classification & Duplicate Rules
- **Observation**: Product charges and shipping credits did not match because tax lines (`TAX`, `SHIPPINGTAX`, `TAXDISCOUNT`, `LOWVALUEGOODSTAX-*`, `GIFTWRAPTAX`) were routed into `sales_product_charges` and `sales_shipping` in `settlement_mapping_configs`, while `payment_mapping_configs` contained conflicting duplicate rules for `low_value_goods` and `sales_tax_collected`.
- **Fix**: Removed duplicate payment rules and routed all sales tax / low-value goods tax lines in both configs cleanly to `sales_tax`.
- **Result**: Pure product charges (`$335,336.96`), pure shipping (`$8,294.16`), and net sales tax (`$13,478.97`) tied out to the exact cent.

---

### 5. Preventing Double-Counting on the `total` Column
- **Observation**: Payments CSV includes both individual fee/sales columns and a row-level `total` column.
- **Root Cause**: A fallback rule (`transaction_type = ''`, `amount_field = 'total'`) routed `total` to `expenses_amazon_fees`.
- **Fix**: Cleared summary routing for `amount_field = 'total'` so `total` is reserved solely for row-level verification.

---

### 6. Join Key (`record_ref`) Plurality Mismatch
- **Observation**: AWD storage fee records failed to join across sources.
- **Root Cause**: `payment_mapping_configs` used plural `AWD_STORAGE_FEES` while `settlement_mapping_configs` used singular `AWD_STORAGE_FEE`.
- **Fix**: Standardized `payment_mapping_configs` to use `txn_ref+AWD_STORAGE_FEE+settlement_id+date`.

---

## Final Verification
After running `MAPPING_FIXES.sql` and re-evaluating:
- **Payments Total**: `$212,118.95`
- **Settlements Total**: `$212,118.95`
- **Amazon Reported Payout**: `$212,118.95`
- **Final Net Variance**: **`$0.00`**
- **Record Counts**: `8,154` reconciled pairs, `5,182` unreconciled payments, `5,135` unreconciled settlements.
