# SECURITY RULES

> These are standing rules for working on KAI/NarAI. Security is more important
> than speed. The KAI Security Center (Phase 1) operationalizes several of them
> (scanning, backups, honest scoring); the rest are enforced by existing
> subsystems or are operator discipline. The "How KAI enforces this" notes map
> each rule to where it actually lives in the codebase.

## How KAI enforces these rules (map)

| Rule area | Where it lives in KAI today |
|---|---|
| Secrets never in code/logs | `tools/wvkey` AES-256-GCM vault (217 keys); Security Center **Secret Scanner** (gitleaks + trufflehog) flags any plaintext; findings stored as redacted fingerprints |
| AI-agent least privilege | `services/governance` — `@audited(scope, destructive)`, `is_scope_enabled` (`KAI_SCOPE_*`), approval gates (`PendingApproval`), kill-switches |
| Human approval for risky actions | `@audited(..., destructive=True)` requires `approved=True`; browser-control double kill-switch; RCE/self-install hard-blocked by the safety classifier |
| Audit trail | append-only `data/governance/audit.jsonl` (`record_action`), redacted inputs/outputs |
| Dependency / vuln scanning | Security Center **Vulnerability Scanner** (trivy) |
| Backups | Security Center **Backup Monitoring** (restic → Backblaze B2) |
| Monitoring / alerts | `services/supreme` empire scanner; Security Center pushes Telegram on critical/verified findings |
| Auth | `dependencies/admin.require_admin_token` (`X-Admin-Token`) today; **MFA + RBAC are Phase 2** (the score reflects this honestly — Authentication starts low) |

---

## Core Principle

Security is more important than speed.

Never expose:
- API keys
- Passwords
- Tokens
- Secrets
- Environment variables
- Database credentials

## Authentication

Always:
- Use strong passwords
- Enable MFA/2FA
- Rotate credentials regularly
- Use OAuth where possible

Never:
- Hardcode secrets into code
- Commit secrets to GitHub

## Database Security

Always:
- Encrypt sensitive data
- Use least privilege access
- Validate all inputs
- Backup databases daily

## API Security

Always:
- Validate requests
- Rate limit endpoints
- Use HTTPS only
- Log suspicious activity

## Server Security

Always:
- Keep software updated
- Use firewalls
- Disable unused ports
- Run services with minimum permissions

## Code Security

Always:
- Sanitize user input
- Validate uploads
- Scan dependencies
- Review code before deployment

Never:
- Execute untrusted code
- Trust user input
- Disable security checks

## Monitoring

Always:
- Log security events
- Monitor CPU, RAM, disk
- Alert on suspicious behavior
- Maintain audit trails

## Backups

Always:
- Daily backups
- Encrypted backups
- Multiple backup locations
- Test recovery procedures

## AI Agent Security

Never allow agents to:
- Access secrets unnecessarily
- Delete critical files
- Execute dangerous commands
- Modify production systems without approval

Require human approval for:
- Financial actions
- System configuration changes
- Production deployments
- Access control changes

---

## Security-Architect Review Prompt

Before making any code change, run this checklist (the standing review lens for
KAI work):

1. Check for security risks.
2. Check authentication requirements.
3. Check authorization requirements.
4. Check secrets exposure.
5. Check logging and auditing.
6. Check data validation.
7. Check rate limiting.
8. Check encryption.
9. Check dependency vulnerabilities.
10. Refuse unsafe implementations.

Security has priority over speed and convenience. Never expose secrets. Never
disable authentication. Never bypass security controls. Always explain risks
before implementation.
