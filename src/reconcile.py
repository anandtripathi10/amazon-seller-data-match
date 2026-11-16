"""
Reconciliation Engine for PortOne Amazon Reconciliation.
Matches records across Payments (DS1) and Settlements (DS2) on shared record_ref,
handles granularity mismatches (1:N, N:1), and compiles Accounting Summary.
"""

from decimal import Decimal
from typing import Dict, List, Any, Tuple
from collections import defaultdict
from src.db import Database

# Standard Summary Sheet Structure matching sample output report
SUMMARY_STRUCTURE = [
    # (Category, Line Item, Field Key)
    ("Sales", "Product Charges", "sales_product_charges"),
    ("Sales", "Tax", "sales_tax"),
    ("Sales", "Shipping", "sales_shipping"),
    ("Sales", "Amazon fees", "sales_amazon_fees"),
    ("Sales", "Inventory Reimbursements", "sales_inventory_reimbursements"),
    ("Sales", "Cross-account Debt Adjustment", "total_adjustment_other_buyer_recharge_amt"),
    ("Sales", "Other", "sales_other"),
    ("Sales", "FBA Fees", "sales_fba_fees"),
    ("Sales", "Micro Deposit (Failed)", "micro_deposit_failed"),
    ("Refunds", "Refund expenses", "refunded_expenses"),
    ("Refunds", "Refunded sales", "refunded_sales"),
    ("Expenses", "Promo rebates", "expenses_promotional_rebates"),
    ("Expenses", "FBA fees", "expenses_fba_fees"),
    ("Expenses", "Cost of Advertising", "expenses_cost_of_advertising"),
    ("Expenses", "Shipping Charges", "expenses_shipping_charges"),
    ("Expenses", "Amazon fees", "expenses_amazon_fees"),
    ("Expenses", "Reversed Reimbursements", "expenses_reversed_reimbursements"),
    ("Expenses", "Cross-account Debt Adjustment", "expenses_cross_account_debt"),
    ("Expenses", "Other", "expenses_other"),
    ("Expenses", "Micro Deposit", "micro_deposit"),
    ("Paid To Amazon", "Paid To Amazon", "paid_to_amazon"),
]

# Consolidated columns mapped to summary fields
CONSOLIDATED_SUMMARY_COLS = [
    ('Product Charges', 'sales_product_charges'),
    ('Tax', 'sales_tax'),
    ('Shipping', 'sales_shipping'),
    ('Amazon Fees', 'sales_amazon_fees'),
    ('Inventory Reimbursements', 'sales_inventory_reimbursements'),
    ('Cross-Account Debt Adjustment', 'total_adjustment_other_buyer_recharge_amt'),
    ('Other', 'sales_other'),
    ('FBA Fees', 'sales_fba_fees'),
    ('Micro Deposit (Failed)', 'micro_deposit_failed'),
    ('Refund Expenses', 'refunded_expenses'),
    ('Refunded Sales', 'refunded_sales'),
    ('Promo Rebates', 'expenses_promotional_rebates'),
    ('FBA Fees (Exp)', 'expenses_fba_fees'),
    ('Cost of Advertising', 'expenses_cost_of_advertising'),
    ('Shipping Charges', 'expenses_shipping_charges'),
    ('Amazon Fees (Exp)', 'expenses_amazon_fees'),
    ('Reversed Reimbursements', 'expenses_reversed_reimbursements'),
    ('Cross-Account Debt Adjustment (Exp)', 'expenses_cross_account_debt'),
    ('Other (Exp)', 'expenses_other'),
    ('Micro Deposit', 'micro_deposit'),
    ('Paid To Amazon', 'paid_to_amazon')
]

class ReconciliationEngine:
    def __init__(self, db: Database, settlement_id: str = "12395580393"):
        self.db = db
        self.settlement_id = settlement_id

    def build_summary_table(self) -> List[Dict[str, Any]]:
        """
        Calculates Summary table independently:
        Payments column purely from ingested payments,
        Settlements column purely from ingested settlements.
        """
        cur = self.db.conn.cursor()
        
        # Aggregate Payments
        cur.execute("""
        SELECT summary_field, SUM(amount) as total_amt
        FROM unified_transactions
        WHERE source_file = 'AMAZON_PAYMENTS'
          AND settlement_id = ?
          AND transaction_status = 'Released'
          AND summary_field IS NOT NULL AND summary_field != ''
        GROUP BY summary_field
        """, (self.settlement_id,))
        p_map = {row['summary_field']: Decimal(str(row['total_amt'])) for row in cur.fetchall()}

        # Aggregate Settlements
        cur.execute("""
        SELECT summary_field, SUM(amount) as total_amt
        FROM unified_transactions
        WHERE source_file = 'AMAZON_SETTLEMENTS'
          AND settlement_id = ?
          AND summary_field IS NOT NULL AND summary_field != ''
        GROUP BY summary_field
        """, (self.settlement_id,))
        s_map = {row['summary_field']: Decimal(str(row['total_amt'])) for row in cur.fetchall()}

        summary_rows = []
        for cat, item, f_key in SUMMARY_STRUCTURE:
            p_val = p_map.get(f_key, Decimal('0.00'))
            s_val = s_map.get(f_key, Decimal('0.00'))
            diff = p_val - s_val
            summary_rows.append({
                'category': cat,
                'line_item': item,
                'field_key': f_key,
                'payments': p_val,
                'settlements': s_val,
                'variance': diff
            })

        return summary_rows

    def reconcile_records(self) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
        """
        Matches records across sources on shared record_ref.
        Handles granularity: groups 1-to-many and many-to-1 relations.
        Returns:
          1. Consolidated rows (Reconciled, Unreconciled Payments, Unreconciled Settlements)
          2. Match count statistics
        """
        cur = self.db.conn.cursor()

        # 1. Fetch payments grouped by record_ref
        cur.execute("""
        SELECT 
            record_ref,
            settlement_id,
            order_id,
            sku,
            raw_type,
            raw_description,
            transaction_date_str,
            release_date_str,
            transaction_status,
            quantity,
            marketplace,
            fulfillment,
            order_city,
            order_state,
            order_postal,
            summary_field,
            amount_field,
            amount
        FROM unified_transactions
        WHERE source_file = 'AMAZON_PAYMENTS'
          AND settlement_id = ?
          AND transaction_status = 'Released'
        """, (self.settlement_id,))
        
        p_by_ref = defaultdict(lambda: {
            'meta': None,
            'total': Decimal('0.00'),
            'summary_fields': defaultdict(lambda: Decimal('0.00'))
        })

        for row in cur.fetchall():
            ref = row['record_ref']
            amt = Decimal(str(row['amount']))
            af = row['amount_field']
            sf = row['summary_field']

            if not p_by_ref[ref]['meta']:
                p_by_ref[ref]['meta'] = dict(row)

            if af == 'total':
                p_by_ref[ref]['total'] += amt
            elif sf:
                p_by_ref[ref]['summary_fields'][sf] += amt

        # 2. Fetch settlements grouped by record_ref
        cur.execute("""
        SELECT 
            record_ref,
            settlement_id,
            order_id,
            sku,
            raw_type,
            amount_type,
            amount_description,
            transaction_date_str,
            quantity,
            marketplace,
            fulfillment,
            summary_field,
            amount
        FROM unified_transactions
        WHERE source_file = 'AMAZON_SETTLEMENTS'
          AND settlement_id = ?
        """, (self.settlement_id,))

        s_by_ref = defaultdict(lambda: {
            'meta': None,
            'total': Decimal('0.00'),
            'summary_fields': defaultdict(lambda: Decimal('0.00'))
        })

        for row in cur.fetchall():
            ref = row['record_ref']
            amt = Decimal(str(row['amount']))
            sf = row['summary_field']

            if not s_by_ref[ref]['meta']:
                s_by_ref[ref]['meta'] = dict(row)

            s_by_ref[ref]['total'] += amt
            if sf:
                s_by_ref[ref]['summary_fields'][sf] += amt

        all_refs = sorted(list(set(p_by_ref.keys()) | set(s_by_ref.keys())))
        
        reconciled_rows = []
        unrecon_p_rows = []
        unrecon_s_rows = []

        stats = {
            'reconciled': 0,
            'unreconciled_payments': 0,
            'unreconciled_settlements': 0
        }

        for ref in all_refs:
            has_p = ref in p_by_ref
            has_s = ref in s_by_ref

            p_data = p_by_ref.get(ref)
            s_data = s_by_ref.get(ref)

            p_tot = p_data['total'] if p_data else Decimal('0.00')
            s_tot = s_data['total'] if s_data else Decimal('0.00')
            tot_diff = p_tot - s_tot

            # Compute difference per summary field
            field_diffs = {}
            for col_label, f_key in CONSOLIDATED_SUMMARY_COLS:
                p_fval = p_data['summary_fields'].get(f_key, Decimal('0.00')) if p_data else Decimal('0.00')
                s_fval = s_data['summary_fields'].get(f_key, Decimal('0.00')) if s_data else Decimal('0.00')
                field_diffs[f_key] = p_fval - s_fval

            record_item = {
                'record_ref': ref,
                'p_meta': p_data['meta'] if p_data else None,
                's_meta': s_data['meta'] if s_data else None,
                'p_total': p_tot,
                's_total': s_tot,
                'p_fields': p_data['summary_fields'] if p_data else {},
                's_fields': s_data['summary_fields'] if s_data else {},
                'total_diff': tot_diff,
                'field_diffs': field_diffs
            }

            if has_p and has_s:
                record_item['status'] = 'Reconciled'
                stats['reconciled'] += 1
                reconciled_rows.append(record_item)
            elif has_p and not has_s:
                record_item['status'] = 'Unreconciled Payment'
                stats['unreconciled_payments'] += 1
                unrecon_p_rows.append(record_item)
            else:
                record_item['status'] = 'Unreconciled Settlement'
                stats['unreconciled_settlements'] += 1
                unrecon_s_rows.append(record_item)

        # Output in the required order: Reconciled, Unreconciled Payments, Unreconciled Settlements
        consolidated = reconciled_rows + unrecon_p_rows + unrecon_s_rows
        return consolidated, stats
