## [1.20.2](https://github.com/frankie336/entities_api/compare/v1.20.1...v1.20.2) (2026-01-23)


### Bug Fixes

* change method list_thread_messages to get_formatted_messages ([67d142f](https://github.com/frankie336/entities_api/commit/67d142f8deb0efdd3d05d4da0654cad2406f7666))
* delete async_client.py. ([9c1ca9f](https://github.com/frankie336/entities_api/commit/9c1ca9f0c1ab6cfa5d31ba296f569aa7e014b946))
* delete old /inference dir. ([baa5c2e](https://github.com/frankie336/entities_api/commit/baa5c2e755fab988e075b8edb6551601fb3db100))
* filter  "<|channel|>analysis" ([a5dd32a](https://github.com/frankie336/entities_api/commit/a5dd32a57fd3a879b1774ce62ea170ac54f1d0c7))
* Implement cache invalidation for assistants cached_assistant ([7f4d3c5](https://github.com/frankie336/entities_api/commit/7f4d3c52d80b00844a8f07a12c9d7901b190ff2e))
* implement new architecture for hot_code. Complex parsing and replay from each worker is needless when hot_code can be replayed direct from the handler. ([e49ea75](https://github.com/frankie336/entities_api/commit/e49ea75e0987b05052a2b286b0339a28726708ea))
* Improve speed and smoothness of streaming. ([0e16437](https://github.com/frankie336/entities_api/commit/0e164378fdc5722ee19f75319a3b32d47c27ee30))
* Improve speed and smoothness of streaming. ([b3e9191](https://github.com/frankie336/entities_api/commit/b3e919132480bea23337161e93dca7484c94ee77))
* Major speed improvements in inference. ([dc06f29](https://github.com/frankie336/entities_api/commit/dc06f294b0ae9d68bc5733053db26eec660152c1))
* Move AsyncHyperbolicClient to client factory. ([9ba074c](https://github.com/frankie336/entities_api/commit/9ba074c33925aeed4a5b713c11166f599bdfe16a))
* Resolve forward stream delay issue ([09deac8](https://github.com/frankie336/entities_api/commit/09deac88058cb4d7e0b4e819d5a9029f29604195))
* Resolve gpt-oss-120b reasoning tokens not generating issue. ([a78e11c](https://github.com/frankie336/entities_api/commit/a78e11c325394f5fb3ff7ae1e67c4377d691aa4e))
* Resolve gpt-oss-120b reasoning tokens not generating issue. ([90bc1c4](https://github.com/frankie336/entities_api/commit/90bc1c4f6463cf8bb37ceb6b466bd26506b86277))
* Resolve hyperbolic/meta-llama- models function calling issues. Previously, the model did not respond to the first turn. This was due to passing in the tool call array in the request payload. ([3e19625](https://github.com/frankie336/entities_api/commit/3e196257f5aa230682cb9ef915b45f13a5adf591))

## [1.20.1](https://github.com/frankie336/entities_api/compare/v1.20.0...v1.20.1) (2026-01-21)


### Bug Fixes

* filter  "<|channel|>analysis" ([ed24d0b](https://github.com/frankie336/entities_api/commit/ed24d0b207f9bc303f3f94b8fb78b7865e65ed92))
* Improve speed and smoothness of streaming. ([cc0d000](https://github.com/frankie336/entities_api/commit/cc0d000a609ca411a02dd80162a7d770006bdd4a))
* Improve speed and smoothness of streaming. ([e4ad4ff](https://github.com/frankie336/entities_api/commit/e4ad4ff80a7421c0d3f9088ad968eec451e88801))
* Major speed improvements in inference. ([d284045](https://github.com/frankie336/entities_api/commit/d284045550e94606658f363ab7a15d01eebadce5))
* Move AsyncHyperbolicClient to client factory. ([dde4690](https://github.com/frankie336/entities_api/commit/dde4690654481268e0879115467010dd7396496d))
* Resolve forward stream delay issue ([ab25252](https://github.com/frankie336/entities_api/commit/ab25252783dfffeb58f7b977e45b23c8ced09ef0))
* Resolve gpt-oss-120b reasoning tokens not generating issue. ([b755611](https://github.com/frankie336/entities_api/commit/b7556113fb127bb183eaf1331605d3712c0ceece))
* Resolve gpt-oss-120b reasoning tokens not generating issue. ([dc7050d](https://github.com/frankie336/entities_api/commit/dc7050d9efeb8709393b6f40d724fb9845059846))

# [1.20.0](https://github.com/frankie336/entities_api/compare/v1.19.0...v1.20.0) (2026-01-21)


### Bug Fixes

* Add tool name to tool output metadata ([981e5ac](https://github.com/frankie336/entities_api/commit/981e5ace76001044ee591f4f6852000049ab6334))
* broken google worker import ([7d83f90](https://github.com/frankie336/entities_api/commit/7d83f90ae02f5a9e2a1897d5e392937396d75fbb))
* Default False = Use Redis Cache (Efficient). ([c5631c0](https://github.com/frankie336/entities_api/commit/c5631c0b0537ba0c5f1ff0dc402b49714378fec6))
* gpt-oss function call 2nd turn issue ([524b693](https://github.com/frankie336/entities_api/commit/524b6938d594c297ce87d8f5901d04b56b621b83))
* Implement native tool call response for gpt-oss Hermes class models. ([6846044](https://github.com/frankie336/entities_api/commit/684604440b5f6692b47f610cf411d88adf41f324))
* Implement native tool call response for llama. ([610b4ed](https://github.com/frankie336/entities_api/commit/610b4edaf336c8cd99198a8e393e6cbfca7f3fc0))
* implement native tool calling on Quen Model calls. ([6347d12](https://github.com/frankie336/entities_api/commit/6347d12ebcf912c9348ee142f76f4af43dc2d823))
* implement process_hot_code_buffer in CodeExecutionMixin. ([e7d5db7](https://github.com/frankie336/entities_api/commit/e7d5db769e0bd5531efadb02c7123c654b438004))
* Implement structured tool call detection for gpt-oss ([4c6934d](https://github.com/frankie336/entities_api/commit/4c6934d78e88f95846ed811d6821f198dba29d3c))
* issue with hyperbolic/DeepSeek data flow ([4b7a0e5](https://github.com/frankie336/entities_api/commit/4b7a0e54859e15cf95fa1544952780ac7a189839))
* issue with oss reasoning chunks ([9c4e88f](https://github.com/frankie336/entities_api/commit/9c4e88f02946f9ca65477dcbad1a358f2d211ea3))
* issue with oss reasoning chunks ([d228581](https://github.com/frankie336/entities_api/commit/d228581cc001e152bd81ba71949a404cac5ccd47))
* JsonUtilsMixin update. ([c73cd3f](https://github.com/frankie336/entities_api/commit/c73cd3f1bd8eae46f7c8bd3c43f3d227a599066d))
* Reinstated partial code_interpreter instructions to _build_native_tools_system_message ([694a3fa](https://github.com/frankie336/entities_api/commit/694a3fa6343901f80b94afeb433deafc5bd1d722))
* Remove duplicate api arg from worker signature. ([e5f1356](https://github.com/frankie336/entities_api/commit/e5f1356662e78002edadcb314a6c71ab224da458))
* Restore gpt-oss hot code interleave. ([9d00699](https://github.com/frankie336/entities_api/commit/9d00699a21e140c47ee0c88a746b4ff512fdf206))
* tool role tool_call_id bug ([502788e](https://github.com/frankie336/entities_api/commit/502788e7d17b4e74ac3f2aa35d654ec9a4f412fa))


### Features

* 9314d4058f78_add_agentic_state_columns_to_assistant_.py adds some level 3 agentic components to the master DB ([1c8d684](https://github.com/frankie336/entities_api/commit/1c8d684f4f930b272418a76047e70145c04a970f))
* cut over to projectdavid==1.39.0: bringing new models online: ([5a9ed31](https://github.com/frankie336/entities_api/commit/5a9ed3183a5244e40826a422ba67b117a9e53c6e))

# [1.19.0](https://github.com/frankie336/entities_api/compare/v1.18.1...v1.19.0) (2026-01-16)


### Features

* move tool-call suppression logic to inference handler ([8e56c5b](https://github.com/frankie336/entities_api/commit/8e56c5b47870803a5d1ca7fb073b6aacdcbf6898))
* move tool-call suppression logic to inference handler ([4152548](https://github.com/frankie336/entities_api/commit/415254882786c6de79280805378a86093789c418))
* upgrade projectdavid SDK to projectdavid==1.37.0 ([a3305b1](https://github.com/frankie336/entities_api/commit/a3305b103186385678bb1db0cdc5ad36784c331b))

## [1.18.1](https://github.com/frankie336/entities_api/compare/v1.18.0...v1.18.1) (2025-07-06)


### Bug Fixes

* update_assistant association issues. ([d57bf31](https://github.com/frankie336/entities_api/commit/d57bf3142245c47fb3969d7b92c42f37c43077d6))

# [1.18.0](https://github.com/frankie336/entities_api/compare/v1.17.0...v1.18.0) (2025-06-17)


### Features

* Release. ([cf082d0](https://github.com/frankie336/entities_api/commit/cf082d09aaee97ef7bd56384e06142ebf1af96f3))

# [1.17.0](https://github.com/frankie336/entities_api/compare/v1.16.0...v1.17.0) (2025-06-16)


### Features

* Structured Error Payloads. ([383c2b0](https://github.com/frankie336/entities_api/commit/383c2b0715a0a47c42fcfdd090329555277203c7))

# [1.16.0](https://github.com/frankie336/entities_api/compare/v1.15.1...v1.16.0) (2025-06-16)


### Bug Fixes

* --Integrate mixins architecture. This major upgrade splits the original base class into a series of smaller mixin classes for better maintainability and less cognitive load. ([80e54ca](https://github.com/frankie336/entities_api/commit/80e54caacecbb7276009639f40fa05deca2fb38f))


### Features

* --Integrate mixins architecture. This major upgrade splits the original base class into a series of smaller mixin classes for better maintainability and less cognitive load. ([d02411b](https://github.com/frankie336/entities_api/commit/d02411b0d2aa0c322bdd4a655c713b146bb0b1ac))
* Restore function call processing in the hyperbolicDs1 class. Function calls json objects can now be suppressed. Improve Mixin Architecture. ([c9a5b1b](https://github.com/frankie336/entities_api/commit/c9a5b1b40301db6e051608788b0e0fec88c85f35))

## [1.15.1](https://github.com/frankie336/entities_api/compare/v1.15.0...v1.15.1) (2025-05-25)


### Bug Fixes

* cache export completely disabled ([dab9b81](https://github.com/frankie336/entities_api/commit/dab9b81212ca4fcc18cd27e87acd1e5c99fbe268))

# [1.15.0](https://github.com/frankie336/entities_api/compare/v1.14.0...v1.15.0) (2025-05-25)


### Bug Fixes

* --Integrate mixins architecture. This major upgrade splits the original base class into a series of smaller mixin classes for better maintainability and less cognitive load. ([ac5d439](https://github.com/frankie336/entities_api/commit/ac5d439ce5c8595232dc32f5e1ae8b081d6ab7fa))


### Features

* --Integrate mixins architecture. This major upgrade splits the original base class into a series of smaller mixin classes for better maintainability and less cognitive load. ([cdab8fc](https://github.com/frankie336/entities_api/commit/cdab8fcead838fe61e357c0dc549d819be10799c))

# [1.14.0](https://github.com/frankie336/entities_api/compare/v1.13.0...v1.14.0) (2025-05-25)


### Features

There  are some major changes and enhancements to vector store creation and life cycle management (RAG).
 Creating a vector store
No longer requires you manually pass the user id into the creaction method 

```python
vs = client.vectors.create_vector_store(
    name="movielens-complete-demo",
    user_id=USER_ID,
)
```

Becomes:

```python
vs = client.vectors.create_vector_store(
    name="movielens-complete-demo",
    
)
```

**Search Methods**

Several new search method have been added:
vector_file_search_raw
Search hits are returned in a raw format with similarity scoring. There is no further post processing, formatting or ranking. This is most appropriate where you need to apply custom or third party ranking and or post processing.  

**Example:**

````python
hits = client.vectors.vector_file_search_raw(
    vector_store_id="vect_GsSezuKiXy11rFssDcRFAg",
    query_text=query,
    top_k=top_k,
    vector_store_host=host_override,
)
````

**Simple_vector_file_search**

Search hits are returned wrapped in an envelope that provides anotation and citations per hit. This is most appropriate for bodies of text where you might need the assistant to provide authorities and citations; a legal document for example. 

**Example**

```python
hits = client.vectors.simple_vector_file_search(
    vector_store_id=STORE_ID,
    query_text=query,
    top_k=top_k,
)
```

**attended_file_search**

Search results are synthesized by an integrated agent; results are passed to the Large Language model. The output comes with AI insights and organization. Additionally, result rankings are enhanced by a second pass through a ranking model. Suited for cumilitative research (deep research) and multi agent   tasks.   

**Example:**

```
hits = client.vectors.attended_file_search(
    vector_store_id=STORE_ID,
    query_text=query,
    top_k=top_k,
)
```

**unattended_file_search**

Search hits are returned wrapped in an envelope that provides anotation and citations per hit. Additionally, result rankings are enhanced by a second pass through a ranking model

**Example:**

```python
 hits = client.vectors.unattended_file_search(
    vector_store_id=STORE_ID,
    query_text=query,
    top_k=top_k,
)
```


* --Integrate mixins architecture. This major upgrade splits the original base class into a series of smaller mixin classes for better maintainability and less cognitive load. ([88216e0](https://github.com/frankie336/entities_api/commit/88216e04f5de357cc35910c32bf9420813f8affa))
* --Integrate mixins architecture. This major upgrade splits the original base class into a series of smaller mixin classes for better maintainability and less cognitive load. ([bf29576](https://github.com/frankie336/entities_api/commit/bf29576c936d85fe88d98f8b01cd2c649f344140))

# [1.13.0](https://github.com/frankie336/entities_api/compare/v1.12.0...v1.13.0) (2025-05-11)


### Features

* allow an admin to choose the owner ([c3e57dd](https://github.com/frankie336/entities_api/commit/c3e57ddef780da23c2169b1ca0d16fc1bbe11db2))

# [1.12.0](https://github.com/frankie336/entities_api/compare/v1.11.1...v1.12.0) (2025-04-30)


### Features

* add tools_resources ([3b399fd](https://github.com/frankie336/entities_api/commit/3b399fd528e8296470e2acd12dc6e00b47171fe6))

## [1.11.1](https://github.com/frankie336/entities_api/compare/v1.11.0...v1.11.1) (2025-04-29)


### Bug Fixes

* restore attach_tool_to_assistant method ([ba87d17](https://github.com/frankie336/entities_api/commit/ba87d172dd3dda2d5ba9e38e09f2a57ca9585eaa))

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
