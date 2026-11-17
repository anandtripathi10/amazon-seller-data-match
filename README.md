# Amazon Seller Data Match — Payments vs Settlement Reconciliation

A config-driven financial reconciliation pipeline that ingests Amazon's **Payments report** (horizontal CSV) and **Settlement report** (vertical tab-delimited TXT) for payout batch `12395580393`, matches records across differing granularities using dynamic join keys (`record_ref`), resolves configuration mapping bugs via SQL, and generates dual-sheet Excel accounting reports tying out to Amazon's reported payout ($212,118.95 with **$0.00 net variance**).

---

## Quick Start

### Prerequisites
- Python 3.9+
- Dependencies: `openpyxl`

### Setup & Run
```bash
# 1. Clone repository and navigate to directory
git clone https://github.com/anandtripathi10/amazon-seller-data-match.git
cd amazon-seller-data-match

# 2. Set up virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install openpyxl

# 3. Run the complete pipeline end-to-end
python main.py
```

### Pipeline Stages
1. **Config Ingestion**: Loads payment and settlement mapping configs into database tables (`payment_mapping_configs`, `settlement_mapping_configs`).
2. **Raw File Ingestion**: Ingests 23,026 payments rows and 54,980 settlement rows into a single unified table (`unified_transactions`), preserving raw JSON payloads, source line numbers, and file origin.
3. **Baseline Reconciliation (Before Fixes)**: Computes initial accounting summary and generates `output/report_before_fixes.xlsx`.
4. **Mapping Config Updates**: Applies `MAPPING_FIXES.sql` against the database config tables to resolve mapping bugs.
5. **Re-evaluation & Report Generation**: Re-evaluates transactions and generates `output/report_after_fixes.xlsx` with **$0.00 net variance**.
6. **PostgreSQL Dump Export**: Generates `output/db_dump.sql` (compatible with PostgreSQL 14+).

---

## Deliverables & Output Files

| File | Purpose | Key Result |
| :--- | :--- | :--- |
| `output/report_before_fixes.xlsx` | Baseline Excel Report | Initial delta: **$30.98** |
| `output/report_after_fixes.xlsx` | Final Reconciled Excel Report | Final delta: **$0.00 (Exact Tie-out)** |
| `MAPPING_FIXES.sql` | SQL Config Updates | 7 documented SQL fixes with root cause notes |
| `output/db_dump.sql` | PostgreSQL Dump | Unified table schema + ingested records |
| `ui/index.html` | Local Report Viewer | Browser viewer for summary diffs and sample records |
| `PROGRESS.md` | Investigation Log | Step-by-step notes on how each variance was isolated |

---

## Database Schema Design

### Unified Single-Table Architecture (`unified_transactions`)
Both source files are ingested into a single `unified_transactions` table with a `source_file` discriminator so reconciliation queries operate over one consistent schema without joining separate transaction tables:

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

### Design Rationale
1. **Auditability**: Every figure in the Excel report traces back to its source file, line number, and raw JSON row.
2. **Uniform Join Keys**: Both sources populate `record_ref` using the config template, handling 1:N and N:1 granularity differences directly in SQL/grouping logic.
3. **Database-Driven Configs**: Mapping rules live in `payment_mapping_configs` and `settlement_mapping_configs`. All fixes are applied strictly via SQL updates without hardcoded adjustments in code.

---

## Key Metrics & Run Output

- **Amazon Reported Target Payout**: `$212,118.95`
- **Settlement Report Sum**: `$212,118.95`
- **Reconciled Payments Sum**: `$212,118.95`
- **Final Net Variance**: **`$0.00`**
- **Reconciliation Counts**:
  - **Reconciled Record Pairs**: `8,154`
  - **Unreconciled Payments**: `5,182`
  - **Unreconciled Settlements**: `5,135`

---

## Assumptions Made
1. **Settlement Period Scope**: The settlement file exclusively covers batch `12395580393`. The Payments CSV includes prior/subsequent batches and deferred transactions; only transactions released within batch `12395580393` contribute to this period's payout.
2. **Horizontal vs Vertical Representation**: In Payments, `total` is a row sum of columns rather than an independent charge. Component columns (`product_sales`, `selling_fees`, `fba_fees`, etc.) route to accounting buckets, while `total` is kept only for row-level verification.
3. **Tax Aggregation**: Payments aggregates sales tax into a single column (`sales tax collected`), whereas Settlements splits it into granular lines (`Tax`, `ShippingTax`, `TaxDiscount`, `LowValueGoodsTax`, `GiftWrapTax`). Routing all tax components to `sales_tax` reconciles both sources cleanly ($13,478.97 net).
