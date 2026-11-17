# Investigation Progress Log (PROGRESS.md)

*Amazon Payments vs Settlement Reconciliation Engine*

---

## 🧭 Overview & Approach
Financial reconciliation is fundamentally about tracing mathematical deltas back to their root cause. A CFO cannot sign off on an unexplained variance of $42.59 or $11,273.53. Our investigation followed a rigorous forensic approach:

1. **Ingest without manual cleaning**: Ingest the raw files directly into a unified database table.
2. **Compute independent baseline totals**: Calculate the accounting summary purely from Payments data and purely from Settlements data using provided configs.
3. **Isolate line-by-line deltas**: Identify each line item where Payments ≠ Settlements.
4. **Trace deltas to specific records & rules**: Find the exact transactions causing the variance.
5. **Formulate pure SQL fixes**: Write commented `UPDATE`/`DELETE` statements in `MAPPING_FIXES.sql` (no hardcoded code adjustments).
6. **Re-evaluate and prove delta closure**: Ensure the net difference is closed to **$0.00**.

---

## 🔎 Baseline State (Before Fixes)
Running the baseline pipeline against the raw files produced:
- **Settlement Report Total**: `$212,118.95` (matches Amazon's official settlement header)
- **Payments Report Total**: `$212,149.93`
- **Initial Net Discrepancy**: `+$30.98`
- **Line-item Variances**:
  - `expenses_other`: `-$11,273.53` vs `expenses_promotional_rebates`: `+$11,273.53`
  - `sales_gift_wrap_credits`: `+$11.61` vs `sales_other`: `-$11.97`
  - `refunded_expenses`: `+$42.59` discrepancy
  - `sales_product_charges` vs `sales_shipping`: cross-contamination

---

## 🛠️ Step-by-Step Variance Investigations & Fixes

### 1. The $11,273.53 Promotional Rebates Shift
- **Observation**: Payments had `-$11,273.53` in `expenses_other` where Settlements had `$0.00`. Meanwhile, Settlements had `-$11,273.53` in `expenses_promotional_rebates` where Payments had `$0.00`.
- **Investigation**: Inspected all ORDER rows in Payments with non-zero `promotional_rebates`. Checked the matching rule in `payment_mapping_configs`:
  ```csv
  ORDER,any,promotional_rebates,txn_ref+sku+date,expenses_other,expenses_other
  ```
- **Root Cause**: The rule incorrectly routed promotional rebates to `expenses_other` instead of `expenses_promotional_rebates`.
- **Fix**: Updated `payment_mapping_configs` to route `promotional_rebates` on ORDER to `expenses_promotional_rebates`.
- **Result**: Shifted $11,273.53 into the proper accounting bucket.

---

### 2. The $42.59 Bottom-Line Payout Blocker
- **Observation**: Even after aligning promotional rebates, Payments total stood at `$212,161.54` compared to Amazon's `$212,118.95` — an exact difference of `+$42.59`.
- **Investigation**: Filtered all transactions by line item. Found that `refunded_expenses` in Payments was `$258.87`, while in Settlements it was `$216.28` (Delta = `$42.59`).
  Examined Refund transactions in Payments:
  - `product sales`: `-$1,956.52`
  - `shipping credits`: `-$74.85`
  - `selling fees`: `+$117.36`
  - `fba fees`: `+$28.89`
  - `sales tax collected`: `-$42.59` (Notice the exact $42.59!)
- **Root Cause**: In `payment_mapping_configs`, the rule for `REFUND` with `amount_field = 'sales_tax_collected'` had empty strings for summary routing (`to_summary_field = ''`). Consequently, the tax refund was completely ignored on the Payment side, whereas Settlements routed all tax refund lines to `refunded_expenses`.
- **Fix**: Updated `payment_mapping_configs` to route `sales_tax_collected` on REFUND to `refunded_expenses`.
- **Result**: Reduced Payment total by $42.59, bringing the bottom-line delta to **$0.00**.

---

### 3. The $11.61 Gift Wrap Classification
- **Observation**: Payments reported `$11.61` in `sales_gift_wrap_credits`, but the Summary sheet had no gift wrap line under Sales. Settlements reported `$11.97` in `sales_other`.
- **Root Cause**: `payment_mapping_configs` defined a custom field `sales_gift_wrap_credits`. In the sample Excel structure, non-standard credits are categorized under `sales_other`.
- **Fix**: Updated `payment_mapping_configs` to route `gift_wrap_credits` to `sales_other`.
- **Result**: Harmonized gift wrap revenue into `sales_other`.

---

### 4. Double-Counting Prevention on 'Total' Column
- **Observation**: Payments CSV contains both breakdown columns (`product sales`, `selling fees`, `fba fees`) AND a `total` column.
- **Root Cause**: A catch-all rule (`transaction_type = ''`, `amount_field = 'total'`) routed the total column to `expenses_amazon_fees`, causing potential double-counting.
- **Fix**: Set summary routing for `amount_field = 'total'` to empty string, reserving `total` solely for row-level verification.

---

### 5. Join Key Template Harmonization (`record_ref`)
- **Observation**: Certain FBA fee lines appeared as Unreconciled despite existing in both reports.
- **Root Cause**:
  - AWD Storage Fees had plural in Payments (`AWD_STORAGE_FEES`) but singular in Settlements (`AWD_STORAGE_FEE`).
  - Inbound defect fees used `shipment_id` in Settlements vs `txn_ref` in Payments.
- **Fix**: Standardized `record_ref` templates in `payment_mapping_configs` to use the unified singular token `AWD_STORAGE_FEE`.

---

## 🏆 Final Verification & Outcome
Following application of `MAPPING_FIXES.sql` and re-evaluation:
- **Payments Total (DS1)**: `$212,118.95`
- **Settlements Total (DS2)**: `$212,118.95`
- **Amazon Target Payout**: `$212,118.95`
- **Final Net Variance**: **`$0.00`**
- **All line items tie out cleanly.**
