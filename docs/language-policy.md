# Runtime language policy

Desktop language is the default for employee conversation, live progress, report summaries, approval explanations and notifications. An explicit user request for a communication language overrides this default for its stated scope.

Deliverable language follows the explicit task requirement first, then an explicit asset requirement, then the communication language. The language in which an asset prompt was written is not an output-language requirement. Asset prompts, skill sources, quotations, identifiers, code, schema keys and enum values remain unchanged. Language selection grants no permission and changes no workflow transition.

The shared core policy is `runteams_core.agents.language_policy`. Desktop hosts send the resolved `en` or `zh-CN` preference, including when following the system. The backend stores a device preference; each new conversation turn or pipeline task captures a `language_policy` snapshot with `communication_language`. Pipeline handoffs and retries retain the task snapshot. Changing the desktop preference does not translate history or mutate a running task. Legacy pipeline tasks retain Chinese as the pre-policy default.

The first release adds no asset language controls. Model-facing guidance and system-generated text use the same policy; external platform message bodies and original deliverables are not translated. A model instruction establishes requested behavior, not a guarantee about arbitrary model output.

## Ownership

- Shared policy, desktop synchronization and employee execution: core agents, conversations and local application.
- Pipeline task snapshots and reports: core pipelines.
- Official host transport and execution: official application and employee integration; it consumes the core implementation.

## Validation

Use focused policy, conversation and pipeline tests plus the core and official CI entry points. Include opposite desktop/asset languages, explicit deliverable language, both model execution paths, preference-change isolation, retries/handoffs, malformed values, synchronization failure recovery, and literal preservation. Tests use mocked execution; real model calls are a separate validation activity.
