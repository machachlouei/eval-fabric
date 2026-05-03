# Security

This document describes the security posture of `eval-fabric`: what threats we model, what defaults we ship, and how to report a vulnerability if you find one.

For architectural context on data handling, see [`docs/architecture.md`](docs/architecture.md#security-and-data-considerations). For the operational counterpart on what is and is not logged, see [`docs/observability.md`](docs/observability.md).

---

## Reporting a vulnerability

**Please do not file a public GitHub issue for security vulnerabilities.**

Email `security@<your-org>.example` with:

- A description of the vulnerability and its potential impact.
- Steps to reproduce, or a proof-of-concept if you have one.
- Affected versions, if known.
- Any suggested remediation.

We commit to:

- An acknowledgement within **2 business days**.
- An initial assessment (severity classification, expected timeline) within **5 business days**.
- A coordinated disclosure window, typically 90 days, before the report becomes public.

If you do not receive a response within the acknowledgement window, please escalate by emailing `security-escalation@<your-org>.example`.

We follow a standard disclosure process and credit reporters in release notes (with permission). We do not currently operate a bounty program, but we are always grateful for thoughtful reports.

---

## Threat model

This is what we believe about the environment the framework runs in and the actors it has to consider.

### What the framework is

`eval-fabric` is a Python library and CLI run inside an organization's compute environment (developer laptop, CI runner, internal cluster). It executes user-provided Python code (evaluators, judges) in the same process as the runner and persists results to a configured backend.

It is **not** a multi-tenant service. There is no built-in authentication, authorization, or tenant isolation. A deployment is expected to be operated by one team per instance, even if results are shared.

### What we are protecting

In rough order of priority:

1. **The integrity of eval results.** A run's `RunResult` must accurately reflect what the evaluator and judges produced. Tampering with stored results undermines every downstream decision (CI gates, deploy approvals, model rollbacks).
2. **The confidentiality of eval data.** Evaluator inputs may include customer data, internal documents, or model outputs that are not intended for public exposure. The framework must not leak them through logs, telemetry, or unrelated channels.
3. **The integrity of the framework itself.** A compromised framework that subtly mis-scores can poison every team's eval pipeline simultaneously.

### What we are not trying to protect

We are explicit about scope. Out-of-scope concerns:

- **Multi-tenant isolation between teams sharing one deployment.** Federate per team if you need this.
- **Sandboxing of plugins.** Evaluators and judges run as trusted code in the same process. A malicious plugin can do anything Python can do. See [Plugin trust](#plugin-trust).
- **Securing the third-party LLM APIs.** If your judge calls OpenAI, you are sending data to OpenAI under their terms. The framework does not redact, transform, or proxy.
- **Network-layer concerns.** TLS, mTLS, certificate pinning — handled by the host application or the infrastructure.

### Threat actors we model

| Actor                              | Capability                                                | What we defend against                                              |
| ---------------------------------- | --------------------------------------------------------- | ------------------------------------------------------------------- |
| **Curious internal user**          | Can read filesystem, environment, process logs            | We do not log secrets or payloads at INFO; we mask in error messages. |
| **Hostile evaluator/judge author** | Can ship a malicious plugin that gets installed           | We surface plugin identity in every span; we do not auto-update plugins. |
| **External attacker via dataset**  | Provides a crafted EvalItem that triggers a parser exploit | Pydantic validation; size limits; no `eval()` of dataset content.   |
| **Compromised model API**          | Returns a malicious payload aiming to exploit downstream  | Judge outputs are validated against typed schemas before persistence. |
| **Compromised trace store**        | Returns tampered records on read                          | Out of scope — this is your data platform's responsibility.         |

### Threats we have decided to accept

These are realistic threats whose mitigation cost we judged not worth the benefit. Operators who care should add controls outside the framework.

- **Plugins running as the framework user.** A malicious plugin can read any file the runner can. Mitigation: a curated allowlist of plugin packages installed in production environments. Not a framework feature.
- **Trace-store contents readable by anyone with backend access.** SQLite has no native ACLs; Postgres uses your existing access model. The framework expects the backend to be appropriately access-controlled.
- **Resource exhaustion via crafted datasets.** A 100M-item dataset will run for a long time and cost real money. We expose `--max-items` for runs, but operators are responsible for budget controls.

---

## Secure defaults

The framework is configured to be safe at install time. You should not have to harden it; you should have to opt out of safety.

### What is on by default

| Default                                                              | Why                                                              |
| -------------------------------------------------------------------- | ---------------------------------------------------------------- |
| Pydantic models reject unknown fields (`extra="forbid"`).            | Catches typos in EvalSpec; prevents schema injection.            |
| Item content is not logged at INFO level.                            | Avoids leaking customer data into log aggregation.               |
| Judge rationales are persisted to the trace store but not to logs.   | Same reason.                                                     |
| YAML loads use `yaml.safe_load`.                                     | No code execution from spec files.                               |
| Plugin import errors are surfaced, not silenced.                     | A failing plugin is visible, not invisible.                      |
| Trace store schema version is checked on open.                       | A mismatched store fails fast, not silently corrupts data.       |
| `on_failure` defaults to `skip`, not `abort`.                        | An eval should not abort on a single bad item by default.        |
| OTel exporter defaults to `none` if not configured.                  | We do not exfiltrate telemetry to surprising places.             |

### Secrets

The framework does not handle secrets. Evaluators and judges read their own credentials from environment variables at runtime. EvalSpec files are committed to source control and **must not contain secrets**.

A plugin that needs an API key reads it via `os.environ["OPENAI_API_KEY"]` (or equivalent). The framework does not pass the environment through any abstraction; the plugin sees the same environment the process sees.

If a plugin author hardcodes a secret in their plugin, that is their bug. The framework cannot help.

### Network egress

The framework itself makes no network calls. All outbound traffic comes from:

- Evaluators (calling the system under test).
- Judges (calling judge models or annotation queues).
- Trace store backends (Postgres, S3).
- The OTel exporter (if configured).

If your environment requires egress allowlisting, allowlist these. The framework will operate in a fully isolated environment provided you supply local-only evaluators and judges and use the SQLite trace store.

---

## Plugin trust

This is the most important security note in the document.

**Plugins are trusted code.** When you `pip install some-plugin-package` and use it via entry points, you are giving its author the ability to run arbitrary code in your runner process. The framework cannot sandbox them.

In practice, this means:

- **Pin plugin versions** in your production environment (`==X.Y.Z`, not `>=X.Y`).
- **Review plugin code** before adoption, especially first-party plugins from teams new to the platform.
- **Limit which plugins are installed** in the production environment. The dev environment can be permissive; production should not.
- **Run the runner with least privilege.** No root, no broad filesystem access, no unnecessary network egress.
- **Audit periodically.** `ef plugins list --health` shows what is installed and whether it loads. Treat the output as a privileged inventory.

This is not a unique posture — it is the same model as `pytest` plugins, `pre-commit` hooks, and any other Python-plugin ecosystem. But it deserves to be stated explicitly because eval results are decision inputs, and a compromised plugin can move money.

---

## Data handling

### Data in motion

- **Within the runner:** in-process, no network.
- **To the trace store:** depends on backend. SQLite is local-only. Postgres uses TLS if configured (`postgres://...?sslmode=require`). Parquet on S3 uses TLS by default for any modern client.
- **To OTel collector:** uses OTLP/HTTPS by default in OTel's configuration; depends on operator setup.

### Data at rest

- **SQLite trace store:** file-system permissions only. The framework does not encrypt SQLite files. Operators who need at-rest encryption should run on an encrypted filesystem or use a different backend.
- **Postgres trace store:** depends on your Postgres configuration (TDE, pg_crypto, etc.). The framework writes raw payloads.
- **Parquet on S3:** uses S3's server-side encryption. Bucket-level encryption is the operator's responsibility to configure.

### Data retention

The framework does not delete data. Trace stores grow without bound by default. Operators are responsible for retention policy:

- **SQLite:** archive old runs by exporting to Parquet, then drop rows.
- **Postgres:** standard retention via partitioning or `VACUUM`.
- **S3 Parquet:** S3 lifecycle rules.

There is no `ef tracestore prune` command. We considered it and decided that destructive operations on result data are too risky to ship as a CLI default. Operators should write their own retention scripts that fit their compliance requirements.

### PII and regulated data

The framework does not classify, redact, or transform data based on its sensitivity. If your evaluator inputs contain PII, PHI, or regulated content:

- The trace store is now a system-of-record for that content. Treat it accordingly (access controls, audit, retention).
- The judge LLM may be a third-party API. Confirm your contract with the provider permits the data class.
- The OTel collector is downstream of the framework. Confirm your collector and storage downstream are appropriate.

The framework will not stop you from sending PII to a third-party judge. That is a policy decision that must be made above the framework.

---

## Supply chain

We take supply chain seriously because plugin authors are downstream of us.

- **Pinned dependencies in `pyproject.toml`.** Direct dependencies are pinned to compatible ranges; `requirements-lock.txt` is generated and committed.
- **`pip-audit` runs in CI** on every PR and nightly. New CVEs in dependencies are surfaced in the next build.
- **Releases are signed.** PyPI releases are uploaded with a sigstore signature. Reproducible builds are tested in CI.
- **No telemetry from the framework itself.** We do not call home, do not phone usage stats, do not check for updates. The framework runs in your environment with no traffic to ours.

---

## Security-relevant configuration

Configuration that has security consequences. Operators should explicitly review these for production deployments.

| Setting                                                | Default     | Production guidance                                            |
| ------------------------------------------------------ | ----------- | -------------------------------------------------------------- |
| `runtime.trace_store`                                  | `sqlite://` | Use Postgres or Parquet with appropriate access controls.      |
| `EVAL_FABRIC_LOG_LEVEL`                                | `INFO`      | Keep at INFO. DEBUG enables verbose internal logs.             |
| OTel exporter for traces                               | `none`      | Set explicitly. `none` is safe but you also see no telemetry.  |
| Plugin discovery                                       | Entry points + explicit | Curate the installed plugin set in production environments.   |
| `runtime.on_failure`                                   | `skip`      | Consider `abort` if even one bad item should halt the eval.    |

---

## Acknowledgements

This framework's security model draws on:

- The OWASP Top 10 for ML.
- NIST SP 800-218 (Secure Software Development Framework).
- Operational lessons from running similar tools at scale.

We are happy to discuss specific assessments, threat-model refinements, or architectural reviews — open an issue or contact the maintainers.