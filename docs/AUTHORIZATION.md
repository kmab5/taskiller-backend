# Authorization Matrix

`release_check.py` treats the following operations as intentionally public. Every other `/api/v1` operation must retain OpenAPI `bearerAuth` or CI fails.

| Public operation | Reason |
|---|---|
| `register` | establish an account |
| `login` | establish a session |
| `refreshAccessToken` | refresh cookie is the credential |
| `confirmEmailVerification` | one-time token is the credential |
| `requestPasswordReset` | account-recovery entry point |
| `confirmPasswordReset` | one-time token is the credential |
| `downloadDataExport` | short-lived HMAC signed URL token |

Health endpoints are outside `/api/v1` and intentionally public.

## Authenticated resources

All user resources apply `CurrentAuth`, which validates both the JWT and its server-side AuthSession. Service methods then scope reads/mutations to `auth.user.id`. Cross-user IDs therefore behave as not-found/invalid references instead of granting access.

| Domain | Ownership boundary | Mutation concurrency |
|---|---|---|
| User/profile/preferences | current user | ETag / `If-Match` |
| Auth sessions | current user | server-side revocation |
| Work Types | system presets + current user's custom types | ETag for mutable custom type |
| Work Items | current user | ETag + idempotency where retry-sensitive |
| Focus recommendations/plans | current user | immutable recommendation; ETag plans |
| Execution Sessions/Events | current user | Session ETag + idempotent Events |
| Analytics | current user's historical snapshots | read only |
| Exports/deletion | current user or signed export URL | idempotency/ETag/rate limit |

CI also asserts that no new v1 operation becomes public accidentally.
