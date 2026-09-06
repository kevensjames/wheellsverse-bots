# mimic_repo — §143 inert fixture set

Benign files that MIMIC suspicious supply-chain patterns so the OS Lab static certification
scanner (`os_lab/certification.py`) can be proven to detect and escalate each one.

Nothing here functions: shell files `exit 0` before the mimic line, hostnames use the RFC 2606
reserved `.invalid` TLD (never resolvable), the credential path is a string that is never opened,
the base64 blob decodes to a plain sentence and is never decoded by any code, and `package.json`'s
hook only echoes. No file is executable, imported, or installed by anything in this repository.

| file | mimics | must escalate step |
|---|---|---|
| install.sh | pipe-to-shell install line | downloaded_binaries (HIGH) |
| keyreader.py | SSH private-key path string | credential_reads (HIGH) |
| persist.sh | crontab @reboot persistence | persistence (HIGH) |
| blob.js | base64-like encoded blob | obfuscation (MEDIUM) |
| telemetry.py | unexpected outbound hostname + telemetry | network_destinations / telemetry (MEDIUM) |
| package.json | postinstall lifecycle hook, no lockfile | install_hooks / package_manifests (MEDIUM) |
