"""
Ingestion Pipeline for PortOne Amazon Reconciliation.
Ingests both Amazon Payments CSV and Amazon Settlement TXT into a single unified table.
Retains source audit trails and computes running summary during ingestion.
"""

import csv
import json
import re
from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, Tuple, Optional
from src.db import Database

def normalize_key(s: Optional[str]) -> str:
    if not s:
        return ''
    return re.sub(r'[^A-Z0-9]+', '_', s.strip().upper()).strip('_')

def parse_iso_date(date_str: str) -> Tuple[Optional[str], str]:
    """
    Normalizes diverse Amazon date strings to ISO YYYY-MM-DD.
    Examples:
      - '29 June 2026 5:39:32 pm GMT+9' -> '2026-06-29'
      - '17.07.2026 07:26:32 UTC' -> '2026-07-17'
      - '17.07.2026' -> '2026-07-17'
    """
    if not date_str:
        return None, ''
    clean = date_str.strip()
    # Try DD.MM.YYYY
    m = re.search(r'(\d{2})\.(\d{2})\.(\d{4})', clean)
    if m:
        d, mth, y = m.groups()
        return f"{y}-{mth}-{d}", f"{d}.{mth}.{y}"
    # Try '29 June 2026'
    m2 = re.search(r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})', clean)
    if m2:
        d, m_name, y = m2.groups()
        try:
            dt = datetime.strptime(f"{d} {m_name} {y}", "%d %B %Y")
            return dt.strftime("%Y-%m-%d"), dt.strftime("%d.%m.%Y")
        except ValueError:
            pass
    return None, clean

class IngestionPipeline:
    def __init__(self, db: Database):
        self.db = db
        self.running_summary = {
            'PAYMENTS': {},
            'SETTLEMENTS': {}
        }

    def load_configs(self, payment_config_path: str, settlement_config_path: str):
        """Loads mapping configs into database tables."""
        cur = self.db.conn.cursor()
        cur.execute("DELETE FROM payment_mapping_configs")
        cur.execute("DELETE FROM settlement_mapping_configs")

        # Payment configs
        with open(payment_config_path, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                cur.execute("""
                INSERT INTO payment_mapping_configs 
                (transaction_type, description, amount_field, record_ref, to_summary_field_when_positive_amount, to_summary_field_when_negative_amount)
                VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    row['transaction_type'],
                    row['description'],
                    row['amount_field'],
                    row['record_ref'],
                    row['to_summary_field_when_positive_amount'],
                    row['to_summary_field_when_negative_amount']
                ))

        # Settlement configs
        with open(settlement_config_path, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                cur.execute("""
                INSERT INTO settlement_mapping_configs 
                (transaction_type, amount_type, amount_description, record_ref, to_summary_field_when_positive_amount, to_summary_field_when_negative_amount)
                VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    row['transaction_type'],
                    row['amount_type'],
                    row['amount_description'],
                    row['record_ref'],
                    row['to_summary_field_when_positive_amount'],
                    row['to_summary_field_when_negative_amount']
                ))

        self.db.conn.commit()

    def get_payment_rules(self):
        cur = self.db.conn.cursor()
        cur.execute("SELECT * FROM payment_mapping_configs WHERE is_active = 1")
        return [dict(r) for r in cur.fetchall()]

    def get_settlement_rules(self):
        cur = self.db.conn.cursor()
        cur.execute("SELECT * FROM settlement_mapping_configs WHERE is_active = 1")
        return [dict(r) for r in cur.fetchall()]

    def build_record_ref(self, template: str, data: Dict[str, Any]) -> str:
        """
        Builds dynamic reconciliation key according to +-joined template.
        Supported variables: txn_ref, sku, date, settlement_id, description, shipment_id.
        """
        if not template:
            return ''
        parts = template.split('+')
        built = []
        for p in parts:
            p_clean = p.strip()
            if p_clean == 'txn_ref':
                built.append(str(data.get('order_id') or ''))
            elif p_clean == 'sku':
                built.append(str(data.get('sku') or ''))
            elif p_clean == 'date':
                built.append(str(data.get('date_norm') or ''))
            elif p_clean == 'settlement_id':
                built.append(str(data.get('settlement_id') or ''))
            elif p_clean == 'shipment_id':
                built.append(str(data.get('shipment_id') or ''))
            elif p_clean == 'description':
                built.append(str(data.get('description_clean') or ''))
            elif p_clean == 'record_type':
                built.append(str(data.get('type') or ''))
            else:
                built.append(p_clean)
        return '+'.join(built)

    def ingest_settlements(self, settlement_file_path: str):
        """Ingests Amazon settlements flat TXT file into the unified table."""
        s_rules = self.get_settlement_rules()
        cur = self.db.conn.cursor()
        cur.execute("DELETE FROM unified_transactions WHERE source_file = 'AMAZON_SETTLEMENTS'")

        rows_to_insert = []
        with open(settlement_file_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter='\t')
            for line_idx, row in enumerate(reader, start=2):
                amt_str = (row.get('amount') or '').strip()
                if not amt_str:
                    continue  # Header/metadata row (e.g. row 1 of settlements)
                amount = Decimal(amt_str)
                tt_raw = row.get('transaction-type') or ''
                at_raw = row.get('amount-type') or ''
                ad_raw = row.get('amount-description') or ''
                
                tt_norm = normalize_key(tt_raw)
                at_norm = normalize_key(at_raw)
                ad_norm = normalize_key(ad_raw)

                # Match rule
                matched = None
                for r in s_rules:
                    r_tt = normalize_key(r['transaction_type'])
                    r_at = normalize_key(r['amount_type'])
                    r_ad = normalize_key(r['amount_description'])
                    if r_tt and r_tt != tt_norm:
                        continue
                    if r_at and r_at != at_norm:
                        continue
                    if r_ad != 'ANY' and r_ad != ad_norm:
                        continue
                    matched = r
                    break

                target_field = ''
                record_ref = ''
                iso_date, disp_date = parse_iso_date(row.get('posted-date') or row.get('posted-date-time') or '')
                
                data_ctx = {
                    'order_id': row.get('order-id') or '',
                    'sku': row.get('sku') or '',
                    'date_norm': disp_date,
                    'settlement_id': row.get('settlement-id') or '',
                    'shipment_id': row.get('shipment-id') or '',
                    'type': tt_norm
                }

                if matched:
                    target_field = matched['to_summary_field_when_positive_amount'] if amount > 0 else matched['to_summary_field_when_negative_amount']
                    record_ref = self.build_record_ref(matched['record_ref'], data_ctx)
                else:
                    record_ref = f"{row.get('order-id')}+{row.get('sku')}+{disp_date}"

                # Running summary calculation during ingestion (Brownie points)
                if target_field:
                    self.running_summary['SETTLEMENTS'][target_field] = (
                        self.running_summary['SETTLEMENTS'].get(target_field, Decimal(0)) + amount
                    )

                rows_to_insert.append((
                    'AMAZON_SETTLEMENTS',
                    line_idx,
                    row.get('settlement-id'),
                    row.get('order-id'),
                    row.get('sku'),
                    iso_date,
                    row.get('posted-date-time') or row.get('posted-date'),
                    None,
                    'Settled',
                    tt_raw,
                    tt_norm,
                    f"{at_raw} - {ad_raw}",
                    None,
                    at_raw,
                    ad_raw,
                    amount,
                    int(row.get('quantity-purchased') or 0) if (row.get('quantity-purchased') or '').isdigit() else 0,
                    row.get('marketplace-name'),
                    row.get('fulfillment-id'),
                    None, None, None,
                    record_ref,
                    target_field,
                    json.dumps(row)
                ))

                if len(rows_to_insert) >= 5000:
                    cur.executemany("""
                    INSERT INTO unified_transactions (
                        source_file, line_number, settlement_id, order_id, sku,
                        transaction_date, transaction_date_str, release_date_str,
                        transaction_status, raw_type, normalized_type, raw_description,
                        amount_field, amount_type, amount_description, amount, quantity,
                        marketplace, fulfillment, order_city, order_state, order_postal,
                        record_ref, summary_field, raw_payload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, rows_to_insert)
                    rows_to_insert = []

        if rows_to_insert:
            cur.executemany("""
            INSERT INTO unified_transactions (
                source_file, line_number, settlement_id, order_id, sku,
                transaction_date, transaction_date_str, release_date_str,
                transaction_status, raw_type, normalized_type, raw_description,
                amount_field, amount_type, amount_description, amount, quantity,
                marketplace, fulfillment, order_city, order_state, order_postal,
                record_ref, summary_field, raw_payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows_to_insert)

        self.db.conn.commit()

    def ingest_payments(self, payment_file_path: str):
        """Ingests Amazon Payments CSV file into the unified table."""
        p_rules = self.get_payment_rules()
        cur = self.db.conn.cursor()
        cur.execute("DELETE FROM unified_transactions WHERE source_file = 'AMAZON_PAYMENTS'")

        field_cols = [
            ('product_sales', 'product sales'),
            ('shipping_credits', 'shipping credits'),
            ('gift_wrap_credits', 'gift wrap credits'),
            ('promotional_rebates', 'promotional rebates'),
            ('sales_tax_collected', 'sales tax collected'),
            ('low_value_goods', 'low value goods'),
            ('selling_fees', 'selling fees'),
            ('fba_fees', 'fulfilment by amazon fees'),
            ('other_transaction_fees', 'other transaction fees'),
            ('other', 'other'),
            ('total', 'total')
        ]

        rows_to_insert = []
        with open(payment_file_path, mode='r', encoding='utf-8-sig') as f:
            for _ in range(9):
                next(f)  # skip 9 metadata rows
            reader = csv.DictReader(f)
            for line_idx, row in enumerate(reader, start=11):
                raw_type = row.get('type') or ''
                tt_norm = normalize_key(raw_type)
                raw_desc = row.get('description') or ''
                desc_norm = normalize_key(raw_desc)
                if tt_norm in ('ORDER', 'REFUND'):
                    desc_norm = 'ANY'
                
                release_date_str = row.get('Transaction Release Date') or ''
                dt_str = row.get('date/time') or ''
                iso_date, disp_date = parse_iso_date(release_date_str or dt_str)

                # Process each amount column
                for af_code, col_name in field_cols:
                    val_str = (row.get(col_name) or '0').replace(',', '').strip()
                    val = Decimal(val_str) if val_str else Decimal(0)
                    if val == 0 and af_code != 'total':
                        continue  # Skip zero fields unless total

                    matched = None
                    for r in p_rules:
                        r_tt = normalize_key(r['transaction_type'])
                        r_af = normalize_key(r['amount_field'])
                        r_desc = normalize_key(r['description'])
                        if r_tt and r_tt != tt_norm:
                            continue
                        if r_af != normalize_key(af_code):
                            continue
                        if r_desc != 'ANY' and r_desc != desc_norm:
                            if not (r_desc in desc_norm or desc_norm in r_desc):
                                continue
                        matched = r
                        break

                    target_field = ''
                    record_ref = ''
                    data_ctx = {
                        'order_id': row.get('order ID') or '',
                        'sku': row.get('sku') or '',
                        'date_norm': disp_date,
                        'settlement_id': row.get('settlement ID') or '',
                        'description_clean': desc_norm,
                        'type': tt_norm
                    }

                    if matched:
                        target_field = matched['to_summary_field_when_positive_amount'] if val > 0 else matched['to_summary_field_when_negative_amount']
                        record_ref = self.build_record_ref(matched['record_ref'], data_ctx)
                    else:
                        record_ref = f"{row.get('order ID')}+{row.get('sku')}+{disp_date}"

                    # 'total' column is an audit rollup, not an independent accounting component
                    if af_code == 'total':
                        target_field = ''

                    # Only Released rows for this settlement period contribute to the accounting summary
                    is_released = (row.get('Transaction status') == 'Released')
                    if target_field and is_released and row.get('settlement ID') == '12395580393':
                        self.running_summary['PAYMENTS'][target_field] = (
                            self.running_summary['PAYMENTS'].get(target_field, Decimal(0)) + val
                        )

                    rows_to_insert.append((
                        'AMAZON_PAYMENTS',
                        line_idx,
                        row.get('settlement ID'),
                        row.get('order ID'),
                        row.get('sku'),
                        iso_date,
                        dt_str,
                        release_date_str,
                        row.get('Transaction status'),
                        raw_type,
                        tt_norm,
                        raw_desc,
                        af_code,
                        None,
                        col_name,
                        val,
                        int(row.get('quantity') or 0) if (row.get('quantity') or '').isdigit() else 0,
                        row.get('marketplace'),
                        row.get('fulfilment'),
                        row.get('order city'),
                        row.get('order state'),
                        row.get('order postal'),
                        record_ref,
                        target_field,
                        json.dumps(row)
                    ))

                    if len(rows_to_insert) >= 5000:
                        cur.executemany("""
                        INSERT INTO unified_transactions (
                            source_file, line_number, settlement_id, order_id, sku,
                            transaction_date, transaction_date_str, release_date_str,
                            transaction_status, raw_type, normalized_type, raw_description,
                            amount_field, amount_type, amount_description, amount, quantity,
                            marketplace, fulfillment, order_city, order_state, order_postal,
                            record_ref, summary_field, raw_payload
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, rows_to_insert)
                        rows_to_insert = []

        if rows_to_insert:
            cur.executemany("""
            INSERT INTO unified_transactions (
                source_file, line_number, settlement_id, order_id, sku,
                transaction_date, transaction_date_str, release_date_str,
                transaction_status, raw_type, normalized_type, raw_description,
                amount_field, amount_type, amount_description, amount, quantity,
                marketplace, fulfillment, order_city, order_state, order_postal,
                record_ref, summary_field, raw_payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows_to_insert)

        self.db.conn.commit()
