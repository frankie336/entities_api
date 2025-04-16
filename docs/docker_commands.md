# 🐳 Docker Commands Reference

This document captures all supported Docker orchestration commands used in the `entities` system via `start.py`.

---

## 🏁 General Startup

Use `start.py` to simplify container management:

### Default Orchestration

```bash
python start.py
```

### Skip Orchestration Phase

```bash
python start.py --no-orchestrate
```

### Run with Ollama (Optional Local LLMs)

```bash
python start.py --with-ollama
```

With GPU passthrough:

```bash
python start.py --with-ollama --ollama-gpu
```

---

## 🔧 Docker Lifecycle Commands

| Action                                | Command |
|---------------------------------------|---------|
| **Bring up containers**               | `python start.py --mode up` |
| **Build Docker images**               | `python start.py --mode build` |
| **Build & bring up**                  | `python start.py --mode both` |
| **No-cache build**                    | `python start.py --mode build --no-cache` |
| **No-cache build & up**               | `python start.py --mode both --no-cache` |
| **Clear volumes & restart**           | `python start.py --mode up --clear-volumes` |
| **Stop containers**                   | `python start.py --down` |
| **Stop & clear all data**             | `python start.py --down --clear-volumes` |
| **Debug cache/docker health**         | `python start.py --debug-cache` |

---

## 🔨 Build Specific Services

| Service                | Command |
|------------------------|---------|
| **Main API**           | `python start.py --mode build --services api` |
| **Database (MySQL)**   | `python start.py --mode build --services db` |
| **Vector DB (Qdrant)** | `python start.py --mode build --services qdrant` |
| **Sandbox**            | `python start.py --mode build --services sandbox` |
| **File Server (Samba)**| `python start.py --mode build --services samba` |
