import { getJson } from "../../shared/api/client";
import type { BackupManifest } from "./model";

export function getBackupManifest(): Promise<BackupManifest> {
  return getJson<BackupManifest>("/api/backup/manifest");
}
