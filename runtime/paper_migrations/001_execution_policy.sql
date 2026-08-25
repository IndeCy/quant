CREATE TABLE paper_execution_policy (
  account_id integer PRIMARY KEY,
  slippage_bps real NOT NULL DEFAULT 5,
  execution_delay integer NOT NULL DEFAULT 1,
  max_participation_rate real NOT NULL DEFAULT 0.2,
  commission_rate real NOT NULL DEFAULT 0,
  stamp_tax_rate real NOT NULL DEFAULT 0,
  min_commission real NOT NULL DEFAULT 0,
  lot_size integer NOT NULL DEFAULT 1,
  tax_exempt_symbols mediumtext,
  create_time datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  modify_time datetime NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE paper_order ADD COLUMN commission real NOT NULL DEFAULT 0;
ALTER TABLE paper_order ADD COLUMN stamp_tax real NOT NULL DEFAULT 0;
ALTER TABLE paper_order ADD COLUMN execution_impact real NOT NULL DEFAULT 0;
