export interface WorkspaceRef {
  id: number;
  name: string;
}

export interface CurrentWorkspace extends WorkspaceRef {
  role: string | null;
  role_label: string;
}

export interface Me {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  full_name: string;
  is_superuser: boolean;
  avatar: string | null;
  job_title: string;
  workspace: CurrentWorkspace | null;
  workspaces: WorkspaceRef[];
  permissions: string[];
}
