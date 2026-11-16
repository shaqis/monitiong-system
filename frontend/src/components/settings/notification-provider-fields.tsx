"use client";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  EditableNotificationProvider,
  NotificationSettings,
} from "@/types";

export type EncryptionMode = "starttls" | "ssl" | "none";

export interface ProviderFields {
  provider: EditableNotificationProvider;
  smtpHost: string;
  smtpPort: string;
  encryption: EncryptionMode;
  smtpUsername: string;
  smtpPassword: string;
  brevoApiKey: string;
}

interface NotificationProviderFieldsProps {
  fields: ProviderFields;
  settings: NotificationSettings;
  fieldErrors: Record<string, string>;
  disabled: boolean;
  onChange: <K extends keyof ProviderFields>(key: K, value: ProviderFields[K]) => void;
  onProviderChange: (provider: EditableNotificationProvider) => void;
  onEncryptionChange: (mode: EncryptionMode) => void;
}

function FieldError({ message }: { message: string | undefined }) {
  if (!message) {
    return null;
  }
  return <p className="text-xs text-red-600">{message}</p>;
}

export function NotificationProviderFields({
  fields,
  settings,
  fieldErrors,
  disabled,
  onChange,
  onProviderChange,
  onEncryptionChange,
}: NotificationProviderFieldsProps) {
  const envManagedProvider =
    settings.source === "environment" &&
    (settings.provider === "mailgun" || settings.provider === "mailtrap");

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="notification-provider">Provider</Label>
        <Select
          value={fields.provider}
          onValueChange={(value) =>
            onProviderChange(value === "brevo" ? "brevo" : "smtp")
          }
          disabled={disabled}
        >
          <SelectTrigger id="notification-provider">
            <SelectValue placeholder="Select a provider" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="smtp">SMTP server</SelectItem>
            <SelectItem value="brevo">Brevo</SelectItem>
          </SelectContent>
        </Select>
        <FieldError message={fieldErrors.provider} />
      </div>

      {envManagedProvider ? (
        <Alert variant="info">
          <div>
            <AlertTitle>Managed by the environment</AlertTitle>
            <AlertDescription>
              Email currently uses {settings.provider === "mailgun" ? "Mailgun" : "Mailtrap"},
              which is configured through the backend environment. Saving SMTP or Brevo details
              here overrides it.
            </AlertDescription>
          </div>
        </Alert>
      ) : null}

      {fields.provider === "smtp" ? (
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="notification-smtp-host">SMTP host</Label>
              <Input
                id="notification-smtp-host"
                value={fields.smtpHost}
                onChange={(event) => onChange("smtpHost", event.target.value)}
                placeholder="smtp.example.com"
                disabled={disabled}
                autoComplete="off"
              />
              <FieldError message={fieldErrors.smtp_host} />
            </div>

            <div className="space-y-2">
              <Label htmlFor="notification-smtp-port">Port</Label>
              <Input
                id="notification-smtp-port"
                type="number"
                min={1}
                max={65535}
                value={fields.smtpPort}
                onChange={(event) => onChange("smtpPort", event.target.value)}
                placeholder="587"
                disabled={disabled}
              />
              <FieldError message={fieldErrors.smtp_port} />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="notification-smtp-encryption">Encryption</Label>
            <Select
              value={fields.encryption}
              onValueChange={(value) =>
                onEncryptionChange(
                  value === "ssl" ? "ssl" : value === "none" ? "none" : "starttls",
                )
              }
              disabled={disabled}
            >
              <SelectTrigger id="notification-smtp-encryption">
                <SelectValue placeholder="Select encryption" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="starttls">STARTTLS (usually port 587)</SelectItem>
                <SelectItem value="ssl">Implicit TLS (usually port 465)</SelectItem>
                <SelectItem value="none">None</SelectItem>
              </SelectContent>
            </Select>
            <FieldError message={fieldErrors.smtp_starttls ?? fieldErrors.smtp_ssl} />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="notification-smtp-username">Username (optional)</Label>
              <Input
                id="notification-smtp-username"
                value={fields.smtpUsername}
                onChange={(event) => onChange("smtpUsername", event.target.value)}
                placeholder="smtp-user"
                disabled={disabled}
                autoComplete="off"
              />
              <FieldError message={fieldErrors.smtp_username} />
            </div>

            <div className="space-y-2">
              <Label htmlFor="notification-smtp-password">Password</Label>
              <Input
                id="notification-smtp-password"
                type="password"
                value={fields.smtpPassword}
                onChange={(event) => onChange("smtpPassword", event.target.value)}
                placeholder={settings.smtp_password_set ? "unchanged" : "Enter password"}
                disabled={disabled}
                autoComplete="new-password"
              />
              <p className="text-xs text-muted-foreground">
                {settings.smtp_password_set
                  ? "Leave blank to keep the saved password."
                  : "Stored encrypted; required when a username is set."}
              </p>
              <FieldError message={fieldErrors.smtp_password} />
            </div>
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          <Label htmlFor="notification-brevo-key">Brevo API key</Label>
          <Input
            id="notification-brevo-key"
            type="password"
            value={fields.brevoApiKey}
            onChange={(event) => onChange("brevoApiKey", event.target.value)}
            placeholder={settings.brevo_api_key_set ? "unchanged" : "xkeysib-…"}
            disabled={disabled}
            autoComplete="new-password"
          />
          <p className="text-xs text-muted-foreground">
            Find the key in Brevo under SMTP &amp; API → API keys.
            {settings.brevo_api_key_set ? " Leave blank to keep the saved key." : ""}
          </p>
          <FieldError message={fieldErrors.brevo_api_key} />
        </div>
      )}
    </div>
  );
}
