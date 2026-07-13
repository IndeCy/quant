export interface BackupManifest {
  runtime_root: string;
  generated_at: string;
  backup_command: string;
  items: BackupManifestItem[];
}

export interface BackupManifestItem {
  name: string;
  path: string;
  exists: boolean;
  file_count: number;
  size_bytes: number;
}
