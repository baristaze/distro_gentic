-- Every column of the platform's own that names an agent session, an agent
-- step, a spend hold, a spend budget, or an agent workspace says so, as
-- the engine's own columns do, and so does every index over one. Every
-- row stays.

ALTER TABLE activity.execution_records RENAME COLUMN session_id TO agent_session_id;
ALTER TABLE activity.execution_records RENAME COLUMN step_id TO agent_step_id;
ALTER INDEX activity.ix_execution_records_org_id_session_id_id RENAME TO ix_execution_records_org_id_agent_session_id_id;
ALTER TABLE activity.inferences RENAME COLUMN session_id TO agent_session_id;
ALTER TABLE activity.inferences RENAME COLUMN step_id TO agent_step_id;
ALTER INDEX activity.ix_inferences_org_id_session_id_id RENAME TO ix_inferences_org_id_agent_session_id_id;
ALTER INDEX activity.ix_budget_holds_created_at RENAME TO ix_spend_budget_holds_created_at;
ALTER TABLE activity.spend_ledger_entries RENAME COLUMN session_id TO agent_session_id;
ALTER TABLE activity.spend_ledger_entries RENAME COLUMN hold_id TO spend_hold_id;
ALTER INDEX activity.ix_spend_ledger_entries_org_id_hold_id RENAME TO ix_spend_ledger_entries_org_id_spend_hold_id;
ALTER INDEX activity.ix_spend_ledger_entries_org_id_session_id_created_at RENAME TO ix_spend_ledger_entries_org_id_agent_session_id_created_at;
ALTER INDEX activity.uq_spend_ledger_entries_org_id_kind_hold_id RENAME TO uq_spend_ledger_entries_org_id_kind_spend_hold_id;
ALTER TABLE activity.validations RENAME COLUMN session_id TO agent_session_id;
ALTER INDEX activity.ix_validations_org_id_session_id_id RENAME TO ix_validations_org_id_agent_session_id_id;

-- Each not-null constraint takes the name its table and column give it,
-- as Postgres gives one it makes: a renamed table or column keeps the
-- name it had.
ALTER TABLE activity.execution_records RENAME CONSTRAINT execution_records_environment_not_null TO execution_records_run_image_not_null;
ALTER TABLE activity.execution_records RENAME CONSTRAINT execution_records_project_not_null TO execution_records_agent_project_not_null;
ALTER TABLE activity.execution_records RENAME CONSTRAINT execution_records_session_id_not_null TO execution_records_agent_session_id_not_null;
ALTER TABLE activity.validations RENAME CONSTRAINT validations_project_not_null TO validations_agent_project_not_null;
ALTER TABLE activity.validations RENAME CONSTRAINT validations_session_id_not_null TO validations_agent_session_id_not_null;
ALTER TABLE activity.inferences RENAME CONSTRAINT inferences_session_id_not_null TO inferences_agent_session_id_not_null;
ALTER TABLE activity.inferences RENAME CONSTRAINT inferences_step_id_not_null TO inferences_agent_step_id_not_null;
ALTER TABLE activity.spend_ledger_counts RENAME CONSTRAINT ledger_counts_added_not_null TO spend_ledger_counts_added_not_null;
ALTER TABLE activity.spend_ledger_counts RENAME CONSTRAINT ledger_counts_counter_not_null TO spend_ledger_counts_counter_not_null;
ALTER TABLE activity.spend_ledger_counts RENAME CONSTRAINT ledger_counts_held_not_null TO spend_ledger_counts_held_not_null;
ALTER TABLE activity.spend_ledger_counts RENAME CONSTRAINT ledger_counts_org_id_not_null TO spend_ledger_counts_org_id_not_null;
ALTER TABLE activity.spend_ledger_counts RENAME CONSTRAINT ledger_counts_spent_not_null TO spend_ledger_counts_spent_not_null;
ALTER TABLE activity.spend_ledger_counts RENAME CONSTRAINT ledger_counts_start_not_null TO spend_ledger_counts_start_not_null;
ALTER TABLE activity.spend_ledger_entries RENAME CONSTRAINT ledger_entries_body_not_null TO spend_ledger_entries_body_not_null;
ALTER TABLE activity.spend_ledger_entries RENAME CONSTRAINT ledger_entries_created_at_not_null TO spend_ledger_entries_created_at_not_null;
ALTER TABLE activity.spend_ledger_entries RENAME CONSTRAINT ledger_entries_id_not_null TO spend_ledger_entries_id_not_null;
ALTER TABLE activity.spend_ledger_entries RENAME CONSTRAINT ledger_entries_kind_not_null TO spend_ledger_entries_kind_not_null;
ALTER TABLE activity.spend_ledger_entries RENAME CONSTRAINT ledger_entries_org_id_not_null TO spend_ledger_entries_org_id_not_null;
