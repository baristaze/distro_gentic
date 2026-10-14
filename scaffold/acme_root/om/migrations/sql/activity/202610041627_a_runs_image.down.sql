-- The release before reads a record's environment.
ALTER TABLE activity.execution_records RENAME COLUMN run_image TO environment;
