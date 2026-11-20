export type NotificationProvider = "smtp" | "brevo" | "mailgun" | "mailtrap";
export type EditableNotificationProvider = "smtp" | "brevo" | "mailgun" | "mailtrap";
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
  mailgun_api_url: string | null;
  mailgun_api_key_set: boolean;
  mailtrap_api_token_set: boolean;
  provider_credentials_set: boolean;
  unreadable_secrets: NotificationProvider[];
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
  mailgun_api_key?: string;
  mailgun_domain?: string | null;
  mailgun_api_url?: string | null;
  mailtrap_api_token?: string;
}
