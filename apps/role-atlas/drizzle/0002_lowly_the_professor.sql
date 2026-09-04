CREATE TABLE `risk_events` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`run_id` text NOT NULL,
	`project_id` text NOT NULL,
	`seq` integer NOT NULL,
	`kind` text NOT NULL,
	`event_json` text NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`run_id`) REFERENCES `risk_runs`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_risk_events_run_seq` ON `risk_events` (`run_id`,`seq`);--> statement-breakpoint
CREATE TABLE `risk_issues` (
	`id` text NOT NULL,
	`project_id` text NOT NULL,
	`run_id` text NOT NULL,
	`fingerprint` text NOT NULL,
	`profile` text NOT NULL,
	`severity` text NOT NULL,
	`status` text NOT NULL,
	`issue_json` text NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`run_id`) REFERENCES `risk_runs`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_risk_issues_run_id` ON `risk_issues` (`run_id`,`id`);--> statement-breakpoint
CREATE INDEX `idx_risk_issues_project_fingerprint` ON `risk_issues` (`project_id`,`fingerprint`);--> statement-breakpoint
CREATE TABLE `risk_patches` (
	`id` text NOT NULL,
	`project_id` text NOT NULL,
	`run_id` text NOT NULL,
	`iteration` integer NOT NULL,
	`status` text NOT NULL,
	`patch_json` text NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`run_id`) REFERENCES `risk_runs`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_risk_patches_run_id` ON `risk_patches` (`run_id`,`id`);--> statement-breakpoint
CREATE TABLE `risk_runs` (
	`id` text PRIMARY KEY NOT NULL,
	`project_id` text NOT NULL,
	`base_version_id` text NOT NULL,
	`candidate_version_id` text,
	`status` text DEFAULT 'running' NOT NULL,
	`mode` text NOT NULL,
	`phase` text DEFAULT 'baseline' NOT NULL,
	`input_json` text NOT NULL,
	`checkpoint_json` text,
	`result_json` text,
	`error` text,
	`started_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`completed_at` text,
	FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`base_version_id`) REFERENCES `project_versions`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `idx_risk_runs_project_started` ON `risk_runs` (`project_id`,`started_at`);--> statement-breakpoint
CREATE TABLE `snapshot_iteration_events` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`run_id` text NOT NULL,
	`snapshot_id` text NOT NULL,
	`seq` integer NOT NULL,
	`kind` text NOT NULL,
	`event_json` text NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`run_id`) REFERENCES `snapshot_iteration_runs`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_snapshot_iteration_events_run_seq` ON `snapshot_iteration_events` (`run_id`,`seq`);--> statement-breakpoint
CREATE TABLE `snapshot_iteration_runs` (
	`id` text PRIMARY KEY NOT NULL,
	`base_snapshot_id` text NOT NULL,
	`candidate_snapshot_id` text,
	`project_id` text,
	`project_version_id` text,
	`status` text DEFAULT 'running' NOT NULL,
	`initiative_profile` text NOT NULL,
	`phase` text DEFAULT 'contract' NOT NULL,
	`input_json` text NOT NULL,
	`checkpoint_json` text,
	`result_json` text,
	`error` text,
	`started_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`completed_at` text
);
--> statement-breakpoint
CREATE INDEX `idx_snapshot_iteration_runs_base_started` ON `snapshot_iteration_runs` (`base_snapshot_id`,`started_at`);--> statement-breakpoint
CREATE TABLE `snapshot_risk_events` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`run_id` text NOT NULL,
	`snapshot_id` text NOT NULL,
	`seq` integer NOT NULL,
	`kind` text NOT NULL,
	`event_json` text NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`run_id`) REFERENCES `snapshot_risk_runs`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_snapshot_risk_events_run_seq` ON `snapshot_risk_events` (`run_id`,`seq`);--> statement-breakpoint
CREATE TABLE `snapshot_risk_runs` (
	`id` text PRIMARY KEY NOT NULL,
	`base_snapshot_id` text NOT NULL,
	`candidate_snapshot_id` text,
	`project_id` text,
	`project_version_id` text,
	`status` text DEFAULT 'running' NOT NULL,
	`mode` text NOT NULL,
	`phase` text DEFAULT 'snapshot' NOT NULL,
	`input_json` text NOT NULL,
	`checkpoint_json` text,
	`result_json` text,
	`error` text,
	`started_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`completed_at` text
);
--> statement-breakpoint
CREATE INDEX `idx_snapshot_risk_runs_base_started` ON `snapshot_risk_runs` (`base_snapshot_id`,`started_at`);--> statement-breakpoint
CREATE TABLE `snapshot_versions` (
	`snapshot_id` text PRIMARY KEY NOT NULL,
	`parent_snapshot_id` text,
	`package_id` text NOT NULL,
	`package_version` text NOT NULL,
	`status` text DEFAULT 'candidate' NOT NULL,
	`package_json` text NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);
