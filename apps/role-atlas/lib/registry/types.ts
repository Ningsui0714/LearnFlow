import type { EvidencePolicy, PackageVisibility } from "@/lib/packages/types";

export type MaintenanceKind = "role_atlas" | "source_official" | "community" | "private";
export type HostingKind = "bundled" | "hosted" | "remote";

export type RegistryScope = {
  market?: string;
  industries?: string[];
  educationStages?: string[];
  audiences?: string[];
  region?: string;
};

export type RegistryMetadata = {
  maintainerName?: string;
  maintainerKind?: "role_atlas" | "source_organization" | "community" | "organization" | "individual";
  maintenanceKind?: MaintenanceKind;
  maintenancePolicy?: {
    reviewCadence?: string;
    updateTriggers?: string[];
    notes?: string;
  };
  hostingKind?: HostingKind;
  visibility?: PackageVisibility;
  license?: string;
  evidencePolicy?: EvidencePolicy;
  protocolRange?: string;
  scope?: RegistryScope;
};
