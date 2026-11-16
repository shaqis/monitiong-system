export type NotificationProvider = "smtp" | "brevo" | "mailgun" | "mailtrap";
export type EditableNotificationProvider = "smtp" | "brevo";
export type NotificationSettingsSource = "database" | "environment";

export interface NotificationSettings {
  enabled: boolean;
  provider: NotificationProvider;
  configured: boolean;
  source: NotificationSettingsSource;
  from_address: string | null;
  from_name: string;
  recipients: string[];
  timeout_seconds: number;
  smtp_host: string | null;
  smtp_port: number;
  smtp_starttls: boolean;
  smtp_ssl: boolean;
  smtp_username: string | null;
  smtp_password_set: boolean;
  brevo_api_key_set: boolean;
  mailgun_domain: string | null;
  provider_credentials_set: boolean;
}

export interface NotificationSettingsUpdate {
  enabled?: boolean;
  provider?: EditableNotificationProvider;
  from_address?: string;
  from_name?: string;
  recipients?: string[];
  timeout_seconds?: number;
  smtp_host?: string | null;
  smtp_port?: number;
  smtp_starttls?: boolean;
  smtp_ssl?: boolean;
  smtp_username?: string | null;
  smtp_password?: string;
  brevo_api_key?: string;
}
