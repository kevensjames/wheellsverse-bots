# Security Patch Summary

## Overview
This patch addresses a critical security vulnerability (CVE-level) that allowed unauthenticated arbitrary OS command execution through the Money Center dashboard.

## Vulnerability Details
**Title:** Unauthenticated Money Center dashboard endpoints allow arbitrary OS command execution

**Attack Vector:**
1. Attacker accesses unauthenticated `/add` or `/edit` endpoints
2. Submits malicious `run_command` (e.g., `python script.py; rm -rf /`)
3. Command is stored in `assets.json` without validation
4. Attacker calls `/start/<asset_id>` to execute the malicious command
5. Server executes arbitrary commands via `subprocess.Popen(..., shell=True)`

## Changes Made

### 1. Authentication Layer (dashboard.py)
- **Added:** Token-based authentication via `MONEY_CENTER_AUTH_TOKEN` environment variable
- **Added:** Session management using Flask sessions with secure secret key
- **Added:** `@require_auth` decorator for all state-changing routes:
  - `/add` - Add new assets
  - `/edit/<asset_id>` - Edit existing assets
  - `/start/<asset_id>` - Start asset processes
  - `/stop/<asset_id>` - Stop asset processes
  - `/remove/<asset_id>` - Delete assets
- **Backward compatibility:** If no token is set, displays warning but allows access (dev mode only)

### 2. Command Injection Prevention (dashboard.py, cli.py)
- **Removed:** `shell=True` from all `subprocess.Popen()` and `subprocess.run()` calls
- **Added:** Safe command parsing using `shlex.split()` to properly handle quoted arguments
- **Added:** Command syntax validation with error handling
- **Result:** Commands are executed as argument arrays, preventing shell interpretation

**Before (vulnerable):**
```python
subprocess.Popen(cmd, shell=True, ...)  # Allows: "python script.py; rm -rf /"
```

**After (secure):**
```python
cmd_args = shlex.split(cmd)
subprocess.Popen(cmd_args, ...)  # Executes only: ["python", "script.py"]
```

### 3. Input Validation (registry.py)
- **Added:** `_validate_command()` function to check for dangerous shell metacharacters
- **Added:** Validation for both `run_command` and `stop_command` fields
- **Blocked characters:** `;`, `|`, `&`, `$`, `` ` ``, `$(`, `||`, `&&`, `>`, `<`, `>>`
- **Added:** `shlex.split()` syntax validation
- **Result:** Malicious commands are rejected before being stored

### 4. Network Binding (dashboard.py)
- **Changed:** Default host from `0.0.0.0` (all interfaces) to `127.0.0.1` (localhost only)
- **Added:** Warning message when binding to non-localhost addresses
- **Result:** Dashboard is not exposed to network by default

### 5. Security Warnings (dashboard.py)
- **Added:** Startup warning if `MONEY_CENTER_AUTH_TOKEN` is not set
- **Added:** Instructions for generating secure tokens
- **Added:** Warning when binding to network-accessible addresses

## Files Modified
1. `money_center/dashboard.py` - Authentication, command execution, network binding
2. `money_center/registry.py` - Command validation
3. `money_center/cli.py` - Command execution (CLI interface)
4. `money_center/SECURITY.md` - Security documentation (new file)
5. `money_center/PATCH_SUMMARY.md` - This file (new file)

## Testing Recommendations

### 1. Test Authentication
```bash
# Without token (should show warning)
python money_center/dashboard.py

# With token (should require auth)
export MONEY_CENTER_AUTH_TOKEN=$(openssl rand -hex 32)
python money_center/dashboard.py
```

### 2. Test Command Validation
Try adding assets with these commands (should be rejected):
- `python script.py; rm -rf /`
- `python script.py | tee log.txt`
- `python script.py && echo done`
- `python script.py > /dev/null`

Valid commands (should work):
- `python /path/to/script.py --arg value`
- `node /path/to/app.js`
- `pkill -f "process_name"`

### 3. Test Command Execution
Verify that commands without shell metacharacters execute correctly:
```bash
python money_center/cli.py add
# Enter a simple command like: python -c "print('test')"
python money_center/cli.py start <asset_id>
```

### 4. Test Network Binding
```bash
# Should bind to localhost only
python money_center/dashboard.py
# Check: netstat -an | grep 7777

# Should show warning
python money_center/dashboard.py --host 0.0.0.0
```

## Deployment Instructions

### 1. Set Authentication Token
```bash
# Generate a secure token
export MONEY_CENTER_AUTH_TOKEN=$(openssl rand -hex 32)

# Optionally set custom secret key
export MONEY_CENTER_SECRET_KEY=$(openssl rand -hex 32)

# Add to your environment or .env file
echo "MONEY_CENTER_AUTH_TOKEN=$MONEY_CENTER_AUTH_TOKEN" >> .env
```

### 2. Update Existing Assets
Review existing assets in `assets.json` for commands with shell metacharacters:
```bash
grep -E '[;|&$`]' money_center/assets.json
```

If found, update commands to remove shell metacharacters or create wrapper scripts.

### 3. Restart Services
```bash
# Stop any running dashboard instances
pkill -f "dashboard.py"

# Start with new security settings
python money_center/dashboard.py
```

### 4. Verify Security
- Confirm authentication is required for state-changing operations
- Confirm dashboard is bound to localhost only (unless explicitly configured otherwise)
- Test that commands with shell metacharacters are rejected
- Review logs for any suspicious activity

## Security Considerations

### What This Patch Fixes
✅ Unauthenticated access to state-changing endpoints  
✅ Command injection via shell metacharacters  
✅ Arbitrary command execution via `shell=True`  
✅ Network exposure by default  

### What This Patch Does NOT Fix
⚠️ **Authorized user command execution** - Authenticated users can still execute commands they define. This is by design for trusted operators.  
⚠️ **HTTPS encryption** - Dashboard runs over HTTP. Use a reverse proxy for production.  
⚠️ **Rate limiting** - No rate limiting on authentication attempts.  
⚠️ **Session security** - Uses Flask's default session mechanism. Consider Redis for production.  

### Additional Hardening Recommendations
1. Use a reverse proxy (nginx, Apache) with HTTPS
2. Implement rate limiting on authentication endpoints
3. Use a more robust session backend (Redis, database)
4. Enable audit logging for all operations
5. Implement IP whitelisting if network access is required
6. Use a secrets management system for tokens (Vault, AWS Secrets Manager)
7. Regularly rotate authentication tokens
8. Monitor logs for suspicious activity

## Rollback Instructions

If issues arise, you can rollback by:
1. Reverting the changes to the three modified files
2. Restarting the dashboard

However, this will re-introduce the security vulnerability. Instead, consider:
- Temporarily disabling authentication by not setting `MONEY_CENTER_AUTH_TOKEN`
- Investigating and fixing any compatibility issues
- Updating commands in assets to remove shell metacharacters

## References
- OWASP Command Injection: https://owasp.org/www-community/attacks/Command_Injection
- CWE-78: OS Command Injection: https://cwe.mitre.org/data/definitions/78.html
- Python subprocess security: https://docs.python.org/3/library/subprocess.html#security-considerations
