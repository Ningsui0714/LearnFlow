ALTER TABLE `package_lines` ADD `maintenance_policy_json` text DEFAULT '{}' NOT NULL;--> statement-breakpoint
ALTER TABLE `package_lines` ADD `superseded_by_package_line_id` text;--> statement-breakpoint
ALTER TABLE `package_releases` ADD `snapshot_as_of` text DEFAULT '' NOT NULL;--> statement-breakpoint
ALTER TABLE `package_releases` ADD `protocol_version` text DEFAULT '2.0.0' NOT NULL;--> statement-breakpoint
UPDATE `package_lines` SET `maintenance_policy_json`='{"reviewCadence":"按需","updateTriggers":["重要来源变化","用户迭代"]}' WHERE `maintenance_policy_json`='{}';
