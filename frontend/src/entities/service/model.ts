export interface ServiceManifest {
  runtime_root: string;
  services: ManagedService[];
}

export interface ServiceStatusManifest {
  runtime_root: string;
  services: ManagedServiceStatus[];
}

export interface ManagedService {
  name: string;
  label: string;
  cwd: string;
  command: string[];
  log_path: string;
  launchd_plist: string;
}

export interface ManagedServiceStatus {
  name: string;
  check: string;
  running: boolean;
}
