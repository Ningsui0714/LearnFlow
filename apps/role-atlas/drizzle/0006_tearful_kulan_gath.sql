CREATE TABLE `role_jobs` (
	`id` text PRIMARY KEY NOT NULL,
	`kind` text NOT NULL,
	`thread_id` text NOT NULL,
	`project_id` text,
	`base_snapshot_id` text,
	`status` text DEFAULT 'queued' NOT NULL,
	`phase` text DEFAULT 'queued' NOT NULL,
	`attempt` integer DEFAULT 0 NOT NULL,
	`input_json` text DEFAULT '{}' NOT NULL,
	`checkpoint_json` text,
	`result_json` text,
	`lease_owner` text,
	`lease_expires_at` text,
	`error` text,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`updated_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`completed_at` text,
	FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `idx_role_jobs_project_updated` ON `role_jobs` (`project_id`,`updated_at`);--> statement-breakpoint
CREATE INDEX `idx_role_jobs_status_lease` ON `role_jobs` (`status`,`lease_expires_at`);