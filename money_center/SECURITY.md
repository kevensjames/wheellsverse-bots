# Money Center Security

## Authentication

The Money Center dashboard now requires authentication for all state-changing operations (add, edit, start, stop, remove assets).

### Setup

1. Generate a secure authentication token:
   ```bash
   export MONEY_CENTER_AUTH_TOKEN=$(openssl rand -hex 32)
   ```

2. Optionally set a custom secret key for session management:
   ```bash
   export MONEY_CENTER_SECRET_KEY=$(openssl rand -hex 32)
   ```

3. Start the dashboard:
   ```bash
   python money_center/dashboard.py
   ```

### Protected Routes

The following routes require authentication when `MONEY_CENTER_AUTH_TOKEN` is set:
- `/add` - Add new assets
- `/edit/<asset_id>` - Edit existing assets
- `/start/<asset_id>` - Start asset processes
- `/stop/<asset_id>` - Stop asset processes
- `/remove/<asset_id>` - Delete assets

Read-only routes (index, asset detail, reports, logs) remain accessible without authentication.

### Backward Compatibility

If `MONEY_CENTER_AUTH_TOKEN` is not set, the dashboard will display a warning but allow access without authentication. This is for local development only. **Always set an authentication token in production environments.**

## Command Injection Prevention

### Shell Metacharacter Validation

The registry now validates `run_command` and `stop_command` fields to prevent shell injection attacks. Commands containing dangerous shell metacharacters are rejected:
- `;` - Command separator
- `|` - Pipe
- `&` - Background execution
- `$` - Variable expansion
- `` ` `` - Command substitution
- `$(` - Command substitution
- `||` - OR operator
- `&&` - AND operator
- `>`, `<`, `>>` - Redirection

### Safe Command Execution

Commands are now executed using `subprocess.Popen()` and `subprocess.run()` **without** `shell=True`. This prevents shell interpretation and command injection:

**Before (vulnerable):**
```python
subprocess.Popen(cmd, shell=True, ...)  # Allows: "python script.py; rm -rf /"
```

**After (secure):**
```python
cmd_args = shlex.split(cmd)
subprocess.Popen(cmd_args, ...)  # Executes only: ["python", "script.py"]
```

### Command Format

Commands should be specified as simple command-line invocations:
- ✅ `python /path/to/script.py --arg value`
- ✅ `node /path/to/app.js`
- ✅ `pkill -f "process_name"`
- ❌ `python script.py && echo done`
- ❌ `python script.py | tee log.txt`
- ❌ `python script.py > /dev/null 2>&1`

If you need complex shell operations, create a wrapper script and execute that instead.

## Network Binding

### Default Binding

The dashboard now binds to `127.0.0.1` (localhost) by default instead of `0.0.0.0` (all interfaces). This prevents network access from other machines.

**Before:**
```bash
python dashboard.py  # Accessible from network
```

**After:**
```bash
python dashboard.py  # Only accessible from localhost
```

### Network Access

To allow network access (not recommended without proper firewall rules):
```bash
python dashboard.py --host 0.0.0.0
```

A warning will be displayed when binding to non-localhost addresses.

## Security Best Practices

1. **Always set `MONEY_CENTER_AUTH_TOKEN`** in production environments
2. **Use strong, randomly-generated tokens** (at least 32 bytes of entropy)
3. **Keep the dashboard on localhost** unless you have proper network security
4. **Use a reverse proxy** (nginx, Apache) with HTTPS if network access is required
5. **Regularly rotate authentication tokens**
6. **Monitor the logs** in `money_center/logs/money_center.log` for suspicious activity
7. **Validate all commands** before adding them to assets
8. **Use absolute paths** for executables when possible
9. **Avoid shell metacharacters** in commands
10. **Create wrapper scripts** for complex command sequences

## Threat Model

### Mitigated Threats

✅ **Unauthenticated access** - Authentication required for state-changing operations  
✅ **Command injection** - Shell metacharacters blocked, commands parsed safely  
✅ **Network exposure** - Default binding to localhost only  
✅ **Shell expansion attacks** - Commands executed without shell interpretation  

### Remaining Considerations

⚠️ **Authorized user command execution** - Authenticated users can still execute arbitrary commands they define. This is by design, as the dashboard is intended for trusted operators.  
⚠️ **Session management** - Sessions are stored in Flask's default session mechanism. For high-security environments, consider using a more robust session backend.  
⚠️ **HTTPS** - The dashboard runs over HTTP by default. Use a reverse proxy with HTTPS for production deployments.  

## Incident Response

If you suspect unauthorized access:

1. **Immediately change** `MONEY_CENTER_AUTH_TOKEN`
2. **Review logs** in `money_center/logs/money_center.log`
3. **Check assets.json** for unauthorized modifications
4. **Inspect running processes** for suspicious activity
5. **Review assets.backup.json** to restore if needed
6. **Restart the dashboard** with new credentials

## Reporting Security Issues

If you discover a security vulnerability, please report it responsibly:
- Do not create public GitHub issues for security vulnerabilities
- Contact the maintainers directly
- Provide detailed reproduction steps
- Allow time for a fix before public disclosure
