"""
Main CLI Pipeline for Amazon Reconciliation.
Orchestrates: Ingest -> Baseline Recon -> Report Before Fixes -> Apply MAPPING_FIXES.sql -> Report After Fixes -> Export Postgres Dump.
"""

import os
import sys
import time
from decimal import Decimal

from src.db import Database, POSTGRES_SCHEMA_SQL
from src.ingest import IngestionPipeline
from src.reconcile import ReconciliationEngine
from src.report import ReportGenerator

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
FIXES_SQL_PATH = os.path.join(BASE_DIR, "MAPPING_FIXES.sql")

def run_pipeline():
    start_time = time.time()
    print("=" * 80)
    print("🚀 STARTING PORTONE AMAZON PAYMENTS VS SETTLEMENT RECONCILIATION")
    print("=" * 80)

    db_file = os.path.join(OUTPUT_DIR, "reconciliation.db")
    if os.path.exists(db_file):
        os.remove(db_file)

    db = Database(db_file)
    pipeline = IngestionPipeline(db)
    reporter = ReportGenerator()

    # Step 1: Load Initial Configurations
    print("\n[Step 1/6] Loading Original Mapping Configurations...")
    payment_cfg_path = os.path.join(DATA_DIR, "amazon_payment_configs_au_old.csv")
    settlement_cfg_path = os.path.join(DATA_DIR, "amazon_settlement_configs_au.csv")
    pipeline.load_configs(payment_cfg_path, settlement_cfg_path)
    print("  ✓ Payment & Settlement mapping configs loaded into database tables.")

    # Step 2: Ingest Raw Files
    print("\n[Step 2/6] Ingesting Amazon Files into Unified Transactions Table...")
    settlement_file = os.path.join(DATA_DIR, "amazon_settlements_data.txt")
    payment_file = os.path.join(DATA_DIR, "amazon_payments_data.csv")

    t0 = time.time()
    pipeline.ingest_settlements(settlement_file)
    print(f"  ✓ Settlements ingested in {time.time() - t0:.2f}s.")

    t0 = time.time()
    pipeline.ingest_payments(payment_file)
    print(f"  ✓ Payments ingested in {time.time() - t0:.2f}s.")

    # Check total rows
    cur = db.conn.cursor()
    cur.execute("SELECT source_file, COUNT(*) FROM unified_transactions GROUP BY source_file")
    for row in cur.fetchall():
        print(f"    - {row[0]}: {row[1]:,} rows in unified_transactions")

    # Step 3: Run Baseline Reconciliation (Before Fixes)
    print("\n[Step 3/6] Running Baseline Reconciliation (Before Fixes)...")
    recon = ReconciliationEngine(db)
    summary_before = recon.build_summary_table()
    consolidated_before, stats_before = recon.reconcile_records()

    tot_p_before = sum(r['payments'] for r in summary_before)
    tot_s_before = sum(r['settlements'] for r in summary_before)
    variance_before = tot_p_before - tot_s_before

    print(f"  Payments Total:    ${tot_p_before:,.2f}")
    print(f"  Settlements Total: ${tot_s_before:,.2f}")
    print(f"  Initial Variance:  ${variance_before:,.2f}")
    print(f"  Record Matches:    Reconciled={stats_before['reconciled']:,}, "
          f"Unreconciled Payments={stats_before['unreconciled_payments']:,}, "
          f"Unreconciled Settlements={stats_before['unreconciled_settlements']:,}")

    # Generate Before Fix Excel Report
    report_before_path = os.path.join(OUTPUT_DIR, "report_before_fixes.xlsx")
    reporter.generate(summary_before, consolidated_before, report_before_path)
    print(f"  ✓ Generated: {report_before_path}")

    # Step 4: Apply Mapping Fixes
    print("\n[Step 4/6] Applying Config Fixes from MAPPING_FIXES.sql...")
    with open(FIXES_SQL_PATH, 'r') as f:
        sql_script = f.read()
    
    # Execute SQL updates on config tables
    cur.executescript(sql_script)
    db.conn.commit()
    print("  ✓ Applied all SQL updates to config tables.")

    # Re-ingest with fixed configs
    print("  Re-ingesting and re-evaluating transactions with fixed configs...")
    pipeline.running_summary = {'PAYMENTS': {}, 'SETTLEMENTS': {}}
    pipeline.ingest_settlements(settlement_file)
    pipeline.ingest_payments(payment_file)

    # Step 5: Run Reconciliation After Fixes
    print("\n[Step 5/6] Running Reconciliation After Fixes...")
    summary_after = recon.build_summary_table()
    consolidated_after, stats_after = recon.reconcile_records()

    tot_p_after = sum(r['payments'] for r in summary_after)
    tot_s_after = sum(r['settlements'] for r in summary_after)
    variance_after = tot_p_after - tot_s_after

    print(f"  Payments Total:    ${tot_p_after:,.2f}")
    print(f"  Settlements Total: ${tot_s_after:,.2f}")
    print(f"  Final Variance:    ${variance_after:,.2f}")
    print(f"  Record Matches:    Reconciled={stats_after['reconciled']:,}, "
          f"Unreconciled Payments={stats_after['unreconciled_payments']:,}, "
          f"Unreconciled Settlements={stats_after['unreconciled_settlements']:,}")

    # Generate After Fix Excel Report
    report_after_path = os.path.join(OUTPUT_DIR, "report_after_fixes.xlsx")
    reporter.generate(summary_after, consolidated_after, report_after_path)
    print(f"  ✓ Generated: {report_after_path}")

    # Step 6: Generate PostgreSQL Dump
    print("\n[Step 6/6] Generating PostgreSQL Export Dump (db_dump.sql)...")
    pg_dump_path = os.path.join(OUTPUT_DIR, "db_dump.sql")
    export_postgres_dump(db, pg_dump_path)
    print(f"  ✓ PostgreSQL dump saved to {pg_dump_path}")

    db.close()
    elapsed = time.time() - start_time
    print("\n" + "=" * 80)
    print(f"🎉 PIPELINE COMPLETED SUCCESSFULLY IN {elapsed:.2f} SECONDS!")
    print(f"   Delta Closed: ${variance_before:,.2f} ➔ ${variance_after:,.2f}")
    print("=" * 80)

def export_postgres_dump(db: Database, output_path: str):
    """Exports unified transactions and configs to standard PostgreSQL dump format."""
    cur = db.conn.cursor()
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("-- =========================================================\n")
        f.write("-- Amazon Payments vs Settlement Reconciliation: PostgreSQL Database Dump\n")
        f.write("-- =========================================================\n\n")
        f.write(POSTGRES_SCHEMA_SQL)
        f.write("\n\n-- Ingested Configs and Data Samples\n")

        # Dump payment configs
        cur.execute("SELECT * FROM payment_mapping_configs")
        p_configs = cur.fetchall()
        for r in p_configs:
            f.write(f"INSERT INTO payment_mapping_configs (transaction_type, description, amount_field, record_ref, to_summary_field_when_positive_amount, to_summary_field_when_negative_amount) VALUES ('{r['transaction_type']}', '{r['description']}', '{r['amount_field']}', '{r['record_ref']}', '{r['to_summary_field_when_positive_amount']}', '{r['to_summary_field_when_negative_amount']}');\n")

        # Dump settlement configs
        cur.execute("SELECT * FROM settlement_mapping_configs")
        s_configs = cur.fetchall()
        for r in s_configs:
            f.write(f"INSERT INTO settlement_mapping_configs (transaction_type, amount_type, amount_description, record_ref, to_summary_field_when_positive_amount, to_summary_field_when_negative_amount) VALUES ('{r['transaction_type']}', '{r['amount_type']}', '{r['amount_description']}', '{r['record_ref']}', '{r['to_summary_field_when_positive_amount']}', '{r['to_summary_field_when_negative_amount']}');\n")

        # Dump representative sample of unified_transactions (1000 rows)
        cur.execute("SELECT * FROM unified_transactions LIMIT 1000")
        sample_rows = cur.fetchall()
        f.write(f"\n-- Representative sample of unified_transactions ({len(sample_rows)} rows)\n")
        for r in sample_rows:
            f.write(f"INSERT INTO unified_transactions (source_file, line_number, settlement_id, order_id, sku, transaction_status, raw_type, amount, record_ref, summary_field) VALUES ('{r['source_file']}', {r['line_number']}, '{r['settlement_id']}', '{r['order_id']}', '{r['sku']}', '{r['transaction_status']}', '{r['raw_type']}', {r['amount']}, '{r['record_ref']}', '{r['summary_field']}');\n")

if __name__ == "__main__":
    run_pipeline()
