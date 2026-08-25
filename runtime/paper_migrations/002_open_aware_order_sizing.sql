ALTER TABLE paper_execution_policy
ADD COLUMN open_aware_order_sizing integer NOT NULL DEFAULT 0;

CREATE TABLE paper_target_batch (
  id integer PRIMARY KEY AUTOINCREMENT,
  account_id integer NOT NULL DEFAULT 0,
  signal_date varchar(10) NOT NULL DEFAULT '',
  execute_date varchar(10) NOT NULL DEFAULT '',
  target_weights mediumtext,
  status varchar(20) NOT NULL DEFAULT 'PENDING',
  create_time datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  modify_time datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(account_id, execute_date)
);

CREATE INDEX idx_paper_target_batch_due
ON paper_target_batch(account_id, status, execute_date);
