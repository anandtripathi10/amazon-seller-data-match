"""
Unified Database Schema and Storage for Amazon Reconciliation.
Supports local SQLite execution and generates standard PostgreSQL DDL / pg_dump.
"""

import sqlite3
import json
from decimal import Decimal
from typing import List, Dict, Any, Optional

def adapt_decimal(d):
    return str(d)

def convert_decimal(s):
    return Decimal(s.decode('utf-8'))

sqlite3.register_adapter(Decimal, adapt_decimal)
sqlite3.register_converter("DECIMAL", convert_decimal)

POSTGRES_SCHEMA_SQL = """
-- PostgreSQL Schema for Amazon Payments vs Settlement Reconciliation
-- Requirement: Ingest both files in a single unified table.

DROP TABLE IF EXISTS unified_transactions CASCADE;
DROP TABLE IF EXISTS payment_mapping_configs CASCADE;
DROP TABLE IF EXISTS settlement_mapping_configs CASCADE;
DROP TABLE IF EXISTS reconciliation_summary CASCADE;

-- 1. Unified Transactions Table (Holds both Payments & Settlements)
CREATE TABLE unified_transactions (
    id SERIAL PRIMARY KEY,
    source_file VARCHAR(50) NOT NULL, -- 'AMAZON_PAYMENTS' or 'AMAZON_SETTLEMENTS'
    line_number INT NOT NULL,
    settlement_id VARCHAR(50),
    order_id VARCHAR(100),
    sku VARCHAR(100),
    transaction_date TIMESTAMP,
    transaction_date_str VARCHAR(100),
    release_date_str VARCHAR(100),
    transaction_status VARCHAR(50),
    raw_type VARCHAR(100),
    normalized_type VARCHAR(100),
    raw_description TEXT,
    amount_field VARCHAR(100),
    amount_type VARCHAR(100),
    amount_description VARCHAR(100),
    amount NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    quantity INT DEFAULT 0,
    marketplace VARCHAR(100),
    fulfillment VARCHAR(100),
    order_city VARCHAR(100),
    order_state VARCHAR(100),
    order_postal VARCHAR(50),
    record_ref VARCHAR(255),
    summary_field VARCHAR(100),
    raw_payload JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_unified_settlement_id ON unified_transactions(settlement_id);
CREATE INDEX idx_unified_order_id ON unified_transactions(order_id);
CREATE INDEX idx_unified_sku ON unified_transactions(sku);
CREATE INDEX idx_unified_record_ref ON unified_transactions(record_ref);
CREATE INDEX idx_unified_source_file ON unified_transactions(source_file);

-- 2. Payment Mapping Config Table
CREATE TABLE payment_mapping_configs (
    id SERIAL PRIMARY KEY,
    transaction_type VARCHAR(100),
    description VARCHAR(255),
    amount_field VARCHAR(100),
    record_ref VARCHAR(255),
    to_summary_field_when_positive_amount VARCHAR(100),
    to_summary_field_when_negative_amount VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    notes TEXT
);

-- 3. Settlement Mapping Config Table
CREATE TABLE settlement_mapping_configs (
    id SERIAL PRIMARY KEY,
    transaction_type VARCHAR(100),
    amount_type VARCHAR(100),
    amount_description VARCHAR(255),
    record_ref VARCHAR(255),
    to_summary_field_when_positive_amount VARCHAR(100),
    to_summary_field_when_negative_amount VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    notes TEXT
);

-- 4. Reconciliation Summary Table
CREATE TABLE reconciliation_summary (
    id SERIAL PRIMARY KEY,
    summary_category VARCHAR(100) NOT NULL,
    line_item VARCHAR(100) NOT NULL,
    summary_field VARCHAR(100) NOT NULL,
    payment_amount NUMERIC(15, 2) DEFAULT 0.00,
    settlement_amount NUMERIC(15, 2) DEFAULT 0.00,
    variance NUMERIC(15, 2) DEFAULT 0.00,
    stage VARCHAR(20) NOT NULL -- 'BEFORE_FIX' or 'AFTER_FIX'
);
"""

class Database:
    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        self.conn.row_factory = sqlite3.Row
        self._init_sqlite_schema()

    def _init_sqlite_schema(self):
        cur = self.conn.cursor()
        cur.executescript("""
        CREATE TABLE IF NOT EXISTS unified_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file TEXT NOT NULL,
            line_number INTEGER NOT NULL,
            settlement_id TEXT,
            order_id TEXT,
            sku TEXT,
            transaction_date TEXT,
            transaction_date_str TEXT,
            release_date_str TEXT,
            transaction_status TEXT,
            raw_type TEXT,
            normalized_type TEXT,
            raw_description TEXT,
            amount_field TEXT,
            amount_type TEXT,
            amount_description TEXT,
            amount DECIMAL NOT NULL DEFAULT '0.00',
            quantity INTEGER DEFAULT 0,
            marketplace TEXT,
            fulfillment TEXT,
            order_city TEXT,
            order_state TEXT,
            order_postal TEXT,
            record_ref TEXT,
            summary_field TEXT,
            raw_payload TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS payment_mapping_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_type TEXT,
            description TEXT,
            amount_field TEXT,
            record_ref TEXT,
            to_summary_field_when_positive_amount TEXT,
            to_summary_field_when_negative_amount TEXT,
            is_active INTEGER DEFAULT 1,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS settlement_mapping_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_type TEXT,
            amount_type TEXT,
            amount_description TEXT,
            record_ref TEXT,
            to_summary_field_when_positive_amount TEXT,
            to_summary_field_when_negative_amount TEXT,
            is_active INTEGER DEFAULT 1,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS reconciliation_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            summary_category TEXT NOT NULL,
            line_item TEXT NOT NULL,
            summary_field TEXT NOT NULL,
            payment_amount DECIMAL DEFAULT '0.00',
            settlement_amount DECIMAL DEFAULT '0.00',
            variance DECIMAL DEFAULT '0.00',
            stage TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_u_sid ON unified_transactions(settlement_id);
        CREATE INDEX IF NOT EXISTS idx_u_oid ON unified_transactions(order_id);
        CREATE INDEX IF NOT EXISTS idx_u_ref ON unified_transactions(record_ref);
        CREATE INDEX IF NOT EXISTS idx_u_src ON unified_transactions(source_file);
        """)
        self.conn.commit()

    def close(self):
        if self.conn:
            self.conn.close()
