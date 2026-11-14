"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Loader2 } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ApiError, createUser } from "@/lib/api";
import { isValidEmail, passwordByteLength } from "@/lib/format";
import type { Role, User } from "@/types";

interface UserFormModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (user: User) => void;
}

interface FormState {
  email: string;
  fullName: string;
  password: string;
  role: Role;
}

const EMPTY_FORM: FormState = {
  email: "",
  fullName: "",
  password: "",
  role: "viewer",
};

export function UserFormModal({ open, onOpenChange, onCreated }: UserFormModalProps) {
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setForm(EMPTY_FORM);
      setErrors({});
      setError(null);
    }
  }, [open]);

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((previous) => ({ ...previous, [key]: value }));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const nextErrors: Record<string, string> = {};
    const email = form.email.trim();
    const fullName = form.fullName.trim();

    if (!isValidEmail(email)) {
      nextErrors.email = "Enter a valid email address.";
    }
    if (!fullName) {
      nextErrors.fullName = "Full name is required.";
    } else if (fullName.length > 120) {
      nextErrors.fullName = "Full name must be at most 120 characters.";
    }
    const passwordBytes = passwordByteLength(form.password);
    if (form.password.length < 12) {
      nextErrors.password = "Password must be at least 12 characters.";
    } else if (passwordBytes > 72) {
      nextErrors.password = "Password must be at most 72 bytes.";
    }

    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) {
      return;
    }

    setSaving(true);
    try {
      const created = await createUser({
        email,
        full_name: fullName,
        password: form.password,
        role: form.role,
      });
      onOpenChange(false);
      onCreated(created);
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(caught.message);
        const mapped: Record<string, string> = {};
        for (const field of caught.fields) {
          if (field.field) {
            mapped[field.field] = field.message;
          }
        }
        setErrors(mapped);
      } else {
        setError("The user could not be created.");
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create user</DialogTitle>
          <DialogDescription>
            Add an account with a temporary password. Share it securely.
          </DialogDescription>
        </DialogHeader>

        <form className="space-y-4" onSubmit={handleSubmit}>
          {error ? (
            <Alert variant="destructive">
              <div>
                <AlertTitle>Could not create user</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </div>
            </Alert>
          ) : null}

          <div className="space-y-2">
            <Label htmlFor="user-email">Email</Label>
            <Input
              id="user-email"
              type="email"
              value={form.email}
              onChange={(event) => update("email", event.target.value)}
              placeholder="person@example.com"
              disabled={saving}
              autoComplete="off"
            />
            {errors.email ? <p className="text-xs text-red-600">{errors.email}</p> : null}
          </div>

          <div className="space-y-2">
            <Label htmlFor="user-name">Full name</Label>
            <Input
              id="user-name"
              value={form.fullName}
              onChange={(event) => update("fullName", event.target.value)}
              placeholder="Ada Lovelace"
              disabled={saving}
              autoComplete="off"
            />
            {errors.full_name ? (
              <p className="text-xs text-red-600">{errors.full_name}</p>
            ) : errors.fullName ? (
              <p className="text-xs text-red-600">{errors.fullName}</p>
            ) : null}
          </div>

          <div className="space-y-2">
            <Label htmlFor="user-password">Temporary password</Label>
            <Input
              id="user-password"
              type="password"
              value={form.password}
              onChange={(event) => update("password", event.target.value)}
              disabled={saving}
              autoComplete="new-password"
            />
            <p className="text-xs text-muted-foreground">
              At least 12 characters and at most 72 bytes.
            </p>
            {errors.password ? <p className="text-xs text-red-600">{errors.password}</p> : null}
          </div>

          <div className="space-y-2">
            <Label htmlFor="user-role">Role</Label>
            <Select
              value={form.role}
              onValueChange={(value) => update("role", value === "admin" ? "admin" : "viewer")}
              disabled={saving}
            >
              <SelectTrigger id="user-role">
                <SelectValue placeholder="Select role" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="viewer">Viewer</SelectItem>
                <SelectItem value="admin">Admin</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? (
                <>
                  <Loader2 className="animate-spin" aria-hidden="true" />
                  Creating…
                </>
              ) : (
                "Create user"
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
