import { getJson } from "../../shared/api/client";
import type { ServiceManifest, ServiceStatusManifest } from "./model";

export function getServiceManifest(): Promise<ServiceManifest> {
  return getJson<ServiceManifest>("/api/services/manifest");
}

export function getServiceStatus(): Promise<ServiceStatusManifest> {
  return getJson<ServiceStatusManifest>("/api/services/status");
}
