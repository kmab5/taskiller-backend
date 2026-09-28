# Backend Development Rounds

The backend is planned as **eight implementation rounds**. A round is a coherent, reviewable milestone, not a calendar-time estimate. Each round ends with migrations, tests, API-contract updates and a runnable repository state.

1. **Foundation — complete** — FastAPI scaffold, configuration, PostgreSQL/Alembic, health endpoints, Docker, CI, OpenAPI export and repository quality tooling.
2. **Identity & authentication — complete** — users, Argon2id credentials, JWT access tokens, rotating/revocable refresh sessions, verification/reset token primitives, profile/preferences, authorization dependencies and auth contract tests.
3. **Work model** — WorkTypes, Project/Sprint/Chore CRUD, hierarchy invariants, ordering, states, tree/next-action queries, ETags/versioning and ownership rules.
4. **Focus & recommendation engine** — work characteristics, deterministic evidence-informed rules, recommendation snapshots, Focus Plan/segment CRUD and customization.
5. **Execution engine** — Sessions, append-only Events, one-open-session invariant, pause/resume/advance/complete/abandon, idempotency, cross-device conflicts and session reviews.
6. **Analytics & personalization** — duration derivation, estimate calibration, user/task/project summaries, time series, project rollups and historical signals fed back into recommendations.
7. **Privacy & operations** — data exports, deletion lifecycle, PostgreSQL outbox/worker, retention, rate limits, operational/security logging and recovery behavior.
8. **Hardening & production release** — complete OpenAPI/problem catalog, authorization matrix, load/security tests, migrations audit, Koyeb/Neon production configuration, observability and end-to-end verification.

After Round 8, the backend is intended to be **v1 feature-complete independently of `taskiller-web`**. Future integrations such as social OAuth, notifications, calendar sync or Redis can be added without changing the core API architecture.
