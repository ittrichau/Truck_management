# GitHub Actions auto-deploy to VPS

Every push to `main` deploys the new revision to the VPS through GitHub Actions.

## VPS one-time setup

Run these commands as `root` on the VPS. Replace the public-key placeholder with the deploy public key generated locally.

```bash
adduser --disabled-password --gecos '' deploy
usermod -aG docker deploy
mkdir -p /opt/truck-management
chown -R deploy:deploy /opt/truck-management
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
install -m 600 -o deploy -g deploy /dev/null /home/deploy/.ssh/authorized_keys
```

Append the GitHub Actions deploy **public key** to `/home/deploy/.ssh/authorized_keys`, then verify key-only access:

```bash
ssh -i ~/.ssh/truck-management-actions deploy@YOUR_VPS_IP
```

The server-local `.env`, `instance/`, and `logs/` directories are not changed by the deploy script. Keep them out of Git.

## GitHub repository setup

In **Settings → Environments → production**, optionally require approval before production deploys. Then add these repository/environment secrets:

| Secret | Value |
| --- | --- |
| `VPS_HOST` | VPS IP or hostname, e.g. `180.93.117.107` |
| `VPS_USER` | `deploy` |
| `VPS_PORT` | `22` |
| `VPS_SSH_KEY` | Full private key content for the dedicated GitHub Actions deploy key |

Never store the VPS password, `.env`, database, or TLS private keys in GitHub Secrets for this workflow.

## Deployment behavior

The workflow calls `deploy/deploy-vps.sh`, which:

1. Fetches `origin/main` and checks out that exact revision.
2. Keeps `.env`, SQLite database, uploads, and logs on the server.
3. Builds/restarts the Docker Compose service; the existing entrypoint applies migrations.
4. Waits for `http://127.0.0.1:5000/health`.
5. Fails the workflow and prints container logs if health validation does not pass.

Use GitHub's **Actions** tab to inspect each deployment.
