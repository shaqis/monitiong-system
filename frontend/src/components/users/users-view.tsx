"use client";

import { useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import {
  KeyRound,
  Loader2,
  MoreHorizontal,
  ShieldCheck,
  ShieldX,
  UserCheck,
  UserX,
  UserPlus,
} from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ResetPasswordDialog } from "@/components/users/reset-password-dialog";
import { UserFormModal } from "@/components/users/user-form-modal";
import { ApiError, updateUser } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { User } from "@/types";

interface UsersViewProps {
  initialUsers: User[];
  currentUser: User;
}

interface Feedback {
  variant: "success" | "destructive";
  title: string;
  body: string;
}

function isLastActiveAdmin(user: User, users: User[]): boolean {
  if (user.role !== "admin" || !user.is_active) {
    return false;
  }
  const activeAdmins = users.filter((entry) => entry.role === "admin" && entry.is_active);
  return activeAdmins.length <= 1;
}

export function UsersView({ initialUsers, currentUser }: UsersViewProps) {
  const router = useRouter();
  const [users, setUsers] = useState<User[]>(initialUsers);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [resetTarget, setResetTarget] = useState<User | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    setUsers(initialUsers);
  }, [initialUsers]);

  function refresh() {
    startTransition(() => {
      router.refresh();
    });
  }

  function replaceUser(updated: User) {
    setUsers((previous) =>
      previous.map((entry) => (entry.id === updated.id ? updated : entry)),
    );
  }

  async function handleRoleToggle(user: User) {
    const nextRole = user.role === "admin" ? "viewer" : "admin";
    setPendingId(user.id);
    setFeedback(null);
    try {
      const updated = await updateUser(user.id, { role: nextRole });
      replaceUser(updated);
      setFeedback({
        variant: "success",
        title: "Role updated",
        body: `${updated.full_name} is now ${updated.role}.`,
      });
      refresh();
    } catch (caught) {
      setFeedback({
        variant: "destructive",
        title: "Role update rejected",
        body:
          caught instanceof ApiError
            ? caught.message
            : "The role could not be changed.",
      });
    } finally {
      setPendingId(null);
    }
  }

  async function handleActiveToggle(user: User) {
    setPendingId(user.id);
    setFeedback(null);
    try {
      const updated = await updateUser(user.id, { is_active: !user.is_active });
      replaceUser(updated);
      setFeedback({
        variant: "success",
        title: updated.is_active ? "Account activated" : "Account deactivated",
        body: `${updated.full_name} is now ${updated.is_active ? "active" : "inactive"}.`,
      });
      refresh();
    } catch (caught) {
      setFeedback({
        variant: "destructive",
        title: "Status update rejected",
        body:
          caught instanceof ApiError
            ? caught.message
            : "The account status could not be changed.",
      });
    } finally {
      setPendingId(null);
    }
  }

  function handleCreated(user: User) {
    setUsers((previous) => [...previous, user]);
    setFeedback({
      variant: "success",
      title: "User created",
      body: `${user.full_name} can now sign in as ${user.role}.`,
    });
    refresh();
  }

  function handlePasswordReset(user: User) {
    replaceUser(user);
    setFeedback({
      variant: "success",
      title: "Password reset",
      body: `The password for ${user.full_name} was updated.`,
    });
    refresh();
  }

  const currentUserRecord = users.find((entry) => entry.id === currentUser.id) ?? currentUser;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">Users</h2>
          <p className="text-sm text-muted-foreground">
            Create accounts, change roles, and control access.
          </p>
        </div>
        <Button type="button" onClick={() => setCreateOpen(true)}>
          <UserPlus aria-hidden="true" />
          Create user
        </Button>
      </div>

      {feedback ? (
        <Alert variant={feedback.variant}>
          <div>
            <AlertTitle>{feedback.title}</AlertTitle>
            <AlertDescription>{feedback.body}</AlertDescription>
          </div>
        </Alert>
      ) : null}

      {users.length === 0 ? (
        <EmptyState
          title="No users found"
          description="Create the first account to give someone access."
          action={
            <Button type="button" onClick={() => setCreateOpen(true)}>
              <UserPlus aria-hidden="true" />
              Create user
            </Button>
          }
        />
      ) : (
        <div className={cn("rounded-xl border bg-white", isPending && "opacity-60")}>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Full name</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Created</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.map((user) => {
                const lastActiveAdmin = isLastActiveAdmin(user, users);
                const isSelf = user.id === currentUserRecord.id;
                const rowPending = pendingId === user.id;
                return (
                  <TableRow key={user.id}>
                    <TableCell className="font-medium">
                      {user.full_name}
                      {isSelf ? (
                        <span className="ml-2 text-xs text-muted-foreground">(you)</span>
                      ) : null}
                    </TableCell>
                    <TableCell className="text-muted-foreground">{user.email}</TableCell>
                    <TableCell>
                      <Badge variant={user.role === "admin" ? "default" : "secondary"}>
                        {user.role}
                      </Badge>
                      {lastActiveAdmin ? (
                        <Badge variant="warning" className="ml-2">
                          Last active admin
                        </Badge>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      <Badge variant={user.is_active ? "success" : "muted"}>
                        {user.is_active ? "Active" : "Inactive"}
                      </Badge>
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">
                      {formatDateTime(user.created_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            aria-label={`Actions for ${user.full_name}`}
                            disabled={rowPending}
                          >
                            {rowPending ? (
                              <Loader2 className="animate-spin" aria-hidden="true" />
                            ) : (
                              <MoreHorizontal aria-hidden="true" />
                            )}
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-52">
                          <DropdownMenuItem
                            disabled={lastActiveAdmin && user.role === "admin"}
                            title={
                              lastActiveAdmin && user.role === "admin"
                                ? "Cannot demote the last active admin"
                                : undefined
                            }
                            onSelect={() => void handleRoleToggle(user)}
                          >
                            {user.role === "admin" ? (
                              <>
                                <ShieldX className="h-4 w-4" aria-hidden="true" />
                                Make viewer
                              </>
                            ) : (
                              <>
                                <ShieldCheck className="h-4 w-4" aria-hidden="true" />
                                Make admin
                              </>
                            )}
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            disabled={lastActiveAdmin && user.is_active}
                            title={
                              lastActiveAdmin && user.is_active
                                ? "Cannot deactivate the last active admin"
                                : undefined
                            }
                            onSelect={() => void handleActiveToggle(user)}
                          >
                            {user.is_active ? (
                              <>
                                <UserX className="h-4 w-4" aria-hidden="true" />
                                Deactivate
                              </>
                            ) : (
                              <>
                                <UserCheck className="h-4 w-4" aria-hidden="true" />
                                Activate
                              </>
                            )}
                          </DropdownMenuItem>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem onSelect={() => setResetTarget(user)}>
                            <KeyRound className="h-4 w-4" aria-hidden="true" />
                            Reset password
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}

      <UserFormModal open={createOpen} onOpenChange={setCreateOpen} onCreated={handleCreated} />

      <ResetPasswordDialog
        open={resetTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            setResetTarget(null);
          }
        }}
        user={resetTarget}
        onReset={handlePasswordReset}
      />
    </div>
  );
}
