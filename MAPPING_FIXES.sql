-- ============================================================================
-- Amazon Payments vs Settlement Reconciliation
-- MAPPING_FIXES.sql
-- ============================================================================
-- This script contains the precise SQL updates required to correct genuine
-- mapping defects in the configuration tables. Each block isolates a specific
-- variance, explains the root cause, documents the before/after state, and
-- provides the exact SQL statement.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- DEFECT 1: Promotional Rebates Routing to 'expenses_other' Instead of 'expenses_promotional_rebates'
-- ----------------------------------------------------------------------------
-- Impact: $11,273.53 variance between Payments and Settlements.
-- Root Cause: In payment_mapping_configs, ORDER promotional rebates were mapped to
--   'expenses_other', whereas in settlement_mapping_configs they were routed to
--   'expenses_promotional_rebates'. This caused a -$11,273.53 deficit in 'expenses_other'
--   and a +$11,273.53 discrepancy in 'expenses_promotional_rebates'.
-- Fix: Update payment_mapping_configs for amount_field = 'promotional_rebates' on ORDER
--   to route to 'expenses_promotional_rebates'.
UPDATE payment_mapping_configs
SET to_summary_field_when_positive_amount = 'expenses_promotional_rebates',
    to_summary_field_when_negative_amount = 'expenses_promotional_rebates',
    notes = 'Fixed: Route order promotional rebates to expenses_promotional_rebates instead of expenses_other'
WHERE transaction_type = 'ORDER' 
  AND amount_field = 'promotional_rebates';

-- ----------------------------------------------------------------------------
-- DEFECT 2: Omission of Sales Tax on Refunds in Payment Config
-- ----------------------------------------------------------------------------
-- Impact: $42.59 variance on refunded expenses ($258.87 vs $216.28), causing the entire
--   bottom-line payout total to mismatch ($212,161.54 vs Amazon target $212,118.95).
-- Root Cause: In payment_mapping_configs, transaction_type = 'REFUND' and amount_field =
--   'sales_tax_collected' had empty routing strings ('', ''). In settlement_mapping_configs,
--   all refund tax components (ITEMPRICE TAX: -$41.09, SHIPPINGTAX: -$3.19, TAXDISCOUNT: +$1.69,
--   net: -$42.59) were correctly routed to 'refunded_expenses'. Ignoring this line on the
--   Payment side prevented the tax clawback from reducing refunded expenses.
-- Fix: Route sales_tax_collected on REFUND to 'refunded_expenses'.
UPDATE payment_mapping_configs
SET to_summary_field_when_positive_amount = 'refunded_expenses',
    to_summary_field_when_negative_amount = 'refunded_expenses',
    notes = 'Fixed: Route refund sales tax collected to refunded_expenses to account for tax refund clawback'
WHERE transaction_type = 'REFUND'
  AND amount_field = 'sales_tax_collected';

-- ----------------------------------------------------------------------------
-- DEFECT 3: Gift Wrap Credits Mapped to Non-Existent Summary Field 'sales_gift_wrap_credits'
-- ----------------------------------------------------------------------------
-- Impact: $11.61 orphaned into an unrecognized category not on the Summary Sheet.
-- Root Cause: In payment_mapping_configs, ORDER gift_wrap_credits was routed to
--   'sales_gift_wrap_credits'. The standard accounting summary sheet does not contain
--   a dedicated gift wrap line; Settlement config routes GIFTWRAP to 'sales_other'.
-- Fix: Route gift_wrap_credits to 'sales_other' to align with the Summary Sheet line 'Sales -> Other'.
UPDATE payment_mapping_configs
SET to_summary_field_when_positive_amount = 'sales_other',
    to_summary_field_when_negative_amount = 'sales_other',
    notes = 'Fixed: Route gift wrap credits to sales_other to match Summary Sheet hierarchy'
WHERE transaction_type = 'ORDER'
  AND amount_field = 'gift_wrap_credits';

-- ----------------------------------------------------------------------------
-- DEFECT 4: Duplicate Conflicting Rules for 'low_value_goods' & 'sales_tax_collected'
-- ----------------------------------------------------------------------------
-- Impact: Ambiguity and cross-contamination between product charges and shipping charges.
-- Root Cause: payment_mapping_configs contained duplicate rows for ORDER:
--   - Row A: low_value_goods -> sales_shipping
--   - Row B: low_value_goods -> sales_product_charges
--   - Row C: sales_tax_collected -> sales_product_charges
--   - Row D: sales_tax_collected -> sales_shipping
-- Fix: Clean up duplicates and map sales tax and low value goods cleanly to 'sales_tax'.
DELETE FROM payment_mapping_configs
WHERE transaction_type = 'ORDER'
  AND amount_field = 'low_value_goods'
  AND to_summary_field_when_positive_amount = 'sales_shipping';

UPDATE payment_mapping_configs
SET to_summary_field_when_positive_amount = 'sales_tax',
    to_summary_field_when_negative_amount = 'sales_tax',
    notes = 'Fixed: Route low value goods tax offset to sales_tax'
WHERE transaction_type = 'ORDER'
  AND amount_field = 'low_value_goods';

DELETE FROM payment_mapping_configs
WHERE transaction_type = 'ORDER'
  AND amount_field = 'sales_tax_collected'
  AND to_summary_field_when_positive_amount = 'sales_shipping';

UPDATE payment_mapping_configs
SET to_summary_field_when_positive_amount = 'sales_tax',
    to_summary_field_when_negative_amount = 'sales_tax',
    notes = 'Fixed: Route sales tax collected directly to sales_tax bucket'
WHERE transaction_type = 'ORDER'
  AND amount_field = 'sales_tax_collected';

-- ----------------------------------------------------------------------------
-- DEFECT 5: Settlement Config Tax Misclassification into Product & Shipping Charges
-- ----------------------------------------------------------------------------
-- Impact: Taxes distorted product charges ($348,908.77 vs $335,336.96) and shipping ($8,200.96 vs $8,294.16).
-- Root Cause: In settlement_mapping_configs:
--   - (ORDER, ITEMPRICE, TAX) was routed to 'sales_product_charges' instead of 'sales_tax'
--   - (ORDER, ITEMPRICE, SHIPPINGTAX) was routed to 'sales_shipping' instead of 'sales_tax'
--   - (ORDER, PROMOTION, TAXDISCOUNT) was routed to 'sales_shipping' instead of 'sales_tax'
--   - (ORDER, ITEMWITHHELDTAX, LOWVALUEGOODSTAX-PRINCIPAL) was routed to 'sales_product_charges'
--   - (ORDER, ITEMWITHHELDTAX, LOWVALUEGOODSTAX-SHIPPING) was routed to 'sales_shipping'
--   - (ORDER, ITEMPRICE, GIFTWRAPTAX) was routed to 'sales_other' instead of 'sales_tax'
-- Fix: Route all tax components on the settlement side to 'sales_tax' so pure product charges,
--   pure shipping credits, and pure taxes tie out 100% across both sources.
UPDATE settlement_mapping_configs
SET to_summary_field_when_positive_amount = 'sales_tax',
    to_summary_field_when_negative_amount = 'sales_tax',
    notes = 'Fixed: Route ItemPrice Tax to sales_tax'
WHERE transaction_type = 'ORDER'
  AND amount_type = 'ITEMPRICE'
  AND amount_description = 'TAX';

UPDATE settlement_mapping_configs
SET to_summary_field_when_positive_amount = 'sales_tax',
    to_summary_field_when_negative_amount = 'sales_tax',
    notes = 'Fixed: Route ShippingTax to sales_tax'
WHERE transaction_type = 'ORDER'
  AND amount_type = 'ITEMPRICE'
  AND amount_description = 'SHIPPINGTAX';

UPDATE settlement_mapping_configs
SET to_summary_field_when_positive_amount = 'sales_tax',
    to_summary_field_when_negative_amount = 'sales_tax',
    notes = 'Fixed: Route TaxDiscount to sales_tax'
WHERE transaction_type = 'ORDER'
  AND amount_type = 'PROMOTION'
  AND amount_description = 'TAXDISCOUNT';

UPDATE settlement_mapping_configs
SET to_summary_field_when_positive_amount = 'sales_tax',
    to_summary_field_when_negative_amount = 'sales_tax',
    notes = 'Fixed: Route LowValueGoodsTax-Principal to sales_tax'
WHERE transaction_type = 'ORDER'
  AND amount_type = 'ITEMWITHHELDTAX'
  AND amount_description = 'LOWVALUEGOODSTAX-PRINCIPAL';

UPDATE settlement_mapping_configs
SET to_summary_field_when_positive_amount = 'sales_tax',
    to_summary_field_when_negative_amount = 'sales_tax',
    notes = 'Fixed: Route LowValueGoodsTax-Shipping to sales_tax'
WHERE transaction_type = 'ORDER'
  AND amount_type = 'ITEMWITHHELDTAX'
  AND amount_description = 'LOWVALUEGOODSTAX-SHIPPING';

UPDATE settlement_mapping_configs
SET to_summary_field_when_positive_amount = 'sales_tax',
    to_summary_field_when_negative_amount = 'sales_tax',
    notes = 'Fixed: Route GiftWrapTax to sales_tax'
WHERE transaction_type = 'ORDER'
  AND amount_type = 'ITEMPRICE'
  AND amount_description = 'GIFTWRAPTAX';

-- ----------------------------------------------------------------------------
-- DEFECT 6: Discrepancies in Key Construction (record_ref) Templates
-- ----------------------------------------------------------------------------
-- Root Cause: AWD storage fees and inbound defect fees had divergent record_ref formulas:
--   - Payments had plural: 'txn_ref+AWD_STORAGE_FEES+settlement_id+date'
--   - Settlements had singular: 'txn_ref+AWD_STORAGE_FEE+settlement_id+date'
--   - Settlements had shipment_id: 'shipment_id+INBOUND_DEFECT_FEE+settlement_id+date'
-- Fix: Unify record_ref templates so records join smoothly.
UPDATE payment_mapping_configs
SET record_ref = 'txn_ref+AWD_STORAGE_FEE+settlement_id+date',
    notes = 'Fixed: Standardized AWD_STORAGE_FEES to singular AWD_STORAGE_FEE'
WHERE record_ref LIKE '%AWD_STORAGE_FEES%';

-- ----------------------------------------------------------------------------
-- DEFECT 7: Catch-All Rule Routing 'total' Column to 'expenses_amazon_fees'
-- ----------------------------------------------------------------------------
-- Impact: Double counting row totals alongside component amounts.
-- Root Cause: In payment_mapping_configs, a fallback rule (transaction_type = '')
--   routed amount_field = 'total' to 'expenses_amazon_fees'. In the Payments CSV,
--   'total' is a mathematical sum of horizontal columns, not an independent expense.
-- Fix: Set summary routing for all 'total' amount_fields to empty string.
UPDATE payment_mapping_configs
SET to_summary_field_when_positive_amount = '',
    to_summary_field_when_negative_amount = '',
    notes = 'Fixed: Clear summary routing for total columns to prevent double-counting'
WHERE amount_field = 'total';
