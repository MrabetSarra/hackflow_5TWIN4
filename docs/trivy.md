# Trivy repository scans

Trivy runs in a disposable Docker container and scans the repository for
vulnerabilities, misconfiguration, and secrets. The scan excludes Git history,
private uploads/credentials, and user media.

From the repository root, run:

```powershell
docker compose -f docker-compose.security.yml --profile security run --rm trivy fs --scanners vuln,misconfig,secret --skip-dirs .git --skip-dirs private_media --skip-dirs media .
```

To make high and critical findings fail the command, add
`--exit-code 1 --severity HIGH,CRITICAL`. The first scan downloads Trivy's
vulnerability database and requires internet access.
