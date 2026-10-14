-- An execution record names the image it ran on: its run image.
ALTER TABLE activity.execution_records RENAME COLUMN environment TO run_image;
