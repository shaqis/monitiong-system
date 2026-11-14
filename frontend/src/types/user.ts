import type { Role } from "./auth";

export interface UserCreateInput {
  email: string;
  full_name: string;
  password: string;
  role: Role;
}

export interface UserUpdateInput {
  full_name?: string;
  password?: string;
  role?: Role;
  is_active?: boolean;
}
