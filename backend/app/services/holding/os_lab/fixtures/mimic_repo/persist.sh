#!/bin/sh
# INERT §143 FIXTURE. The first statement exits; the mimic line below never runs.
exit 0
echo "@reboot /opt/mimic/agent" | crontab -
