"use client";

import { useState } from "react";
import { Loader2, Send } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ApiError, sendTestNotification } from "@/lib/api";
import type { NotificationSettings } from "@/types";

interface Feedback {
  variant: "success" | "destructive";
  title: string;
  body: string;
}

function providerLabel(provider: NotificationSettings["provider"]): string {
  switch (provider) {
    case "smtp":
      return "SMTP";
    case "brevo":
      return "Brevo";
    case "mailgun":
      return "Mailgun";
    case "mailtrap":
      return "Mailtrap";
  }
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1 border-b pb-3 last:border-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="break-all text-sm font-medium sm:text-right">{value}</dd>
    </div>
  );
}

interface NotificationSettingsViewProps {
  settings: NotificationSettings;
}

export function NotificationSettingsView({ settings }: NotificationSettingsViewProps) {
  const [pending, setPending] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  async function sendTest() {
    setPending(true);
    setFeedback(null);
    try {
      await sendTestNotification();
      const count = settings.recipients.length;
      setFeedback({
        variant: "success",
        title: "Test email sent",
        body:
          count === 1
            ? "The provider accepted the message for 1 recipient."
            : `The provider accepted the message for ${count} recipients.`,
      });
    } catch (error) {
      setFeedback({
        variant: "destructive",
        title: "Test email failed",
        body: error instanceof ApiError ? error.message : "The request failed. Try again.",
      });
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Email notifications are configured through the backend environment. This page shows
          the effective configuration and lets you send a test.
        </p>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle>Email notifications</CardTitle>
              <CardDescription>Incident open and recovery alerts.</CardDescription>
            </div>
            <div className="flex gap-2">
              <Badge variant={settings.enabled ? "success" : "muted"}>
                {settings.enabled ? "Enabled" : "Disabled"}
              </Badge>
              <Badge variant={settings.configured ? "success" : "warning"}>
                {settings.configured ? "Ready to send" : "Not configured"}
              </Badge>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          <dl className="space-y-3">
            <DetailRow label="Provider" value={providerLabel(settings.provider)} />
            <DetailRow
              label="From"
              value={
                settings.from_address
                  ? `${settings.from_name} <${settings.from_address}>`
                  : "Not set"
              }
            />
            <DetailRow
              label="Recipients"
              value={settings.recipients.length > 0 ? settings.recipients.join(", ") : "None"}
            />
            <DetailRow label="Timeout" value={`${settings.timeout_seconds} seconds`} />
          </dl>

          <div>
            <h2 className="text-sm font-semibold">Provider details</h2>
            <dl className="mt-3 space-y-3">
              {settings.provider === "smtp" ? (
                <>
                  <DetailRow label="SMTP host" value={settings.smtp_host ?? "Not set"} />
                  <DetailRow label="SMTP port" value={String(settings.smtp_port)} />
                  <DetailRow
                    label="STARTTLS"
                    value={settings.smtp_starttls ? "Enabled" : "Disabled"}
                  />
                  <DetailRow
                    label="Implicit TLS"
                    value={settings.smtp_ssl ? "Enabled" : "Disabled"}
                  />
                  <DetailRow
                    label="Authentication"
                    value={
                      settings.smtp_username_set
                        ? "Username and password set"
                        : "No authentication"
                    }
                  />
                </>
              ) : null}
              {settings.provider === "mailgun" ? (
                <DetailRow
                  label="Mailgun domain"
                  value={settings.mailgun_domain ?? "Not set"}
                />
              ) : null}
              {settings.provider !== "smtp" ? (
                <DetailRow
                  label="API credentials"
                  value={settings.provider_credentials_set ? "Set" : "Missing"}
                />
              ) : null}
            </dl>
          </div>

          <div className="flex flex-col gap-3 rounded-md border bg-muted/40 p-4 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-muted-foreground">
              The test sends to the configured recipients. It works while notifications are
              disabled, so you can verify credentials first.
            </p>
            <Button
              type="button"
              onClick={sendTest}
              disabled={pending || !settings.configured}
            >
              {pending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Send className="mr-2 h-4 w-4" />
              )}
              Send test email
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

          <p className="text-xs text-muted-foreground">
            Credentials are read from the backend environment. This page never displays
            secrets.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
