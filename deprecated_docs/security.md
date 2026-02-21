##  Security

## 🔐 Security
| Component                                                  | Description                                                                                      |
|------------------------------------------------------------|--------------------------------------------------------------------------------------------------|
| [**API Keys**](/deprecated_docs/api_keys.md)                          | Learn how users authenticate using scoped, revocable API keys. Includes creation, revocation, and prefix validation. |
| [**Policy & Philosophy**](/deprecated_docs/handling_function_calls.md) | Understand our security-first approach to function calling, tool execution, and system invocation. |
| [**Provider API Keys**](/deprecated_docs/provider_api_key_flow.md)    | Details how to securely inject third-party provider keys (like OpenAI or Azure) into assistant flows. |
| [**Bootstrap Secrets**](/deprecated_docs/bootstrap_security.md)       | Every deployment generates unique database credentials, signing salts, and tool IDs by default. No two builds share secrets. |
| [**Tool Identifiers**](/deprecated_docs/tool_identifier_system.md)    | Each tool (e.g., code interpreter) receives a globally unique identifier. Used in structured output and event tracing. |
| [**Deterministic Secrets**](/deprecated_docs/secrets_override.md)     | For reproducible builds in CI/CD or multi-tenant environments, secrets may be injected via environment overrides. |


 