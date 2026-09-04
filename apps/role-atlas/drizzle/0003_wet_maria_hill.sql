CREATE TABLE `workspace_ingestion_events` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`run_id` text NOT NULL,
	`seq` integer NOT NULL,
	`kind` text NOT NULL,
	`event_json` text NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`run_id`) REFERENCES `workspace_ingestion_runs`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_workspace_ingestion_events_run_seq` ON `workspace_ingestion_events` (`run_id`,`seq`);--> statement-breakpoint
CREATE TABLE `workspace_ingestion_runs` (
	`id` text PRIMARY KEY NOT NULL,
	`project_id` text,
	`base_snapshot_id` text,
	`iteration_run_id` text,
	`adapter_id` text NOT NULL,
	`package_id` text,
	`status` text DEFAULT 'running' NOT NULL,
	`phase` text DEFAULT 'register' NOT NULL,
	`input_json` text NOT NULL,
	`checkpoint_json` text,
	`result_json` text,
	`alignment_json` text,
	`error` text,
	`started_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`completed_at` text
);
--> statement-breakpoint
CREATE INDEX `idx_workspace_ingestion_runs_project_started` ON `workspace_ingestion_runs` (`project_id`,`started_at`);