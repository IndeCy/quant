import { getJson } from "../../shared/api/client";
import type { ServiceManifest } from "./model";

export function getServiceManifest(): Promise<ServiceManifest> {
  return getJson<ServiceManifest>("/api/services/manifest");
}
