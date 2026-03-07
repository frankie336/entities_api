# Project David

[![License: PolyForm Noncommercial](https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-blue.svg)](https://polyformproject.org/licenses/noncommercial/1.0.0/)
[![Docker Pulls](https://img.shields.io/docker/pulls/thanosprime/entities-api-api?label=API%20Pulls&logo=docker&style=flat-square)](https://hub.docker.com/r/thanosprime/entities-api-api)
[![Docker Image Version](https://img.shields.io/docker/v/thanosprime/entities-api-api?sort=semver&label=API%20Version&style=flat-square)](https://hub.docker.com/r/thanosprime/entities-api-api/tags)
[![CI](https://github.com/frankie336/entities_api/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/frankie336/entities_api/actions/workflows/ci.yml)

![Entities Emblem](https://raw.githubusercontent.com/frankie336/entities_api/master/assets/projectdavid_logo.png)

---

An open-source API for sending messages to an LLM and getting responses back, with built-in support for tools, memory, and multi-step agent behaviour — self-hosted, so you own the infrastructure and can plug in any model you want.

## Why Project David?

- **Any model** — connect to any LLM provider or run locally with [Ollama](https://github.com/ollama/ollama)
- **Own your infrastructure** — self-hosted, no vendor lock-in, no data leaving your stack
- **Built-in agent primitives** — tools, memory, and multi-step reasoning out of the box
- **Open-source** — built for engineers who won't trade data sovereignty for convenience

---

## Quick Start

**1. Install the local package.**

```bash
pip install -e .
```

**2. Build the Docker containers.**

```bash
platform-api docker-manager --mode both
```

> 📦 **What gets generated on first run**
>
> Running this command bootstraps two files at the repository root if they don't already exist:
>
> | File | What it contains |
> |---|---|
> | `.env` | Unique, locally-generated secrets — DB passwords, `DEFAULT_SECRET_KEY`, `SEARXNG_SECRET_KEY`, etc. Never committed to version control. |
> | `docker-compose.yml` | A fully-wired Compose file referencing those secrets via `${ENV_VAR}` placeholders. |
>
> Both files are created once and left untouched on subsequent runs, so your local secrets remain stable across restarts.

For the full command reference see:
[Docker orchestration commands](https://github.com/project-david-ai/projectdavid_docs/blob/master/src/pages/api-infra/docker_commands.md)

Verify the CLI is working:

```bash
platform-api --help
```

Expected output:

```
Usage: platform-api [OPTIONS] COMMAND [ARGS]...

 Entities API management CLI.

╭─ Commands ────────────────────────────────────────────────────────────────────╮
│ bootstrap-admin   Bootstrap the initial admin user and API key.               │
│ docker-manager    Manage Docker Compose stack: build, run, set up .env...     │
╰───────────────────────────────────────────────────────────────────────────────╯
```

**3. Provision your admin credentials.**

The command reads `SPECIAL_DB_URL` from your environment. Set it before running:

**Linux / macOS:**
```bash
export SPECIAL_DB_URL=mysql+pymysql://user:password@localhost:3307/entities_db
```

**Windows PowerShell:**
```powershell
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
        [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim())
    }
}
```

Then run:

```bash
platform-api bootstrap-admin
```

This will walk you through the options step by step. To pass all options explicitly:

```bash
platform-api bootstrap-admin \
  --db-url "mysql+pymysql://user:password@localhost:3307/entities_db" \
  --email "admin@example.com" \
  --name "Default Admin"
```

Expected output on first run:

```
================================================================
  ✓  Admin API Key Generated
================================================================
  Email   : admin@example.com
  User ID : user_abc123...
  Prefix  : ad_abc12
----------------------------------------------------------------
  API KEY : ad_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
----------------------------------------------------------------
  This key will NOT be shown again.
  Set it in your environment:
    export ADMIN_API_KEY=ad_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
================================================================
```

> ⚠️ **Store this key immediately.** It is shown exactly once and cannot be recovered.
> If lost, delete the `ApiKey` row from the database and re-run the command.

**4. Provision your first user.**

Install the SDK:

```bash
pip install projectdavid
```

Create a user:

```python
import os
from dotenv import load_dotenv
load_dotenv()
from projectdavid import Entity

client = Entity(api_key=os.getenv("ADMIN_API_KEY"))

new_user = client.users.create_user(
    full_name="Kevin Flynn",
    email="flynn@encom.com",
    is_admin=False,
)

print(new_user)
```

Expected output:

```
id='user_h5YYXC9b200Xv3QYT0Bv12' email='flynn@encom.com' full_name='Kevin Flynn' ...
```

Users require an API key to access the platform endpoints:

```python
create_api_key = client.keys.create_key_for_user(
    target_user_id="the_user_id_here", key_name="The Grid"
)

print(create_api_key.plain_key)
```

Expected output:

```
ea_z_5YV4zGly50UHKlenc9BgTCQXtE....
```

The user can now make API calls using their key:

```python
import os
from dotenv import load_dotenv
load_dotenv()
from projectdavid import Entity

client = Entity(api_key=os.getenv("USER_API_KEY"))
```

> ⚠️ **Do not use the admin key for general API calls.**

---

## Next Steps

- [Inference Quick Start](https://github.com/project-david-ai/projectdavid)
- [Full Python SDK documentation](https://github.com/project-david-ai/projectdavid_docs/tree/master/src/pages/sdk)

---

![Network Diagram](assets/docker_containers.png)

---

## License

Distributed under the [PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0/).
Commercial licensing available upon request.