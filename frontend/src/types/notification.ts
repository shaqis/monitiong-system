export type NotificationProvider = "smtp" | "brevo" | "mailgun" | "mailtrap";

export interface NotificationSettings {
  enabled: boolean;
  provider: NotificationProvider;
  configured: boolean;
  from_address: string | null;
  from_name: string;
  recipients: string[];
  timeout_seconds: number;
  smtp_host: string | null;
  smtp_port: number;
  smtp_starttls: boolean;
  smtp_ssl: boolean;
  smtp_username_set: boolean;
  mailgun_domain: string | null;
  provider_credentials_set: boolean;
}
