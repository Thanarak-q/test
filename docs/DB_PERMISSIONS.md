# Database permissions

The app connects as its own MySQL user. It must not be able to rewrite history:
audit and log tables are **append-only** for it, so a compromised app process (or a
bug) can add rows but cannot edit or erase the record of what happened.

Migrations run as a separate, more privileged user. The app user never runs DDL.

| table                         | SELECT | INSERT | UPDATE | DELETE | why                                                      |
| ----------------------------- | :----: | :----: | :----: | :----: | -------------------------------------------------------- |
| `identity_users`              |   ✓    |   ✓    |   ✓    |        | row created on first key create; see note on `UPDATE`    |
| `identity_api_keys`           |   ✓    |   ✓    |   ✓    |        | revoke / delete are soft (status change), never `DELETE` |
| `identity_api_key_audit_logs` |   ✓    |   ✓    |        |        | append-only                                              |
| `identity_auth_failure_logs`  |   ✓    |   ✓    |        |        | append-only                                              |
| `llm_models`                  |   ✓    |        |        |        | managed by migrations / an admin user                    |
| `llm_quotas`                  |   ✓    |   ✓    |   ✓    |        | counter re-seed and settle (chat pipeline)               |
| `llm_usage_logs`              |   ✓    |   ✓    |        |        | append-only                                              |

`UPDATE` on `identity_users` is there only because key creation takes the per-user
lock with `INSERT … ON DUPLICATE KEY UPDATE id = id`, which MySQL checks against the
`UPDATE` privilege even though nothing changes.

Retention is enforced by `python -m app.jobs.retention` (run daily from cron) as a
separate user that holds `SELECT, DELETE` on the three log tables only: 60 days for
`llm_usage_logs`, 90 for `identity_api_key_audit_logs` and `identity_auth_failure_logs`
(`app/constants/retention.py`).

```sql
CREATE USER 'matthew_retention'@'%' IDENTIFIED BY '...';
GRANT SELECT, DELETE ON matthew.llm_usage_logs              TO 'matthew_retention'@'%';
GRANT SELECT, DELETE ON matthew.identity_api_key_audit_logs TO 'matthew_retention'@'%';
GRANT SELECT, DELETE ON matthew.identity_auth_failure_logs  TO 'matthew_retention'@'%';
```

```sql
-- as an admin, once per environment; replace the password
CREATE USER 'matthew_app'@'%' IDENTIFIED BY '...';

GRANT SELECT, INSERT, UPDATE ON matthew.identity_users              TO 'matthew_app'@'%';
GRANT SELECT, INSERT, UPDATE ON matthew.identity_api_keys           TO 'matthew_app'@'%';
GRANT SELECT, INSERT         ON matthew.identity_api_key_audit_logs TO 'matthew_app'@'%';
GRANT SELECT, INSERT         ON matthew.identity_auth_failure_logs  TO 'matthew_app'@'%';
GRANT SELECT                 ON matthew.llm_models                  TO 'matthew_app'@'%';
GRANT SELECT, INSERT, UPDATE ON matthew.llm_quotas                  TO 'matthew_app'@'%';
GRANT SELECT, INSERT         ON matthew.llm_usage_logs              TO 'matthew_app'@'%';
```

The compose file's `matthew` user has `ALL` on the database. That is for local
development only and is not what production should run as.

TODO(chat-pipeline): confirm the `llm_*` rows with the pipeline owner.
