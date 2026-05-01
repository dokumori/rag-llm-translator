# Renovate Bot — Setup & Usage Guide

## What is Renovate?

Renovate is an automated dependency update tool. Once installed, it:

1. **Scans** your repository on a schedule (configured: every Monday before 8 AM CET)
2. **Detects** outdated dependencies (pip packages, Docker images, etc.)
3. **Opens PRs** with the version bump, changelog, and release notes
4. **You review and merge** — that's it

## One-Time Setup (5 minutes)

### Step 1: Install the Renovate GitHub App

1. Go to [github.com/apps/renovate](https://github.com/apps/renovate)
2. Click **Install**
3. Choose your account / organization
4. Select **"Only select repositories"** → pick `drupal-rag-project`
5. Click **Install**

### Step 2: Wait for the Onboarding PR

Within a few minutes, Renovate opens an **onboarding PR** in your repo titled:

> **Configure Renovate**

This PR shows you:
- What dependencies Renovate detected
- What PRs it *would* open based on your config
- A preview of the Dependency Dashboard

**Merge this PR** to activate Renovate.

> [!NOTE]
> Renovate detects that `renovate.json5` already exists in your repo and will use it.
> The onboarding PR may just confirm the config rather than propose a new one.

### Step 3: Done ✅

Renovate is now running. You'll see:
- A **Dependency Dashboard** issue created in your repo (tracks all pending updates)
- Automated PRs appearing on Monday mornings

## Day-to-Day Usage

### Reading a Renovate PR

Each PR includes:
- **What changed**: the package name and version bump
- **Release notes**: extracted from the package's changelog
- **Compatibility notes**: whether it's a major, minor, or patch update

### What to do with PRs

| Situation | Action |
|---|---|
| Minor/patch update, tests pass | Merge it |
| Major update (labeled `breaking`) | Read the changelog, test locally, then merge |
| Update you don't want right now | Close the PR (Renovate won't re-open it until a newer version exists) |

### The Dependency Dashboard

An auto-created GitHub issue titled **"Dependency Dashboard"** that shows:
- ✅ Merged updates
- 🔄 Open PRs
- ⏰ Pending updates (scheduled for next run)
- ❌ Blocked updates (e.g., you closed a PR)

You can also **check a checkbox** on the dashboard to force Renovate to open a PR immediately, without waiting for the schedule.

## What's Being Monitored

| File | Manager | What it tracks |
|---|---|---|
| `services/rag-proxy/requirements.txt` | pip | Python packages (Flask, chromadb, openai, etc.) |
| `services/toolbox/requirements.txt` | pip | Python packages (polib, tqdm, pytest, etc.) |
| `tests/requirements-test.txt` | pip | Test-only packages (snowballstemmer) |
| `services/rag-proxy/Dockerfile` | dockerfile | `python:3.10-slim-bookworm` base image + digest |
| `services/toolbox/Dockerfile` | dockerfile | `python:3.10-slim-bookworm` base image + digest |
| `docker-compose.yml` | docker-compose | `chromadb/chroma:1.4.1` service image |

## How Updates Are Grouped

To keep PR noise low, updates are batched:

- **One PR** for all minor/patch pip updates across all services (keeps versions in sync)
- **Individual PRs** for major pip updates (may have breaking changes)
- **One PR** for Docker base image updates
- **One PR** for Docker Compose image updates

## Configuration

The config lives in [`renovate.json5`](../renovate.json5) at the repo root. It's heavily commented — read it for details on each setting.

### Common Customizations

#### Change the schedule
```json5
"schedule": ["before 8am on monday"],   // weekly
"schedule": ["before 8am every weekday"], // daily
"schedule": ["every 2 weeks on monday"],  // biweekly
```

#### Enable auto-merge for patch updates
```json5
{
  "description": "Auto-merge patch-level pip updates",
  "matchManagers": ["pip_requirements"],
  "matchUpdateTypes": ["patch"],
  "automerge": true
}
```

#### Ignore a specific package
```json5
{
  "matchPackageNames": ["chromadb"],
  "enabled": false
}
```

## Disabling or Removing Renovate

- **Pause temporarily**: Close all Renovate PRs and uncheck items on the Dashboard
- **Remove permanently**: Uninstall the GitHub App from your repo settings → Integrations
