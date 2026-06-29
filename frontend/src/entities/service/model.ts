export interface ServiceManifest {
  runtime_root: string;
  services: ManagedService[];
}

export interface ManagedService {
  name: string;
  label: string;
  cwd: string;
  command: string[];
  log_path: string;
  launchd_plist: string;
}
