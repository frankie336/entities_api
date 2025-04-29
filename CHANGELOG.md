# [1.11.0](https://github.com/frankie336/entities_api/compare/v1.10.0...v1.11.0) (2025-04-29)


### Bug Fixes

* restore attach_tool_to_assistant method ([4d6eb2e](https://github.com/frankie336/entities_api/commit/4d6eb2e7e94570425f9c20a3ef742f504f252d55))


### Features

* Add canonical_id reserved ID's to base_tools ([17b7214](https://github.com/frankie336/entities_api/commit/17b7214f7ff7a7f992dfac0a51a70be883b094df))

# [1.10.0](https://github.com/frankie336/entities_api/compare/v1.9.0...v1.10.0) (2025-04-28)


### Features

* multi-stage requirements  hashing wiht improved function call handling. Introducing the platform_tools param in the assistants data structure. Introducing hybrid hashed and non hashed requirements file for problematic packages. ([8ae4b19](https://github.com/frankie336/entities_api/commit/8ae4b192ba2b56e8899850fa0ac71647c170e808))
* multi-stage requirements  hashing wiht improved function call handling. Introducing the platform_tools param in the assistants data structure. Introducing hybrid hashed and non hashed requirements file for problematic packages. ([a2f517a](https://github.com/frankie336/entities_api/commit/a2f517ab3e1df81ea7058e0b0c86be327479ddbe))
* multi-stage requirements  hashing wiht improved function call handling. Introducing the platform_tools param in the assistants data structure. Introducing hybrid hashed and non hashed requirements file for problematic packages. ([79e4c65](https://github.com/frankie336/entities_api/commit/79e4c65a9a6c6088631b262765d973776164f398))
* multi-stage requirements  hashing wiht improved function call handling. Introducing the platform_tools param in the assistants data structure. Introducing hybrid hashed and non hashed requirements file for problematic packages. ([267dbb9](https://github.com/frankie336/entities_api/commit/267dbb9aa382b6607ac44e5ba585ca0dce98d6b2))
* multi-stage requirements  hashing wiht improved function call handling. Introducing the platform_tools param in the assistants data structure. Introducing hybrid hashed and non hashed requirements file for problematic packages. ([76efb7d](https://github.com/frankie336/entities_api/commit/76efb7db6a16c1e73fca8c296c85da17bc83a4d9))

# [1.9.0](https://github.com/frankie336/entities_api/compare/v1.8.0...v1.9.0) (2025-04-23)


### Features

* function-call-tags ([6e67d57](https://github.com/frankie336/entities_api/commit/6e67d57808d16b8960ec1cd29499549215d26044))
* Improved function call handling. Working towards full call structure filtering. ([4c4c67f](https://github.com/frankie336/entities_api/commit/4c4c67f4fefd18776ad49892a30d7e27f36ca255))

# [1.8.0](https://github.com/frankie336/entities_api/compare/v1.7.1...v1.8.0) (2025-04-23)


### Features

* Asynchronous-REDIS ([8fc3de9](https://github.com/frankie336/entities_api/commit/8fc3de941163e36ad682448f9d7c4d6aae492788))

## [1.7.1](https://github.com/frankie336/entities_api/compare/v1.7.0...v1.7.1) (2025-04-19)


### Bug Fixes

* generate_dev_docker_compose ([570bda1](https://github.com/frankie336/entities_api/commit/570bda1ce25b66bb08b025899a23da953f4b7870))

# [1.7.0](https://github.com/frankie336/entities_api/compare/v1.6.0...v1.7.0) (2025-04-19)


### Features

* shunt-streams-to-redis-phase-1 ([1cab6f5](https://github.com/frankie336/entities_api/commit/1cab6f5596e7643b31f867729ae4a450c317f5f7))
Shunting streams to Redis 
We are in the process of shunting streaming content to the Redis server. This lays the ground  for state of the art utility performance enhancement, error recovery, edge device integration, and agentic features 


# [1.6.0](https://github.com/frankie336/entities_api/compare/v1.5.0...v1.6.0) (2025-04-19)


### Features

* basic_vector_embeddings_search ([7ce4fab](https://github.com/frankie336/entities_api/commit/7ce4fab60f7c0d5870f5c8f0cbb18fe8020299ea))
* move context-window-to-redis-primary ([475f19b](https://github.com/frankie336/entities_api/commit/475f19b13f63e3ce3340e26aee52469f88be1ad1))

We have moved the primary message history and system message to a redis server. 
We use a data driven method of building the context window for each assistant. On each turn the latest messages from the assistant and user are appended onto the dialogue. This includes tool responses. The context window can quickly grows in a multi turn conversation. Fetching this from the database adds more and more latency as the size of the thread  grows. 
Implementing Redis
 We moved the primary message history,  tool definitions, and system message to a Redis server. At the same time, a redis server is now introduced into the docker container estate; the first in a series of changes that will leverage powerful features of Redis for a true scalable, enterprise AI inference platform. 
No Database change 
There is no database change, so you can retain existing data in Dev and not have to make any Alembic update s
Whilst the solution has been tested, please let us know if you experience any abnormalities; these will be rapidly fixed.


# [1.5.0](https://github.com/frankie336/entities_api/compare/v1.4.0...v1.5.0) (2025-04-18)


### Features

* basic_vector_embeddings_search ([e5def53](https://github.com/frankie336/entities_api/commit/e5def53adbe148f6d0feb843f3458659a8542c91))

# [1.4.0](https://github.com/frankie336/entities_api/compare/v1.3.2...v1.4.0) (2025-04-17)


### Features

* Integrate DeepSeek API. ([e6c1dae](https://github.com/frankie336/entities_api/commit/e6c1daeb2201ae63d4e07daf67dc923b00e69a2a))

## [1.3.2](https://github.com/frankie336/entities_api/compare/v1.3.1...v1.3.2) (2025-04-17)


### Bug Fixes

* upgrade pd client. ([ae0569b](https://github.com/frankie336/entities_api/commit/ae0569bece4174112225fa5ed2181160f2f5961f))

## [1.3.1](https://github.com/frankie336/entities_api/compare/v1.3.0...v1.3.1) (2025-04-17)


### Bug Fixes

* TogetherAIHandler routing issues. ([be6c386](https://github.com/frankie336/entities_api/commit/be6c38684f81ddd5759c1adad7e636f873d08dbc))

# [1.3.0](https://github.com/frankie336/entities_api/compare/v1.2.1...v1.3.0) (2025-04-17)


### Bug Fixes

* Normalize your route keys to lowercase in SUBMODEL_CLASS_MAP ([a8d1f51](https://github.com/frankie336/entities_api/commit/a8d1f51719e3c9f79527145ead9329562db6e9ce))


### Features

* Add support for new models ([4523191](https://github.com/frankie336/entities_api/commit/45231911a3f24f0af7989197c6e4fb0bd017551b))

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

# [1.2.0](https://github.com/frankie336/entities_api/compare/v1.1.0...v1.2.0) (2025-04-15)

## [1.2.1](https://github.com/frankie336/entities_api/compare/v1.2.0...v1.2.1) (2025-04-16)


### Bug Fixes

* Moved admin .env ([3c2834e](https://github.com/frankie336/entities_api/commit/3c2834eb90256349c22c24ea9146c750013f1c36))


### ✨ Added
- Introduced `scripts/generate_docker_compose.py` and `scripts/generate_docker_compose_dev.py`:
  - Automatically generate `docker-compose.yml` and `.env` files if they do not exist.
  - Inject unique, secure values for `MYSQL_ROOT_PASSWORD`, `MYSQL_PASSWORD`, and `DEFAULT_SECRET_KEY`.
  - Generate and map a `unique_secret` for custom Docker network binding.

- Added fallback `.example` templates:
  - `docker-compose.dev.example.yml` – now tracked in source control.
  - Redacts all secrets and replaces them with `REPLACE_ME` tokens for dev visibility and safety.

### 🔧 Changed
- `start.py` (DockerManager):
  - Aligned `.env` generation to source values directly from `docker-compose.yml` (or fallback defaults).
  - Dynamically constructs `DATABASE_URL` and `SPECIAL_DB_URL` using parsed credentials.
  - Added logic to detect `docker-compose.yml` presence and skip regeneration if already defined.
  - Ensured platform-aware path handling for mounted volumes (`SHARED_PATH` detection).
  - Added validation for `docker-compose.dev.yml` parsing via PyYAML.

### 🧪 Improved
- Hardened Docker secret management:
  - Secrets are never committed to source control.
  - All auto-generated credentials use `uuid.uuid4().hex` or `secrets.token_urlsafe(...)` for high entropy.
  - `.dockerignore` and `.gitignore` now explicitly exclude sensitive runtime files.



### Bug Fixes

* env generate_docker_compose.py ([9ddde9f](https://github.com/frankie336/entities_api/commit/9ddde9f170f1f3624585baf3fdab29e61dd1023d))


### Features

* dynamic-unique-env-secrets ([13b556f](https://github.com/frankie336/entities_api/commit/13b556fdbca04bfdf65de44263345f45dafd0bea))

# [1.1.0](https://github.com/frankie336/entities_api/compare/v1.0.0...v1.1.0) (2025-04-15)


### Features

* New CI flow18! ([ff06107](https://github.com/frankie336/entities_api/commit/ff061078e69d5fb75f3abf739ed1ba8eaccb3888))
* New CI flow19! ([05e2bd3](https://github.com/frankie336/entities_api/commit/05e2bd36a3c125276e15d0de35e2402ba0f18e39))

# 1.0.0 (2025-04-14)


### Bug Fixes

* ASSISTANTS_BASE_URL eroneus back slash / ([6e70fd9](https://github.com/frankie336/entities_api/commit/6e70fd9d841de89c5da2055b35ac6405321493d5))
* **download:** allow inline rendering of image MIME types via conditional Content-Disposition ([d833909](https://github.com/frankie336/entities_api/commit/d833909e7bcb66508a9a8884148fe476c9a8549c))
* **download:** allow inline rendering of image MIME types via conditional Content-Disposition ([7b45b3b](https://github.com/frankie336/entities_api/commit/7b45b3ba08d035b9b9da58b31432354a0598d02f))
* remove comments from .env generation ([7894e1e](https://github.com/frankie336/entities_api/commit/7894e1e361f6c931cca178cb3bbd5e5b79ae37b3))
* users route. ([de6683b](https://github.com/frankie336/entities_api/commit/de6683bacb7cf3a4a26d20a447e8fffd4a99859d))


### Features

* add routes.md ([a2a52fa](https://github.com/frankie336/entities_api/commit/a2a52faa8fc9eb553e0b95ca64a902fb85d471a0))
* add routes.md ([f5ae598](https://github.com/frankie336/entities_api/commit/f5ae598417739109e5d9b57e7ee4668265dc0110))
* add routes.md ([eb03440](https://github.com/frankie336/entities_api/commit/eb03440140137163058cc2b1f79e2a15da0336a4))
* Add support for deepseek-ai/DeepSeek-V3-0324 ([87ac173](https://github.com/frankie336/entities_api/commit/87ac173ac2b332ddef9bf8c1db6633e380a15fd6))
* Add support for deepseek-ai/DeepSeek-V3-0324 ([350503f](https://github.com/frankie336/entities_api/commit/350503f4c6692fb9b0dab5c7305dde3ada6883c5))
* bootstrap default assistant_set_up_service.py. ([6cea7bb](https://github.com/frankie336/entities_api/commit/6cea7bbe82f2c1e3f3c6c92c6fbce455573b766b))
* bootstrap default assistant_set_up_service.py. ([10518ff](https://github.com/frankie336/entities_api/commit/10518ff6bd3b7c9a08546353ac1b22869b8edbcb))
* enhance code interpreter output with smart file rendering ([6f50b50](https://github.com/frankie336/entities_api/commit/6f50b50a384298ddcc57c8957d9f26f4af16c455))
* Implement API key protected routes ([197aec4](https://github.com/frankie336/entities_api/commit/197aec4771e3097817c10200b8a32bbc98ffd0c1))
* Implement new provider routing. ([45c16fa](https://github.com/frankie336/entities_api/commit/45c16faed545d86d5cb9ca68e87127f201102c80))
* Implement new provider routing. ([3624b52](https://github.com/frankie336/entities_api/commit/3624b52d537cd322d9081ce58bcd77b30a78e100))
* Integrate new models: ([32b954f](https://github.com/frankie336/entities_api/commit/32b954fbc8f456b6c78db2630df7ccab9c0d315f))
* multi-stage-containers. ([092f1f7](https://github.com/frankie336/entities_api/commit/092f1f7b3f23767a5733f507d7713161b60c895e))
* multi-stage-containers. ([a4dc666](https://github.com/frankie336/entities_api/commit/a4dc6663244dcc99f4bd893d62ee25958431b34c))
* New CI flow! ([486d875](https://github.com/frankie336/entities_api/commit/486d87574180c50a9c42ce4e4158a2e23ab8d6a2))
* New CI flow! ([1428ce7](https://github.com/frankie336/entities_api/commit/1428ce743efdc73bc35eca75994da766341cebae))
* New CI flow10! ([57d2f3e](https://github.com/frankie336/entities_api/commit/57d2f3e29d86a01210b625a3e2f5f5f7aa12acca))
* New CI flow11! ([49e408a](https://github.com/frankie336/entities_api/commit/49e408ab9074150520250176b9411d8015bcf537))
* New CI flow13! ([59ea8df](https://github.com/frankie336/entities_api/commit/59ea8df6ffc1e0bcfdd52e4b1481a722b81955cb))
* New CI flow14! ([1e7a303](https://github.com/frankie336/entities_api/commit/1e7a30345c651e34e4cd178d153d43c7cbec71f6))
* New CI flow15! ([293e133](https://github.com/frankie336/entities_api/commit/293e1332da53d7ec745f090d849b7b182ffe29ef))
* New CI flow16! ([f2b49fd](https://github.com/frankie336/entities_api/commit/f2b49fd267ecab89bc239d04cd948269d692123b))
* New CI flow17! ([f31b927](https://github.com/frankie336/entities_api/commit/f31b927e80590b491932a74acd6506a3b42a7286))
* New CI flow2! ([a6db2c1](https://github.com/frankie336/entities_api/commit/a6db2c117c6d41a4808701d42d444a80e41f17c7))
* New CI flow3! ([6bb1357](https://github.com/frankie336/entities_api/commit/6bb13570a1f24f1a15e4905dcfbfdf80706423a6))
* New CI flow4! ([5d229be](https://github.com/frankie336/entities_api/commit/5d229bedbe92f534cd703ded228f00c60b059c45))
* New CI flow5! ([fb95024](https://github.com/frankie336/entities_api/commit/fb950244852f33e40c5f01b165b4645d89e3a0f0))
* New CI flow6! ([05f8d0d](https://github.com/frankie336/entities_api/commit/05f8d0d0360eb28ab339a60b8c7a164ed7ce580a))
* New CI flow7! ([4e704b4](https://github.com/frankie336/entities_api/commit/4e704b42cf321ff1c402a668bded7e86e69c1a7a))
* New CI flow8! ([1633e76](https://github.com/frankie336/entities_api/commit/1633e76d71e49412b00e505f134e31ac6295a806))
* New CI flow9! ([8cdc5f9](https://github.com/frankie336/entities_api/commit/8cdc5f9044ce9d94d11b28ae53043c928cd6e0d1))

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---
