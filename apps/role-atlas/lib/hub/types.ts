export type HubChannel = "official" | "community";
export type HubVisibility = "private" | "public";
export type HubSubmissionStatus = "submitted" | "approved" | "rejected" | "published";

export type RolePackageHubPolicy = {
  protocol: "role-package-hub-policy.v1";
  officialMaintainerSubjects: string[];
  reviewerSubjects: string[];
};

export type RolePackageHubSubmission = {
  protocol: "role-package-hub-submission.v1";
  submissionId: string;
  packageId: string;
  packageVersion: string;
  snapshotId: string;
  rootHash: string;
  roleTitle: string;
  ownerSubjectId: string;
  maintainerName: string;
  channel: HubChannel;
  visibility: HubVisibility;
  objectPath: string;
  status: HubSubmissionStatus;
  submittedAt: string;
  reviewedAt?: string;
  reviewerSubjectId?: string;
  reviewNotes?: string;
  publishedAt?: string;
};

export type RolePackageHubCatalogEntry = {
  packageId: string;
  packageVersion: string;
  snapshotId: string;
  rootHash: string;
  roleTitle: string;
  ownerSubjectId: string;
  maintainerName: string;
  channel: HubChannel;
  visibility: HubVisibility;
  review: "not_required_private" | "approved";
  objectPath: string;
  publishedAt: string;
};

export type RolePackageHubCatalog = {
  protocol: "role-package-hub-catalog.v1";
  generatedAt: string;
  entries: RolePackageHubCatalogEntry[];
  rootHash: string;
};
