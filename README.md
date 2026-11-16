# PortOne SDE II Assignment — Amazon Payments vs Settlement Reconciliation

A production-grade, config-driven financial reconciliation engine that ingests Amazon's **Payments report** (horizontal CSV) and **Settlement report** (vertical flat TSV) for payout batch `12395580393`, matches records across disparate granularities using dynamic join keys (`record_ref`), identifies subtle mapping defects in production configs, and generates CFO-ready dual-sheet accounting reports that tie out 100% to Amazon's reported payout ($212,118.95 with **$0.00 variance**).

---

## 🚀 Quick Start (Running End-to-End)

### Prerequisites
- Python 3.9+
- Dependencies: `openpyxl`

### Setup & Run
```bash
# 1. Clone repository and navigate to directory
cd /Users/anandtripathi/hustle/projects/portone-amazon-recon

# 2. Activate virtual environment (or create one)
source .venv/bin/activate
pip install openpyxl

# 3. Run the complete pipeline end-to-end
python main.py
```

### What this single command executes:
1. **Config Ingestion**: Loads payment and settlement mapping configs into database tables.
2. **Raw File Ingestion**: Ingests 23,026 payments rows and 54,980 settlement rows into a **single unified table** (`unified_transactions`), preserving raw JSON payloads, source line numbers, and file origin.
3. **Baseline Reconciliation (Before Fixes)**: Computes initial accounting summary and generates `output/report_before_fixes.xlsx`.
4. **Automated Defect Correction**: Executes `MAPPING_FIXES.sql` against the database config tables to resolve mapping bugs.
5. **Re-evaluation & Verification**: Re-evaluates transactions and generates final `output/report_after_fixes.xlsx` with **$0.00 variance**.
6. **PostgreSQL Dump Export**: Generates `output/db_dump.sql` (compatible with PostgreSQL 14+).

---

## 📊 Deliverables & Output Files

| File | Purpose | Key Result |
| :--- | :--- | :--- |
| `output/report_before_fixes.xlsx` | Baseline Excel Report | Initial delta: **$30.98** |
| `output/report_after_fixes.xlsx` | Final Reconciled Excel Report | Final delta: **$0.00 (100% Tie-out)** |
| `MAPPING_FIXES.sql` | SQL Config Updates | 7 documented fixes with root cause analysis |
| `output/db_dump.sql` | PostgreSQL Dump | Unified table schema + representative sample data |
| `ui/index.html` | Interactive Dashboard | Visual explorer of steps, diffs, and sample records |
| `PROGRESS.md` | Investigation Progress Log | Step-by-step audit of how variances were isolated |

---

## 🏗️ Database Schema Design

### Mandatory Single-Table Architecture (`unified_transactions`)
Per assignment requirements (*"Important :: Ingest both the files in a single table, not in two different tables"*), all source transactions are stored in `unified_transactions`:

```sql
CREATE TABLE unified_transactions (
    id SERIAL PRIMARY KEY,
    source_file VARCHAR(50) NOT NULL,       -- 'AMAZON_PAYMENTS' or 'AMAZON_SETTLEMENTS'
    line_number INT NOT NULL,               -- Source file line number for audit trail
    settlement_id VARCHAR(50),              -- Amazon settlement batch ID
    order_id VARCHAR(100),                  -- Amazon Order ID
    sku VARCHAR(100),                       -- Merchant SKU
    transaction_date TIMESTAMP,             -- Parsed ISO date (YYYY-MM-DD)
    transaction_date_str VARCHAR(100),      -- Original raw timestamp string
    release_date_str VARCHAR(100),          -- Payment transaction release timestamp
    transaction_status VARCHAR(50),         -- 'Released' or 'Deferred'
    raw_type VARCHAR(100),                  -- Source transaction type (Order, Refund, etc.)
    normalized_type VARCHAR(100),           -- Normalized key (ORDER, REFUND, etc.)
    raw_description TEXT,                   -- Source fee/product description
    amount_field VARCHAR(100),              -- Source column for payments (e.g. 'product_sales')
    amount_type VARCHAR(100),               -- Settlement amount type (e.g. 'ItemPrice')
    amount_description VARCHAR(100),        -- Settlement amount description (e.g. 'Principal')
    amount NUMERIC(15, 2) NOT NULL,         -- Monetary amount
    quantity INT DEFAULT 0,                 -- Units purchased
    record_ref VARCHAR(255),                -- Dynamic +-joined reconciliation key
    summary_field VARCHAR(100),             -- Target summary field bucket
    raw_payload JSONB                       -- Complete unedited source row
);
```

### Why this schema?
1. **Auditability**: Every dollar in the Excel report traces back to its exact source file, line number, and raw JSON payload.
2. **Uniform Join Keys**: Both file sources populate `record_ref`, allowing unified SQL queries for reconciliation.
3. **Database-Driven Configs**: Mapping configs reside in `payment_mapping_configs` and `settlement_mapping_configs`. Fixes are applied strictly through SQL data updates without hardcoding adjustments into report generation code.

---

## 📈 Key Metrics & Run Output

- **Amazon Reported Target Payout**: `$212,118.95`
- **Settlement Report Sum**: `$212,118.95`
- **Reconciled Payments Sum**: `$212,118.95`
- **Final Net Variance**: **`$0.00`**
- **Reconciliation Counts**:
  - **Reconciled Record Pairs**: `8,154`
  - **Unreconciled Payments**: `5,182`
  - **Unreconciled Settlements**: `5,135`

---

## 🔍 Assumptions Made
1. **Settlement Period Scope**: The settlement file exclusively covers batch `12395580393`. The Payments CSV includes prior/subsequent batches and deferred transactions; only transactions released within batch `12395580393` contribute to this period's payout.
2. **Horizontal vs Vertical Representation**: In Payments, `total` is a row sum of columns, not an independent transaction. Component columns (`product_sales`, `selling_fees`, `fba_fees`) route to accounting buckets, while `total` serves solely for row-level auditing.
3. **Tax Aggregation**: Payments aggregates sales tax into a single column (`sales tax collected`), whereas Settlements provides granular lines (`Tax`, `ShippingTax`, `TaxDiscount`). Both aggregate cleanly to the exact cent ($13,478.97 net).
