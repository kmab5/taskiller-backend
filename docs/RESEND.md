# Resend authentication email

Taskiller can deliver email verification and password-reset messages through the Resend HTTPS API. This is the recommended mode on Render Free because it does not depend on SMTP ports.

Required production variables:

```text
TASKILLER_EMAIL_DELIVERY_MODE=resend
TASKILLER_WEB_APP_URL=https://taskiller-web.vercel.app
TASKILLER_RESEND_API_KEY=<Resend API key>
TASKILLER_RESEND_FROM_EMAIL=Taskiller <noreply@your-verified-domain.com>
```

Never commit the API key. Configure it as a secret environment variable in Render. Verify the sending domain in Resend and add the DNS records Resend provides before using that domain in `TASKILLER_RESEND_FROM_EMAIL`.
