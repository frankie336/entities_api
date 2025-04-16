# Entities V1

[![License: PolyForm Noncommercial](https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-blue.svg)](https://polyformproject.org/licenses/noncommercial/1.0.0/)
[![Docker Pulls](https://img.shields.io/docker/pulls/thanosprime/entities-api-api?label=API%20Pulls&logo=docker&style=flat-square)](https://hub.docker.com/r/thanosprime/entities-api-api)
[![Docker Image Version](https://img.shields.io/docker/v/thanosprime/entities-api-api?sort=semver&label=API%20Version&style=flat-square)](https://hub.docker.com/r/thanosprime/entities-api-api/tags)
[![CI](https://github.com/frankie336/entities_api/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/frankie336/entities_api/actions/workflows/ci.yml)

![Entities Emblem](https://raw.githubusercontent.com/frankie336/entities_api/master/assets/entities_emblem_green.png)

The **Entities API** is for developing projects that interact with LLMs.  
It aggregates inference calls to multiple providers as well as local using the [Ollama](https://github.com/ollama) library.

This enables rapid and flexible deployment of advanced features such as conversation management,  
[function calling](/docs/function_calling.md), [code interpretation](/docs/code_interpretation.md), and more through easy-to-use API endpoints.

---

![Network Diagram](assets/docker_containers.png)

---

## 🔍 Entities vs. LangChain (and Friends)

| Feature                          | **Entities**                                    | LangChain / Others                     |
|----------------------------------|-------------------------------------------------|----------------------------------------|
| **Design Philosophy**            | Systems-level, composable, and user-controlled  | Framework-heavy, opinionated, abstract |
| **Interface Style**              | Explicit class-based SDK + REST API             | Chained declarative syntax             |
| **Vector Store Logic**           | Custom embeddings + Qdrant via HTTPx            | Plug-and-play vector wrappers          |
| **Tool Use & AI Calls**          | Native function calling + structured streaming  | Wrapper-based toolchains               |
| **Security Model**               | Firejail sandbox, subprocess isolation          | None / minimal                         |
| **Licensing Philosophy**         | Open-use, revenue-share model                   | Varies (often restrictive)             |
| **Docker Architecture**          | DevOps-ready, containerized, bootstrap-aware    | Rarely production-oriented             |
| **Local LLM Support**            | Ollama integration (opt-in)                     | Often cloud-dependent                  |
| **Buzzword Compliant**           | ❌ No agents, chains, or gimmicks               | ✅ All the latest acronyms             |

---

## 💡 Why Entities?

> Entities is a **developer-native**, **security-conscious**, and **deeply composable AI framework** built for:
>
> - People who want to **own their stack**
> - Teams building **real-world intelligent assistants**
> - Engineers who prefer **systems control over chained magic**
> - Architects working **inside secure, disconnected, or trust-minimized environments**

You don’t “add a tool to a chain.”  
You **register tools, trigger runs, stream thoughts, and command vector memory.**

> Whether you're building in the open or operating behind the firewall —  
> **Entities is engineered for autonomy, auditability, and absolute control.**

A quiet revolution for those who’ve dreamed of an **OpenAI-class Assistants platform**,  
but **on their own terms**, **at near-zero cost**, and deployable against **any LLM model** — cloud or local.

This is **AI orchestration for the rest of us.**

---

## ⚙️ Bootstrap Setup

For a full admin setup and assistant provisioning guide, see:

👉 [`docs/bootstrap.md`](https://github.com/frankie336/entities/blob/master/docs/bootstrap.md)

This includes:
- Admin user creation
- Initial API key generation
- Regular user creation
- Default assistant setup

These scripts can be run directly in development (e.g., `python scripts/bootstrap_admin.py`)  
or invoked inside containers using the orchestration tools.

---

## 🐳 Docker Lifecycle Commands

Entities provides a unified orchestration script for building, running, and tearing down your container environment.

👉 [`docs/docker_commands.md`](https://github.com/frankie336/entities/blob/master/docs/docker_commands.md)

---

## Supported Inference Providers

| Provider                                        | Type                        |
|------------------------------------------------|-----------------------------|
| [Ollama](https://github.com/ollama)             | **Local** (Self-Hosted)     |
| [DeepSeek](https://platform.deepseek.com/)      | **Cloud** (Open-Source)     |
| [Hyperbolic](https://hyperbolic.xyz/)           | **Cloud** (Proprietary)     |
| [OpenAI](https://platform.openai.com/)          | **Cloud** (Proprietary)     |
| [together.ai](https://www.together.ai/)         | **Cloud** (Aggregated)      |
| [MS Azure Foundry](https://azure.microsoft.com) | **Cloud** (Enterprise)      |

---

## 🔐 Security Model

Entities places security at the forefront, employing:

- **Firejail Sandboxing**: Limits system access during code interpretation and local execution.
- **Subprocess Isolation**: Ensures code executions cannot interfere with core API logic, providing robust protection in multi-user environments.

---

## 🧠 State Management

Entities simplifies dialogue management with the [Threads](/docs/threads.md) endpoint.

```json
[
  {"role": "system", "content": "You are a helpful assistant."},
  {"role": "user", "content": "What’s the capital of France?"},
  {"role": "assistant", "content": "The capital of France is Paris."},
  {"role": "user", "content": "What’s the population of Paris?"},
  {"role": "assistant", "content": "Approximately 2.1 million."}
]
```

---

![Workflow](assets/quik_start-work_flow.png)

---

## 📚 Documentation Index

### Core Concepts

- [Assistants](https://github.com/frankie336/projectdavid/blob/master/docs/assistants.md)  
- [Threads](https://github.com/frankie336/projectdavid/blob/master/docs/threads.md)  
- [Messages](https://github.com/frankie336/projectdavid/blob/master/docs/messages.md)  
- [Runs](https://github.com/frankie336/projectdavid/blob/master/docs/runs.md)  
- [Inference](https://github.com/frankie336/projectdavid/blob/master/docs/inference.md)  
- [Streaming](https://github.com/frankie336/projectdavid/blob/master/docs/streams.md)  

### Internals

- [Routes](/docs/routes.md)  
- [Security](/docs/security.md)  
- [Integration Status](/docs/model_integration_status.md)  
- [Files](/docs/files.md)  
- [Vector Store](https://github.com/frankie336/projectdavid/blob/master/docs/vector_store.md)  
- [Database](/docs/database.md)  
- [Tools](/docs/tools.md)  
- [Users](/docs/users.md)

### Advanced Features

- [Function Calling](https://github.com/frankie336/projectdavid/blob/master/docs/function_calling.md)  
- [Code Interpretation](https://github.com/frankie336/projectdavid/blob/master/docs/code_interpretation.md)  

---

## 🧪 Local Dev

To run setup scripts directly during local development:

```bash
# Bootstrap admin user with defaults
python scripts/bootstrap_admin.py

# Create regular user
python scripts/create_user.py --name "Bob" --email "bob@example.com"

# Setup assistant (using admin API key + user ID)
python scripts/bootstrap_default_assistant.py
```

Install the SDK:

```bash
pip install projectdavid
```

Then follow usage docs at:  
👉 [`https://github.com/frankie336/projectdavid`](https://github.com/frankie336/projectdavid)

---

## API Explorer

- [`/altredoc`](http://your-domain/altredoc/)
- [`/mydocs`](http://your-domain/mydocs#/)

---

## 📜 License

Distributed under the [PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0/).  
Commercial licensing available upon request.
