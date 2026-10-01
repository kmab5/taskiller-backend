# Mailjet Authentication Email

Taskiller supports Mailjet's HTTPS Send API v3.1 for verification and password-reset emails.

## Mailjet account setup

1. Open Mailjet.
2. Go to **Account Settings → Senders & Domains**.
3. Add a sender address that you control.
4. Open the activation email Mailjet sends to that address and confirm it.
5. Verify that the sender is shown as **Active**.
6. Go to **Account Settings → API Keys / API Key Management**.
7. Copy the public API key.
8. Generate/copy the secret key and store it securely.

The Mailjet secret is sensitive and must never be committed to Git.

## Render variables

```text
TASKILLER_EMAIL_DELIVERY_MODE=mailjet
TASKILLER_WEB_APP_URL=https://taskiller-web.vercel.app
TASKILLER_MAILJET_API_KEY=<public API key>
TASKILLER_MAILJET_SECRET_KEY=<secret/private key>
TASKILLER_MAILJET_FROM_EMAIL=<the exact active sender address>
TASKILLER_MAILJET_FROM_NAME=Taskiller
```

Optional defaults:

```text
TASKILLER_MAILJET_API_URL=https://api.mailjet.com/v3.1/send
TASKILLER_MAILJET_TIMEOUT_SECONDS=10
```

## Delivery

The backend authenticates to Mailjet using HTTP Basic Auth:

- username = Mailjet API key
- password = Mailjet secret key

The request is sent over HTTPS to:

```text
POST https://api.mailjet.com/v3.1/send
```

No SMTP port is used.

## Gmail sender limitation

A Gmail address can be activated as an individual sender address in Mailjet. Because you do not control `gmail.com`, you cannot add Mailjet SPF/DKIM records to Gmail's DNS. Delivery may therefore show Mailjet attribution or have lower deliverability than a future custom-domain sender.

## Smoke test

After deployment:

1. Log into Taskiller.
2. Open Settings → Profile.
3. Request email verification.
4. Confirm the message arrives.
5. Click its verification link.
6. Sign out and test **Forgot password**.
7. Confirm the reset message arrives and opens the password-reset page.

If delivery fails, inspect Render logs. Taskiller converts provider failures into the stable API problem:

```text
email_delivery_unavailable
```
