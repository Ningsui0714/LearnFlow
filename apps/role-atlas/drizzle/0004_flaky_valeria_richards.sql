CREATE TABLE `maintainers` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`kind` text NOT NULL,
	`description` text DEFAULT '' NOT NULL,
	`url` text,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);
--> statement-breakpoint
CREATE TABLE `package_artifacts` (
	`root_hash` text PRIMARY KEY NOT NULL,
	`artifact_kind` text NOT NULL,
	`media_type` text NOT NULL,
	`byte_size` integer NOT NULL,
	`content` text,
	`storage_key` text,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);
--> statement-breakpoint
CREATE TABLE `package_lines` (
	`id` text PRIMARY KEY NOT NULL,
	`role_identity_id` text NOT NULL,
	`package_id` text NOT NULL,
	`title` text NOT NULL,
	`scope_json` text DEFAULT '{}' NOT NULL,
	`maintainer_id` text NOT NULL,
	`maintenance_kind` text NOT NULL,
	`hosting_kind` text DEFAULT 'hosted' NOT NULL,
	`visibility` text DEFAULT 'private' NOT NULL,
	`license` text DEFAULT 'unspecified' NOT NULL,
	`evidence_policy` text DEFAULT 'metadata' NOT NULL,
	`protocol_range` text DEFAULT '^2.0.0' NOT NULL,
	`status` text DEFAULT 'active' NOT NULL,
	`recommended_release_id` text,
	`registry_version` integer DEFAULT 0 NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`updated_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`role_identity_id`) REFERENCES `role_identities`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`maintainer_id`) REFERENCES `maintainers`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_package_lines_package_id` ON `package_lines` (`package_id`);--> statement-breakpoint
CREATE INDEX `idx_package_lines_role_identity` ON `package_lines` (`role_identity_id`);--> statement-breakpoint
CREATE TABLE `package_releases` (
	`id` text PRIMARY KEY NOT NULL,
	`package_line_id` text NOT NULL,
	`project_id` text,
	`source_project_version_id` text,
	`snapshot_id` text NOT NULL,
	`package_version` text NOT NULL,
	`status` text NOT NULL,
	`artifact_root_hash` text,
	`validation_report_hash` text,
	`supersedes_release_id` text,
	`error` text,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`published_at` text,
	FOREIGN KEY (`package_line_id`) REFERENCES `package_lines`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE set null,
	FOREIGN KEY (`source_project_version_id`) REFERENCES `project_versions`(`id`) ON UPDATE no action ON DELETE set null
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_package_releases_line_version` ON `package_releases` (`package_line_id`,`package_version`);--> statement-breakpoint
CREATE INDEX `idx_package_releases_snapshot` ON `package_releases` (`snapshot_id`);--> statement-breakpoint
CREATE TABLE `project_tags` (
	`id` text PRIMARY KEY NOT NULL,
	`project_id` text NOT NULL,
	`name` text NOT NULL,
	`target_version_id` text NOT NULL,
	`description` text DEFAULT '' NOT NULL,
	`created_by` text DEFAULT 'user' NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`target_version_id`) REFERENCES `project_versions`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_project_tags_project_name` ON `project_tags` (`project_id`,`name`);--> statement-breakpoint
CREATE TABLE `project_version_events` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`project_id` text NOT NULL,
	`version_id` text,
	`action` text NOT NULL,
	`actor_kind` text DEFAULT 'user' NOT NULL,
	`detail_json` text DEFAULT '{}' NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`version_id`) REFERENCES `project_versions`(`id`) ON UPDATE no action ON DELETE set null
);
--> statement-breakpoint
CREATE INDEX `idx_project_version_events_project_created` ON `project_version_events` (`project_id`,`created_at`);--> statement-breakpoint
CREATE TABLE `reference_migrations` (
	`id` text PRIMARY KEY NOT NULL,
	`from_snapshot_id` text NOT NULL,
	`to_snapshot_id` text NOT NULL,
	`from_target_id` text NOT NULL,
	`to_target_ids_json` text NOT NULL,
	`kind` text NOT NULL,
	`confidence` integer NOT NULL,
	`reason` text DEFAULT '' NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_reference_migrations_path` ON `reference_migrations` (`from_snapshot_id`,`to_snapshot_id`,`from_target_id`);--> statement-breakpoint
CREATE TABLE `release_events` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`release_id` text,
	`package_line_id` text NOT NULL,
	`project_id` text,
	`action` text NOT NULL,
	`actor_kind` text DEFAULT 'user' NOT NULL,
	`detail_json` text DEFAULT '{}' NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`release_id`) REFERENCES `package_releases`(`id`) ON UPDATE no action ON DELETE set null,
	FOREIGN KEY (`package_line_id`) REFERENCES `package_lines`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE set null
);
--> statement-breakpoint
CREATE INDEX `idx_release_events_line_created` ON `release_events` (`package_line_id`,`created_at`);--> statement-breakpoint
CREATE TABLE `role_identities` (
	`id` text PRIMARY KEY NOT NULL,
	`canonical_name` text NOT NULL,
	`aliases_json` text DEFAULT '[]' NOT NULL,
	`description` text DEFAULT '' NOT NULL,
	`occupation_codes_json` text DEFAULT '[]' NOT NULL,
	`industry_domains_json` text DEFAULT '[]' NOT NULL,
	`status` text DEFAULT 'active' NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`updated_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_role_identities_name` ON `role_identities` (`canonical_name`);--> statement-breakpoint
CREATE TABLE `semantic_diffs` (
	`id` text PRIMARY KEY NOT NULL,
	`project_id` text,
	`from_version_id` text NOT NULL,
	`to_version_id` text NOT NULL,
	`algorithm_version` text NOT NULL,
	`diff_json` text NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`from_version_id`) REFERENCES `project_versions`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`to_version_id`) REFERENCES `project_versions`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_semantic_diffs_pair_algorithm` ON `semantic_diffs` (`from_version_id`,`to_version_id`,`algorithm_version`);--> statement-breakpoint
CREATE INDEX `idx_semantic_diffs_project_created` ON `semantic_diffs` (`project_id`,`created_at`);--> statement-breakpoint
ALTER TABLE `project_versions` ADD `parent_version_id` text;--> statement-breakpoint
ALTER TABLE `project_versions` ADD `source_run_id` text;--> statement-breakpoint
ALTER TABLE `project_versions` ADD `source_kind` text DEFAULT 'legacy' NOT NULL;--> statement-breakpoint
ALTER TABLE `project_versions` ADD `root_hash` text DEFAULT 'legacy' NOT NULL;--> statement-breakpoint
ALTER TABLE `project_versions` ADD `message` text DEFAULT '' NOT NULL;--> statement-breakpoint
ALTER TABLE `project_versions` ADD `author_kind` text DEFAULT 'system' NOT NULL;--> statement-breakpoint
CREATE UNIQUE INDEX `idx_project_versions_project_source_run` ON `project_versions` (`project_id`,`source_run_id`);--> statement-breakpoint
ALTER TABLE `projects` ADD `head_version_id` text;--> statement-breakpoint
ALTER TABLE `projects` ADD `current_release_id` text;--> statement-breakpoint
ALTER TABLE `snapshot_versions` ADD `content_hash` text DEFAULT 'legacy' NOT NULL;--> statement-breakpoint
ALTER TABLE `snapshot_versions` ADD `source_run_id` text;--> statement-breakpoint
ALTER TABLE `snapshot_versions` ADD `protocol_version` text DEFAULT '2.0.0' NOT NULL;
--> statement-breakpoint
UPDATE `projects` SET `head_version_id`=`active_version_id` WHERE `head_version_id` IS NULL AND `active_version_id` IS NOT NULL;
--> statement-breakpoint
UPDATE `project_versions` SET `source_run_id`=`build_run_id` WHERE `source_run_id` IS NULL;
--> statement-breakpoint
UPDATE `conversations` SET `version_id`=(
	SELECT `pv`.`id` FROM `project_versions` `pv`
	WHERE `pv`.`project_id`=`conversations`.`project_id` AND `pv`.`snapshot_id`=`conversations`.`snapshot_id`
	ORDER BY `pv`.`created_at` DESC LIMIT 1
) WHERE `version_id` IS NULL AND `snapshot_id` IS NOT NULL;
