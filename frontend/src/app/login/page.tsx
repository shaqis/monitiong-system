"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Activity, Loader2 } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

export default function LoginPage() {
  const router = useRouter();
  const { login, user } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (user) {
      router.replace("/dashboard");
    }
  }, [user, router]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      await login({ email: email.trim(), password });
      router.replace("/dashboard");
      router.refresh();
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(caught.message);
      } else {
        setError("Unable to reach the server. Try again.");
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-100 px-4 py-12">
      <div className="w-full max-w-md space-y-6">
        <div className="flex flex-col items-center gap-2 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow">
            <Activity className="h-6 w-6" aria-hidden="true" />
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">Uptime Monitor</h1>
          <p className="text-sm text-muted-foreground">
            Sign in to view dashboards, URLs, and incidents.
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Sign in</CardTitle>
            <CardDescription>Use the account created by your administrator.</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={handleSubmit}>
              {error ? (
                <Alert variant="destructive">
                  <div>
                    <AlertTitle>Sign in failed</AlertTitle>
                    <AlertDescription>{error}</AlertDescription>
                  </div>
                </Alert>
              ) : null}

              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  name="email"
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  disabled={pending}
                  placeholder="you@example.com"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  disabled={pending}
                  placeholder="Your password"
                />
              </div>

              <Button type="submit" className="w-full" disabled={pending || !email || !password}>
                {pending ? (
                  <>
                    <Loader2 className="animate-spin" aria-hidden="true" />
                    Signing in…
                  </>
                ) : (
                  "Sign in"
                )}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
