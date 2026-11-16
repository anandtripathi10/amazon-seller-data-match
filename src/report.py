"""
Excel Report Generator for PortOne Amazon Reconciliation.
Generates an accounting-grade .xlsx file matching amazon_sample_output_report.xlsx layout:
  - Sheet 1: Summary
  - Sheet 2: Consolidated Data
"""

import os
from decimal import Decimal
from typing import List, Dict, Any
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from src.reconcile import SUMMARY_STRUCTURE, CONSOLIDATED_SUMMARY_COLS

# Formatting styles
FONT_TITLE = Font(name="Calibri", size=14, bold=True, color="1F4E79")
FONT_HEADER = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
FONT_SECTION = Font(name="Calibri", size=11, bold=True, color="000000")
FONT_REGULAR = Font(name="Calibri", size=10)
FONT_BOLD = Font(name="Calibri", size=10, bold=True)
FONT_MISMATCH = Font(name="Calibri", size=10, bold=True, color="C00000")

FILL_HEADER = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
FILL_SUBHEADER = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
FILL_SECTION = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
FILL_ALERT = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")
FILL_MATCH = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")

BORDER_THIN = Border(
    left=Side(style='thin', color='D9D9D9'),
    right=Side(style='thin', color='D9D9D9'),
    top=Side(style='thin', color='D9D9D9'),
    bottom=Side(style='thin', color='D9D9D9')
)
BORDER_TOTAL = Border(
    top=Side(style='thin', color='000000'),
    bottom=Side(style='double', color='000000')
)

NUM_FORMAT_CURRENCY = "$#,##0.00;($#,##0.00);\"-\""

class ReportGenerator:
    def __init__(self, template_path: str = None):
        self.template_path = template_path

    def generate(self, summary_rows: List[Dict[str, Any]], consolidated_rows: List[Dict[str, Any]], output_path: str):
        wb = openpyxl.Workbook()
        
        # 1. Summary Sheet
        ws_sum = wb.active
        ws_sum.title = "Summary"
        self._build_summary_sheet(ws_sum, summary_rows)

        # 2. Consolidated Data Sheet
        ws_cons = wb.create_sheet(title="Consolidated Data")
        self._build_consolidated_sheet(ws_cons, consolidated_rows)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        wb.save(output_path)
        print(f"Report saved successfully to {output_path}")

    def _build_summary_sheet(self, ws, summary_rows: List[Dict[str, Any]]):
        ws.views.sheetView[0].showGridLines = True

        # Title
        ws.merge_cells("B1:E1")
        ws["B1"] = "Amazon Payments vs Settlement Accounting Summary"
        ws["B1"].font = FONT_TITLE
        ws["B1"].alignment = Alignment(vertical="center")

        # Table Header (Row 3)
        headers = ["Category / Line Item", "Payments (DS1)", "Settlements (DS2)", "Payments - Settlements"]
        cols = ["B", "C", "D", "E"]
        for c, h in zip(cols, headers):
            cell = ws[f"{c}3"]
            cell.value = h
            cell.font = FONT_HEADER
            cell.fill = FILL_HEADER
            cell.alignment = Alignment(horizontal="center" if c != "B" else "left", vertical="center")
            cell.border = BORDER_THIN
        ws.row_dimensions[3].height = 24

        curr_row = 4
        current_cat = None
        cat_start_row = curr_row

        totals_p = Decimal('0.00')
        totals_s = Decimal('0.00')

        for item in summary_rows:
            cat = item['category']
            
            # Category header
            if cat != current_cat:
                if current_cat is not None:
                    # Category Subtotal
                    curr_row += 1
                current_cat = cat
                ws[f"B{curr_row}"] = cat
                ws[f"B{curr_row}"].font = FONT_SECTION
                ws[f"B{curr_row}"].fill = FILL_SUBHEADER
                for c in ["C", "D", "E"]:
                    ws[f"{c}{curr_row}"].fill = FILL_SUBHEADER
                curr_row += 1

            p_val = float(item['payments'])
            s_val = float(item['settlements'])
            diff = float(item['variance'])

            totals_p += item['payments']
            totals_s += item['settlements']

            ws[f"B{curr_row}"] = f"   {item['line_item']}"
            ws[f"B{curr_row}"].font = FONT_REGULAR
            ws[f"B{curr_row}"].border = BORDER_THIN

            ws[f"C{curr_row}"] = p_val
            ws[f"C{curr_row}"].font = FONT_REGULAR
            ws[f"C{curr_row}"].number_format = NUM_FORMAT_CURRENCY
            ws[f"C{curr_row}"].border = BORDER_THIN

            ws[f"D{curr_row}"] = s_val
            ws[f"D{curr_row}"].font = FONT_REGULAR
            ws[f"D{curr_row}"].number_format = NUM_FORMAT_CURRENCY
            ws[f"D{curr_row}"].border = BORDER_THIN

            ws[f"E{curr_row}"] = diff
            ws[f"E{curr_row}"].font = FONT_MISMATCH if abs(diff) > 0.001 else FONT_REGULAR
            ws[f"E{curr_row}"].number_format = NUM_FORMAT_CURRENCY
            ws[f"E{curr_row}"].border = BORDER_THIN
            if abs(diff) > 0.001:
                ws[f"E{curr_row}"].fill = FILL_ALERT

            curr_row += 1

        # Final Total Row
        curr_row += 1
        ws[f"B{curr_row}"] = "TOTAL SETTLEMENT VALUE"
        ws[f"B{curr_row}"].font = FONT_BOLD
        ws[f"B{curr_row}"].border = BORDER_TOTAL

        ws[f"C{curr_row}"] = float(totals_p)
        ws[f"C{curr_row}"].font = FONT_BOLD
        ws[f"C{curr_row}"].number_format = NUM_FORMAT_CURRENCY
        ws[f"C{curr_row}"].border = BORDER_TOTAL

        ws[f"D{curr_row}"] = float(totals_s)
        ws[f"D{curr_row}"].font = FONT_BOLD
        ws[f"D{curr_row}"].number_format = NUM_FORMAT_CURRENCY
        ws[f"D{curr_row}"].border = BORDER_TOTAL

        tot_diff = float(totals_p - totals_s)
        ws[f"E{curr_row}"] = tot_diff
        ws[f"E{curr_row}"].font = FONT_MISMATCH if abs(tot_diff) > 0.001 else FONT_BOLD
        ws[f"E{curr_row}"].number_format = NUM_FORMAT_CURRENCY
        ws[f"E{curr_row}"].border = BORDER_TOTAL
        if abs(tot_diff) > 0.001:
            ws[f"E{curr_row}"].fill = FILL_ALERT
        else:
            ws[f"E{curr_row}"].fill = FILL_MATCH

        # Auto-adjust column widths
        ws.column_dimensions["A"].width = 4
        ws.column_dimensions["B"].width = 38
        ws.column_dimensions["C"].width = 20
        ws.column_dimensions["D"].width = 20
        ws.column_dimensions["E"].width = 24

    def _build_consolidated_sheet(self, ws, consolidated_rows: List[Dict[str, Any]]):
        ws.views.sheetView[0].showGridLines = True

        # Sheet header info
        ws["A1"] = "Amazon Payments (DS1) vs Settlement (DS2) Consolidated Reconciliation"
        ws["A1"].font = FONT_TITLE

        # Sub-header labels
        headers = [
            # Payments side (DS1)
            "Date", "date/time", "Transaction Status", "Transaction Release Date", "settlement id",
            "type", "order id", "sku", "description", "Quantity", "marketplace",
            "fulfillment", "order city", "order state", "order postal", "Total",
            "Product Charges", "Tax", "Shipping", "Amazon Fees", "Inventory Reimbursements",
            "Cross-Account Debt Adjustment", "Other", "Refund Expenses", "Refunded Sales",
            "Promo Rebates", "FBA Fees", "Amazon Fees (Exp)", "Other (Exp)",
            # Settlement side (DS2)
            "settlement-id", "transaction-type", "order-id", "sku", "amount-type",
            "amount-description", "posted-date", "Total (S)", "Product Charges (S)", "Tax (S)",
            "Shipping (S)", "Amazon Fees (S)", "Inventory Reimbursements (S)",
            "Cross-Account Debt (S)", "Other (S)", "Refund Expenses (S)", "Refunded Sales (S)",
            "Promo Rebates (S)", "FBA Fees (S)", "Amazon Fees Exp (S)", "Other Exp (S)",
            # Recon metadata & variance
            "Reconciliation Status", "record_ref", "Total Difference (DS1 - DS2)"
        ]

        row_idx = 3
        for col_idx, h in enumerate(headers, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=h)
            cell.font = FONT_HEADER
            cell.fill = FILL_HEADER
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = BORDER_THIN
        ws.row_dimensions[row_idx].height = 28

        # Populate rows (limiting to first 5000 in memory if large, or all)
        max_rows_to_write = min(len(consolidated_rows), 20000)
        for i in range(max_rows_to_write):
            r = consolidated_rows[i]
            row_idx += 1
            p_m = r['p_meta'] or {}
            s_m = r['s_meta'] or {}
            p_fields = r['p_fields']
            s_fields = r['s_fields']

            row_vals = [
                # DS1
                p_m.get('transaction_date_str', '')[:10] if p_m.get('transaction_date_str') else '',
                p_m.get('transaction_date_str', ''),
                p_m.get('transaction_status', ''),
                p_m.get('release_date_str', ''),
                p_m.get('settlement_id', ''),
                p_m.get('raw_type', ''),
                p_m.get('order_id', ''),
                p_m.get('sku', ''),
                (p_m.get('raw_description', '') or '')[:50],
                p_m.get('quantity', 0),
                p_m.get('marketplace', ''),
                p_m.get('fulfillment', ''),
                p_m.get('order_city', ''),
                p_m.get('order_state', ''),
                p_m.get('order_postal', ''),
                float(r['p_total']),
                float(p_fields.get('sales_product_charges', 0)),
                float(p_fields.get('sales_tax', 0)),
                float(p_fields.get('sales_shipping', 0)),
                float(p_fields.get('sales_amazon_fees', 0)),
                float(p_fields.get('sales_inventory_reimbursements', 0)),
                float(p_fields.get('total_adjustment_other_buyer_recharge_amt', 0)),
                float(p_fields.get('sales_other', 0)),
                float(p_fields.get('refunded_expenses', 0)),
                float(p_fields.get('refunded_sales', 0)),
                float(p_fields.get('expenses_promotional_rebates', 0)),
                float(p_fields.get('expenses_fba_fees', 0)),
                float(p_fields.get('expenses_amazon_fees', 0)),
                float(p_fields.get('expenses_other', 0)),

                # DS2
                s_m.get('settlement_id', ''),
                s_m.get('raw_type', ''),
                s_m.get('order_id', ''),
                s_m.get('sku', ''),
                s_m.get('amount_type', ''),
                s_m.get('amount_description', ''),
                s_m.get('transaction_date_str', ''),
                float(r['s_total']),
                float(s_fields.get('sales_product_charges', 0)),
                float(s_fields.get('sales_tax', 0)),
                float(s_fields.get('sales_shipping', 0)),
                float(s_fields.get('sales_amazon_fees', 0)),
                float(s_fields.get('sales_inventory_reimbursements', 0)),
                float(s_fields.get('total_adjustment_other_buyer_recharge_amt', 0)),
                float(s_fields.get('sales_other', 0)),
                float(s_fields.get('refunded_expenses', 0)),
                float(s_fields.get('refunded_sales', 0)),
                float(s_fields.get('expenses_promotional_rebates', 0)),
                float(s_fields.get('expenses_fba_fees', 0)),
                float(s_fields.get('expenses_amazon_fees', 0)),
                float(s_fields.get('expenses_other', 0)),

                # Status & Diff
                r['status'],
                r['record_ref'],
                float(r['total_diff'])
            ]

            status = r['status']
            diff = float(r['total_diff'])

            for col_idx, val in enumerate(row_vals, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=val)
                cell.font = FONT_REGULAR
                cell.border = BORDER_THIN
                if isinstance(val, float):
                    cell.number_format = "#,##0.00;(#,##0.00);\"-\""

            # Status cell styling
            status_cell = ws.cell(row=row_idx, column=len(headers) - 2)
            if status == 'Reconciled':
                status_cell.fill = FILL_MATCH
            else:
                status_cell.fill = FILL_ALERT

            # Diff cell styling
            diff_cell = ws.cell(row=row_idx, column=len(headers))
            if abs(diff) > 0.001:
                diff_cell.font = FONT_MISMATCH
                diff_cell.fill = FILL_ALERT

        for col_idx in range(1, len(headers) + 1):
            col_letter = get_column_letter(col_idx)
            ws.column_dimensions[col_letter].width = 16
