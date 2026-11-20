"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Send } from "lucide-react";
import {
  NotificationProviderFields,
  PROVIDER_SECRET_META,
  type EncryptionMode,
  type ProviderFields,
} from "@/components/settings/notification-provider-fields";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  ApiError,
  sendTestNotification,
  updateNotificationSettings,
} from "@/lib/api";
import type {
  NotificationSettings,
  NotificationSettingsUpdate,
} from "@/types";

interface Feedback {
  variant: "success" | "destructive";
  title: string;
  body: string;
}

interface FormState extends ProviderFields {
  enabled: boolean;
  fromName: string;
  fromAddress: string;
  recipients: string;
}

interface NotificationSettingsViewProps {
  settings: NotificationSettings;
}

function stateFromSettings(settings: NotificationSettings): FormState {
  const provider = settings.provider;
  const encryption: EncryptionMode = settings.smtp_ssl
    ? "ssl"
    : settings.smtp_starttls
      ? "starttls"
      : "none";
  return {
    enabled: settings.enabled,
    provider,
    fromName: settings.from_name,
    fromAddress: settings.from_address ?? "",
    recipients: settings.recipients.join("\n"),
    smtpHost: settings.smtp_host ?? "",
    smtpPort: String(settings.smtp_port || 587),
    encryption,
    smtpUsername: settings.smtp_username ?? "",
    smtpPassword: "",
    brevoApiKey: "",
    mailgunApiKey: "",
    mailgunDomain: settings.mailgun_domain ?? "",
    mailgunApiUrl: settings.mailgun_api_url ?? "",
    mailtrapApiToken: "",
  };
}

function parseRecipients(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((recipient) => recipient.trim())
    .filter((recipient) => recipient.length > 0);
}

function FieldError({ message }: { message: string | undefined }) {
  if (!message) {
    return null;
  }
  return <p className="text-xs text-red-600">{message}</p>;
}

function validateProviderSecrets(
  form: FormState,
  current: NotificationSettings,
): Record<string, string> {
  if (form.provider === "smtp" && form.smtpUsername.trim().length === 0) {
    return {};
  }
  const meta = PROVIDER_SECRET_META[form.provider];
  const hasInput = form[meta.formKey].trim().length > 0;
  if (hasInput || current[meta.setKey]) {
    return {};
  }
  const isUnreadable = current.unreadable_secrets.includes(form.provider);
  return {
    [meta.errorKey]: isUnreadable
      ? `Re-enter the ${meta.label} to replace the undecryptable value.`
      : `${meta.label} is required.`,
  };
}

export function NotificationSettingsView({ settings }: NotificationSettingsViewProps) {
  const router = useRouter();
  const [current, setCurrent] = useState<NotificationSettings>(settings);
  const [form, setForm] = useState<FormState>(() => stateFromSettings(settings));
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((previous) => ({ ...previous, [key]: value }));
    setDirty(true);
  }

  function updateProviderField<K extends keyof ProviderFields>(
    key: K,
    value: ProviderFields[K],
  ) {
    setForm((previous) => ({ ...previous, [key]: value }));
    setDirty(true);
  }

  function changeEncryption(mode: EncryptionMode) {
    setForm((previous) => {
      const defaultPort = previous.smtpPort === "587" || previous.smtpPort === "465";
      let smtpPort = previous.smtpPort;
      if (defaultPort && mode === "starttls") {
        smtpPort = "587";
      } else if (defaultPort && mode === "ssl") {
        smtpPort = "465";
      }
      return { ...previous, encryption: mode, smtpPort };
    });
    setDirty(true);
  }

  function buildInput(): NotificationSettingsUpdate {
    const input: NotificationSettingsUpdate = {
      enabled: form.enabled,
      provider: form.provider,
      from_address: form.fromAddress.trim(),
      from_name: form.fromName.trim(),
      recipients: parseRecipients(form.recipients),
    };
    if (form.provider === "smtp") {
      input.smtp_host = form.smtpHost.trim() || null;
      input.smtp_port = Number(form.smtpPort);
      input.smtp_starttls = form.encryption === "starttls";
      input.smtp_ssl = form.encryption === "ssl";
      input.smtp_username = form.smtpUsername.trim() || null;
    } else if (form.provider === "mailgun") {
      input.mailgun_domain = form.mailgunDomain.trim() || null;
      input.mailgun_api_url = form.mailgunApiUrl.trim() || null;
    }
    const secretMeta = PROVIDER_SECRET_META[form.provider];
    const secretValue = form[secretMeta.formKey];
    if (secretValue.trim().length > 0) {
      input[secretMeta.errorKey] = secretValue;
    }
    return input;
  }

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFeedback(null);
    setError(null);

    const localErrors: Record<string, string> = {};
    if (!form.fromAddress.trim()) {
      localErrors.from_address = "Sender address is required.";
    }
    if (parseRecipients(form.recipients).length === 0) {
      localErrors.recipients = "Add at least one recipient.";
    }
    if (form.provider === "smtp") {
      if (!form.smtpHost.trim()) {
        localErrors.smtp_host = "SMTP host is required.";
      }
      const port = Number(form.smtpPort);
      if (!Number.isInteger(port) || port < 1 || port > 65535) {
        localErrors.smtp_port = "Port must be between 1 and 65535.";
      }
    } else if (form.provider === "mailgun") {
      if (!form.mailgunDomain.trim()) {
        localErrors.mailgun_domain = "Mailgun domain is required.";
      }
    }
    Object.assign(localErrors, validateProviderSecrets(form, current));
    if (Object.keys(localErrors).length > 0) {
      setFieldErrors(localErrors);
      setError(Object.values(localErrors)[0]);
      return;
    }

    setFieldErrors({});
    setSaving(true);
    try {
      const saved = await updateNotificationSettings(buildInput());
      setCurrent(saved);
      setForm(stateFromSettings(saved));
      setDirty(false);
      setFeedback({
        variant: "success",
        title: "Settings saved",
        body: "Incident alerts now use the saved configuration. No restart is needed.",
      });
      router.refresh();
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(caught.message);
        const mapped: Record<string, string> = {};
        for (const field of caught.fields) {
          if (field.field) {
            mapped[field.field] = field.message;
          }
        }
        setFieldErrors(mapped);
      } else {
        setError("Unable to save the notification settings. Try again.");
      }
    } finally {
      setSaving(false);
    }
  }

  async function sendTest() {
    setTesting(true);
    setFeedback(null);
    setError(null);
    try {
      await sendTestNotification();
      const count = current.recipients.length;
      setFeedback({
        variant: "success",
        title: "Test email sent",
        body:
          count === 1
            ? "The provider accepted the message for 1 recipient."
            : `The provider accepted the message for ${count} recipients.`,
      });
    } catch (caught) {
      setFeedback({
        variant: "destructive",
        title: "Test email failed",
        body:
          caught instanceof ApiError
            ? caught.message
            : "The request failed. Try again.",
      });
    } finally {
      setTesting(false);
    }
  }

  const selectedSecretUnreadable = current.unreadable_secrets.includes(form.provider);
  const testDisabled = testing || saving || dirty || !current.configured;
  const testHint = dirty
    ? "Save changes before sending a test."
    : current.configured
      ? "The test sends to the saved recipients and works while alerts are disabled."
      : "Save a complete configuration before sending a test.";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Incident alerts use the configuration saved here. When nothing is saved, the backend
          environment is the fallback. Provider credentials are never displayed.
        </p>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle>Email notifications</CardTitle>
              <CardDescription>Incident open and recovery alerts.</CardDescription>
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge variant={current.enabled ? "success" : "muted"}>
                {current.enabled ? "Enabled" : "Disabled"}
              </Badge>
              <Badge variant={current.configured ? "success" : "warning"}>
                {current.configured ? "Ready to send" : "Not configured"}
              </Badge>
              <Badge variant={current.source === "database" ? "info" : "muted"}>
                {current.source === "database" ? "Saved settings" : "Environment"}
              </Badge>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          {selectedSecretUnreadable ? (
            <Alert variant="warning">
              <div>
                <AlertTitle>Saved secret cannot be decrypted</AlertTitle>
                <AlertDescription>
                  The saved {PROVIDER_SECRET_META[form.provider].label} cannot be decrypted with the
                  current <code>JWT_SECRET</code>. Re-enter it and save changes to restore email
                  notifications.
                </AlertDescription>
              </div>
            </Alert>
          ) : null}

          {error ? (
            <Alert variant="destructive">
              <div>
                <AlertTitle>Could not save</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </div>
            </Alert>
          ) : null}

          {feedback ? (
            <Alert variant={feedback.variant}>
              <div>
                <AlertTitle>{feedback.title}</AlertTitle>
                <AlertDescription>{feedback.body}</AlertDescription>
              </div>
            </Alert>
          ) : null}

          <form className="space-y-6" onSubmit={handleSave} noValidate>
            <div className="flex items-center justify-between gap-4 rounded-lg border p-3">
              <div className="space-y-0.5">
                <Label htmlFor="notification-enabled">Enable incident alerts</Label>
                <p className="text-xs text-muted-foreground">
                  Send an email when an incident opens or resolves.
                </p>
              </div>
              <Switch
                id="notification-enabled"
                checked={form.enabled}
                onCheckedChange={(checked) => update("enabled", checked)}
                disabled={saving}
              />
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="notification-from-name">Sender name</Label>
                <Input
                  id="notification-from-name"
                  value={form.fromName}
                  onChange={(event) => update("fromName", event.target.value)}
                  placeholder="Uptime Monitor"
                  disabled={saving}
                  maxLength={120}
                />
                <FieldError message={fieldErrors.from_name} />
              </div>

              <div className="space-y-2">
                <Label htmlFor="notification-from-address">From address</Label>
                <Input
                  id="notification-from-address"
                  type="email"
                  value={form.fromAddress}
                  onChange={(event) => update("fromAddress", event.target.value)}
                  placeholder="alerts@example.com"
                  disabled={saving}
                  autoComplete="off"
                />
                <FieldError message={fieldErrors.from_address} />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="notification-recipients">Recipients</Label>
              <textarea
                id="notification-recipients"
                value={form.recipients}
                onChange={(event) => update("recipients", event.target.value)}
                placeholder={"ops@example.com\noncall@example.com"}
                disabled={saving}
                rows={3}
                className="flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
              />
              <p className="text-xs text-muted-foreground">
                Separate addresses with a comma or a new line.
              </p>
              <FieldError message={fieldErrors.recipients} />
            </div>

            <NotificationProviderFields
              fields={form}
              settings={current}
              fieldErrors={fieldErrors}
              disabled={saving}
              onChange={updateProviderField}
              onProviderChange={(provider) => update("provider", provider)}
              onEncryptionChange={changeEncryption}
            />

            <div className="flex flex-col gap-4 border-t pt-6 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm text-muted-foreground">{testHint}</p>
              <div className="flex flex-col gap-2 sm:flex-row">
                <Button type="submit" disabled={saving}>
                  {saving ? (
                    <>
                      <Loader2 className="animate-spin" aria-hidden="true" />
                      Saving…
                    </>
                  ) : (
                    "Save changes"
                  )}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={sendTest}
                  disabled={testDisabled}
                >
                  {testing ? (
                    <Loader2 className="animate-spin" aria-hidden="true" />
                  ) : (
                    <Send aria-hidden="true" />
                  )}
                  Send test email
                </Button>
              </div>
            </div>
          </form>

          <p className="text-xs text-muted-foreground">
            Saved provider secrets are encrypted at rest and never displayed. Rotating{" "}
            <code>JWT_SECRET</code> requires re-entering the saved secret.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
