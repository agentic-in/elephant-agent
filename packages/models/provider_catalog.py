"""Shared provider catalog definitions and provider-specific runtime rules."""

from __future__ import annotations

from dataclasses import dataclass, field
import platform
import re
from typing import Mapping


COPILOT_REASONING_EFFORTS_GPT5 = ("minimal", "low", "medium", "high")
COPILOT_REASONING_EFFORTS_O_SERIES = ("low", "medium", "high")
ANTHROPIC_REASONING_EFFORTS = ("low", "medium", "high", "max")
ANTHROPIC_REASONING_EFFORTS_OPUS_47 = ("low", "medium", "high", "xhigh", "max")
ANTHROPIC_REASONING_EFFORTS_BASE = ("low", "medium", "high")
OPENAI_REASONING_EFFORTS_GPT5 = ("minimal", "low", "medium", "high")
OPENAI_REASONING_EFFORTS_O_SERIES = ("low", "medium", "high")

_QWEN_CODE_VERSION = "0.14.1"


def _copilot_default_headers() -> dict[str, str]:
    return {
        "Editor-Version": "vscode/1.99.3",
        "User-Agent": "Elephant Agent/1.0",
        "Openai-Intent": "conversation-edits",
        "x-initiator": "agent",
    }


def _qwen_portal_headers() -> dict[str, str]:
    machine = platform.machine().lower() or "unknown"
    system = platform.system().lower() or "unknown"
    user_agent = f"QwenCode/{_QWEN_CODE_VERSION} ({system}; {machine})"
    return {
        "User-Agent": user_agent,
        "X-DashScope-CacheControl": "enable",
        "X-DashScope-UserAgent": user_agent,
        "X-DashScope-AuthType": "qwen-oauth",
    }


@dataclass(frozen=True, slots=True)
class ProviderDefinition:
    provider_id: str
    display_name: str
    transport_id: str
    catalog_summary: str
    onboarding_hint: str
    default_base_url: str | None = None
    default_model_id: str | None = None
    endpoint_path_override: str | None = None
    required_secret_keys: tuple[str, ...] = ("api_key",)
    required_config_keys: tuple[str, ...] = ()
    capability_flags: tuple[str, ...] = ()
    model_hints: tuple[str, ...] = ()
    supports_custom_base_url: bool = True
    listing_priority: int = 100
    docs_url: str | None = None
    provider_kind: str = "first_party"
    auth_method: str = "api_key"
    auth_type: str = "api_key"
    env_var_names: tuple[str, ...] = ()
    base_url_env_var: str | None = None
    extra_headers: Mapping[str, str] = field(default_factory=dict)
    runtime_enabled: bool = True
    metadata: Mapping[str, str] = field(default_factory=dict)


_DEFAULT_PROVIDER_DEFINITIONS: tuple[ProviderDefinition, ...] = (
    ProviderDefinition(
        provider_id="openai-compatible",
        display_name="OpenAI-Compatible API",
        transport_id="openai_chat_compatible",
        catalog_summary="Connect any OpenAI-compatible endpoint with one shared runtime path.",
        onboarding_hint="Set a base URL, attach a compatible credential source, and choose a model from the live endpoint.",
        default_base_url=None,
        default_model_id="model-id",
        required_secret_keys=("api_key",),
        required_config_keys=("base_url", "model_id"),
        capability_flags=("chat", "embeddings"),
        model_hints=(),
        supports_custom_base_url=True,
        listing_priority=10,
        provider_kind="custom",
        auth_method="api_key",
        auth_type="api_key",
        metadata={
            "surface": "generic_endpoint",
            "unsupported_capabilities": "reasoning",
        },
    ),
    ProviderDefinition(
        provider_id="openai",
        display_name="OpenAI",
        transport_id="openai_responses",
        catalog_summary="Use OpenAI's first-party API with the shared runtime resolver.",
        onboarding_hint="Pick a model, attach an API key or imported credential, and validate the runtime from Elephant Agent.",
        default_base_url="https://api.openai.com/v1",
        default_model_id="gpt-4.1-mini",
        required_secret_keys=("api_key",),
        required_config_keys=("model_id",),
        capability_flags=("chat",),
        model_hints=("gpt-5.4", "gpt-5.4-mini", "gpt-4.1-mini", "o4-mini"),
        supports_custom_base_url=False,
        listing_priority=20,
        provider_kind="first_party",
        auth_method="api_key",
        auth_type="api_key",
        env_var_names=("OPENAI_API_KEY",),
        metadata={
            "surface": "first_party",
            "unsupported_capabilities": "embeddings",
        },
    ),
    ProviderDefinition(
        provider_id="openai-codex",
        display_name="OpenAI Codex (ChatGPT)",
        transport_id="openai_responses",
        catalog_summary="Use ChatGPT/Codex OAuth-backed models through the Responses runtime surface.",
        onboarding_hint="Elephant Agent can discover Codex credentials from your local Codex auth store and route GPT-5/Codex models without manual key entry.",
        default_base_url="https://chatgpt.com/backend-api/codex",
        default_model_id="gpt-5.4",
        endpoint_path_override="/responses",
        required_secret_keys=("api_key",),
        required_config_keys=("model_id",),
        capability_flags=("chat",),
        model_hints=(
            "gpt-5.4",
            "gpt-5.4-mini",
            "gpt-5.3-codex",
            "gpt-5.3-codex-spark",
            "gpt-5.2",
            "gpt-5.2-codex",
            "gpt-5.1-codex-max",
            "gpt-5.1-codex-mini",
        ),
        supports_custom_base_url=False,
        listing_priority=22,
        provider_kind="first_party",
        auth_method="oauth_external",
        auth_type="oauth_external",
        metadata={
            "surface": "oauth_external",
            "external_source": "codex_cli",
            "model_catalog_path": "/models?client_version=1.0.0",
            "model_payload_list_key": "models",
            "model_payload_id_key": "slug",
            "unsupported_capabilities": "embeddings",
        },
    ),
    ProviderDefinition(
        provider_id="openrouter",
        display_name="OpenRouter",
        transport_id="openai_chat_compatible",
        catalog_summary="Route Elephant Agent through OpenRouter with one shared compatible endpoint.",
        onboarding_hint="Pick a routed model, attach an API key, and validate the provider from the CLI.",
        default_base_url="https://openrouter.ai/api/v1",
        default_model_id="openai/gpt-4o-mini",
        required_secret_keys=("api_key",),
        required_config_keys=("model_id",),
        capability_flags=("chat", "embeddings"),
        model_hints=("openai/gpt-4o-mini", "anthropic/claude-3.7-sonnet", "google/gemini-2.5-pro"),
        supports_custom_base_url=False,
        listing_priority=25,
        provider_kind="aggregator",
        auth_method="api_key",
        auth_type="api_key",
        env_var_names=("OPENROUTER_API_KEY",),
        metadata={
            "surface": "aggregator",
            "unsupported_capabilities": "reasoning",
        },
    ),
    ProviderDefinition(
        provider_id="copilot",
        display_name="GitHub Copilot",
        transport_id="openai_chat_compatible",
        catalog_summary="Use GitHub Models / Copilot with dynamic transport selection based on the chosen model.",
        onboarding_hint="Elephant Agent can discover GitHub credentials from environment variables or `gh auth token`, then choose the matching transport for GPT, Claude, and Gemini models.",
        default_base_url="https://api.githubcopilot.com",
        default_model_id="gpt-5.4",
        required_secret_keys=("api_key",),
        required_config_keys=("model_id",),
        capability_flags=("chat",),
        model_hints=(
            "claude-opus-4.6",
            "claude-opus-4.6-1m",
            "claude-sonnet-4.6",
            "gpt-5.2-codex",
            "gpt-5.3-codex",
            "gpt-5.4-mini",
            "gpt-5.4",
            "gpt-5-mini",
            "grok-code-fast-1",
            "gpt-5.1",
            "claude-sonnet-4",
            "claude-sonnet-4.5",
            "claude-opus-4.5",
            "claude-haiku-4.5",
            "gpt-5.2",
            "gpt-4.1",
        ),
        supports_custom_base_url=False,
        listing_priority=28,
        provider_kind="oauth",
        auth_method="oauth_external",
        auth_type="oauth_external",
        env_var_names=("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"),
        extra_headers=_copilot_default_headers(),
        metadata={
            "surface": "github_models_oauth",
            "dynamic_transport": "copilot",
            "model_catalog_path": "/models",
            "model_detail_path_template": "/models/{model_id}",
            "unsupported_capabilities": "embeddings",
        },
    ),
    ProviderDefinition(
        provider_id="anthropic",
        display_name="Anthropic (Claude API)",
        transport_id="anthropic_messages",
        catalog_summary="Use Anthropic's native Messages API with Claude API keys or subscription tokens.",
        onboarding_hint="Choose a Claude model and attach an Anthropic API key or `ANTHROPIC_TOKEN`.",
        default_base_url="https://api.anthropic.com",
        default_model_id="claude-sonnet-4-0",
        required_secret_keys=("api_key",),
        required_config_keys=("model_id",),
        capability_flags=("chat",),
        model_hints=("claude-sonnet-4-0", "claude-opus-4-0", "claude-haiku-4-0"),
        supports_custom_base_url=False,
        listing_priority=30,
        provider_kind="oauth",
        auth_method="oauth_external",
        auth_type="oauth_external",
        env_var_names=("ANTHROPIC_API_KEY", "ANTHROPIC_TOKEN"),
        metadata={
            "surface": "oauth_external",
            "unsupported_capabilities": "streaming,embeddings",
        },
    ),
    ProviderDefinition(
        provider_id="claude-code",
        display_name="Claude Code (subscription)",
        transport_id="anthropic_messages",
        catalog_summary="Use Claude Code subscription OAuth credentials from the local Claude Code auth store.",
        onboarding_hint="Elephant Agent can detect Claude Code credentials from `~/.claude/.credentials.json` or `CLAUDE_CODE_OAUTH_TOKEN`.",
        default_base_url="https://api.anthropic.com",
        default_model_id="claude-sonnet-4-0",
        required_secret_keys=("api_key",),
        required_config_keys=("model_id",),
        capability_flags=("chat",),
        model_hints=("claude-sonnet-4-0", "claude-opus-4-0", "claude-haiku-4-0"),
        supports_custom_base_url=False,
        listing_priority=31,
        provider_kind="oauth",
        auth_method="oauth_external",
        auth_type="oauth_external",
        env_var_names=("CLAUDE_CODE_OAUTH_TOKEN",),
        metadata={
            "surface": "oauth_external",
            "external_source": "claude_code_credentials",
            "unsupported_capabilities": "streaming,embeddings",
        },
    ),
    ProviderDefinition(
        provider_id="google",
        display_name="Google Gemini",
        transport_id="openai_chat_compatible",
        catalog_summary="Use Gemini through Google's OpenAI-compatible endpoint.",
        onboarding_hint="Choose a Gemini model, attach an API key, and verify the direct Google route.",
        default_base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        default_model_id="gemini-2.5-flash",
        required_secret_keys=("api_key",),
        required_config_keys=("model_id",),
        capability_flags=("chat", "embeddings"),
        model_hints=("gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"),
        supports_custom_base_url=False,
        listing_priority=35,
        provider_kind="first_party",
        auth_method="api_key",
        auth_type="api_key",
        env_var_names=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        metadata={
            "surface": "first_party",
            "unsupported_capabilities": "reasoning",
        },
    ),
    ProviderDefinition(
        provider_id="google-gemini-cli",
        display_name="Google Gemini OAuth",
        transport_id="openai_chat_compatible",
        catalog_summary="Use Gemini CLI-compatible OAuth access tokens through the shared compatible runtime.",
        onboarding_hint="Choose a Gemini model and attach a valid Gemini CLI-compatible access token when this provider is selected.",
        default_base_url="cloudcode-pa://google",
        default_model_id="gemini-2.5-pro",
        required_secret_keys=("api_key",),
        required_config_keys=("model_id",),
        capability_flags=("chat",),
        model_hints=("gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"),
        supports_custom_base_url=False,
        listing_priority=36,
        provider_kind="oauth",
        auth_method="oauth_external",
        auth_type="oauth_external",
        metadata={
            "surface": "oauth_external",
            "unsupported_capabilities": "embeddings",
        },
    ),
    ProviderDefinition(
        provider_id="groq",
        display_name="Groq",
        transport_id="openai_chat_compatible",
        catalog_summary="Use Groq's fast OpenAI-compatible inference endpoint.",
        onboarding_hint="Pick a Groq-served model, attach an API key, and validate the low-latency route.",
        default_base_url="https://api.groq.com/openai/v1",
        default_model_id="llama-3.3-70b-versatile",
        required_secret_keys=("api_key",),
        required_config_keys=("model_id",),
        capability_flags=("chat", "embeddings"),
        model_hints=("llama-3.3-70b-versatile", "qwen-qwq-32b", "deepseek-r1-distill-llama-70b"),
        supports_custom_base_url=False,
        listing_priority=40,
        provider_kind="first_party",
        auth_method="api_key",
        auth_type="api_key",
        env_var_names=("GROQ_API_KEY",),
        metadata={
            "surface": "first_party",
            "unsupported_capabilities": "reasoning",
        },
    ),
    ProviderDefinition(
        provider_id="deepseek",
        display_name="DeepSeek",
        transport_id="openai_chat_compatible",
        catalog_summary="Use DeepSeek's OpenAI-compatible hosted models directly.",
        onboarding_hint="Choose a DeepSeek model, add an API key, and validate the provider from the CLI.",
        default_base_url="https://api.deepseek.com/v1",
        default_model_id="deepseek-chat",
        required_secret_keys=("api_key",),
        required_config_keys=("model_id",),
        capability_flags=("chat", "embeddings"),
        model_hints=("deepseek-chat", "deepseek-reasoner"),
        supports_custom_base_url=False,
        listing_priority=45,
        provider_kind="first_party",
        auth_method="api_key",
        auth_type="api_key",
        env_var_names=("DEEPSEEK_API_KEY",),
        metadata={
            "surface": "first_party",
            "unsupported_capabilities": "reasoning",
        },
    ),
    ProviderDefinition(
        provider_id="xai",
        display_name="xAI",
        transport_id="openai_chat_compatible",
        catalog_summary="Use xAI's hosted Grok models through a shared compatible runtime path.",
        onboarding_hint="Choose a Grok model, add an API key, and validate the provider from the CLI.",
        default_base_url="https://api.x.ai/v1",
        default_model_id="grok-4-fast-reasoning",
        required_secret_keys=("api_key",),
        required_config_keys=("model_id",),
        capability_flags=("chat", "embeddings"),
        model_hints=("grok-4-fast-reasoning", "grok-3-mini", "grok-2-vision"),
        supports_custom_base_url=False,
        listing_priority=50,
        provider_kind="first_party",
        auth_method="api_key",
        auth_type="api_key",
        env_var_names=("XAI_API_KEY",),
        metadata={
            "surface": "first_party",
            "unsupported_capabilities": "reasoning",
        },
    ),
    ProviderDefinition(
        provider_id="mistral",
        display_name="Mistral",
        transport_id="openai_chat_compatible",
        catalog_summary="Use Mistral's hosted models through the shared compatible runtime.",
        onboarding_hint="Pick a Mistral model, attach an API key, and validate the provider from the CLI.",
        default_base_url="https://api.mistral.ai/v1",
        default_model_id="mistral-small-latest",
        required_secret_keys=("api_key",),
        required_config_keys=("model_id",),
        capability_flags=("chat", "embeddings"),
        model_hints=("mistral-small-latest", "mistral-medium-latest", "codestral-latest"),
        supports_custom_base_url=False,
        listing_priority=55,
        provider_kind="first_party",
        auth_method="api_key",
        auth_type="api_key",
        env_var_names=("MISTRAL_API_KEY",),
        metadata={
            "surface": "first_party",
            "unsupported_capabilities": "reasoning",
        },
    ),
    ProviderDefinition(
        provider_id="together",
        display_name="Together AI",
        transport_id="openai_chat_compatible",
        catalog_summary="Use Together AI's hosted open-model catalog through one compatible endpoint.",
        onboarding_hint="Choose a Together model, add an API key, and validate the provider from the CLI.",
        default_base_url="https://api.together.ai/v1",
        default_model_id="meta-llama/Llama-4-Scout-17B-16E-Instruct",
        required_secret_keys=("api_key",),
        required_config_keys=("model_id",),
        capability_flags=("chat", "embeddings"),
        model_hints=("meta-llama/Llama-4-Scout-17B-16E-Instruct", "deepseek-ai/DeepSeek-V3.1", "Qwen/Qwen3-235B-A22B-Instruct-2507"),
        supports_custom_base_url=False,
        listing_priority=60,
        provider_kind="aggregator",
        auth_method="api_key",
        auth_type="api_key",
        env_var_names=("TOGETHER_API_KEY",),
        metadata={
            "surface": "aggregator",
            "unsupported_capabilities": "reasoning",
        },
    ),
    ProviderDefinition(
        provider_id="fireworks",
        display_name="Fireworks AI",
        transport_id="openai_chat_compatible",
        catalog_summary="Use Fireworks' hosted open-model runtime through one compatible endpoint.",
        onboarding_hint="Choose a Fireworks model, add an API key, and validate the provider from the CLI.",
        default_base_url="https://api.fireworks.ai/inference/v1",
        default_model_id="accounts/fireworks/models/deepseek-v3",
        required_secret_keys=("api_key",),
        required_config_keys=("model_id",),
        capability_flags=("chat", "embeddings"),
        model_hints=("accounts/fireworks/models/deepseek-v3", "accounts/fireworks/models/llama-v3p1-70b-instruct"),
        supports_custom_base_url=False,
        listing_priority=62,
        provider_kind="aggregator",
        auth_method="api_key",
        auth_type="api_key",
        env_var_names=("FIREWORKS_API_KEY",),
        metadata={
            "surface": "aggregator",
            "unsupported_capabilities": "reasoning",
        },
    ),
    ProviderDefinition(
        provider_id="moonshot-cn",
        display_name="Moonshot Kimi (China)",
        transport_id="openai_chat_compatible",
        catalog_summary="Use Moonshot Kimi models through the China-region api.moonshot.cn endpoint.",
        onboarding_hint="Choose a Kimi model, add a China-region API key, and validate the provider from the CLI. Use this provider for keys issued by platform.kimi.com.",
        default_base_url="https://api.moonshot.cn/v1",
        default_model_id="kimi-k2-0905-preview",
        required_secret_keys=("api_key",),
        required_config_keys=("model_id",),
        capability_flags=("chat", "embeddings"),
        model_hints=("kimi-k2-0905-preview", "kimi-k2-instruct", "moonshot-v1-8k"),
        supports_custom_base_url=False,
        listing_priority=65,
        provider_kind="first_party",
        auth_method="api_key",
        auth_type="api_key",
        env_var_names=("KIMI_API_KEY", "MOONSHOT_API_KEY"),
        base_url_env_var="KIMI_BASE_URL",
        metadata={
            "surface": "first_party",
            "unsupported_capabilities": "reasoning",
        },
    ),
    ProviderDefinition(
        provider_id="moonshot",
        display_name="Moonshot Kimi",
        transport_id="openai_chat_compatible",
        catalog_summary="Use Moonshot Kimi models through the international api.moonshot.ai endpoint.",
        onboarding_hint="Choose a Kimi model, add an international-region API key, and validate the provider from the CLI. Use this provider for keys issued by platform.moonshot.ai.",
        default_base_url="https://api.moonshot.ai/v1",
        default_model_id="kimi-k2-0905-preview",
        required_secret_keys=("api_key",),
        required_config_keys=("model_id",),
        capability_flags=("chat", "embeddings"),
        model_hints=("kimi-k2-0905-preview", "kimi-k2-instruct", "moonshot-v1-8k"),
        supports_custom_base_url=False,
        listing_priority=66,
        provider_kind="first_party",
        auth_method="api_key",
        auth_type="api_key",
        env_var_names=("MOONSHOT_API_KEY", "KIMI_API_KEY"),
        base_url_env_var="MOONSHOT_BASE_URL",
        metadata={
            "surface": "first_party",
            "unsupported_capabilities": "reasoning",
        },
    ),
    ProviderDefinition(
        provider_id="qwen-oauth",
        display_name="Qwen (via Qwen CLI)",
        transport_id="openai_chat_compatible",
        catalog_summary="Use Qwen Portal OAuth credentials discovered from the local Qwen CLI token store.",
        onboarding_hint="Elephant Agent can import Qwen Portal credentials from `~/.qwen/oauth_creds.json` and route requests through the portal endpoint.",
        default_base_url="https://portal.qwen.ai/v1",
        default_model_id="qwen3-coder-plus",
        required_secret_keys=("api_key",),
        required_config_keys=("model_id",),
        capability_flags=("chat",),
        model_hints=("qwen3-coder-plus", "qwen3-235b-a22b", "qwen-max"),
        supports_custom_base_url=False,
        listing_priority=66,
        provider_kind="oauth",
        auth_method="oauth_external",
        auth_type="oauth_external",
        base_url_env_var="ELEPHANT_QWEN_BASE_URL",
        extra_headers=_qwen_portal_headers(),
        metadata={
            "surface": "oauth_external",
            "external_source": "qwen_cli",
            "unsupported_capabilities": "reasoning,embeddings",
        },
    ),
    ProviderDefinition(
        provider_id="minimax",
        display_name="MiniMax",
        transport_id="anthropic_messages",
        catalog_summary="Use MiniMax's Anthropic-compatible reasoning models without changing the kernel path.",
        onboarding_hint="Choose a MiniMax model, add an API key, and validate the provider from the CLI.",
        default_base_url="https://api.minimax.io/anthropic",
        default_model_id="MiniMax-M2.7",
        required_secret_keys=("api_key",),
        required_config_keys=("model_id",),
        capability_flags=("chat",),
        model_hints=("MiniMax-M2.7", "MiniMax-M2.7-highspeed", "MiniMax-M2.5", "MiniMax-M2.5-highspeed", "MiniMax-M2.1", "MiniMax-M2.1-highspeed", "MiniMax-M2"),
        supports_custom_base_url=False,
        listing_priority=70,
        provider_kind="first_party",
        auth_method="api_key",
        auth_type="api_key",
        env_var_names=("MINIMAX_API_KEY",),
        base_url_env_var="MINIMAX_BASE_URL",
        metadata={
            "surface": "first_party",
            "unsupported_capabilities": "reasoning,embeddings",
        },
    ),
    ProviderDefinition(
        provider_id="minimax-cn",
        display_name="MiniMax China",
        transport_id="anthropic_messages",
        catalog_summary="Use MiniMax's China-region Anthropic-compatible endpoint.",
        onboarding_hint="Attach a China-region MiniMax key and choose a domestic MiniMax model when you need the direct regional endpoint.",
        default_base_url="https://api.minimaxi.com/anthropic",
        default_model_id="MiniMax-M2.7",
        required_secret_keys=("api_key",),
        required_config_keys=("model_id",),
        capability_flags=("chat",),
        model_hints=("MiniMax-M2.7", "MiniMax-M2.7-highspeed", "MiniMax-M2.5", "MiniMax-M2.5-highspeed", "MiniMax-M2.1", "MiniMax-M2.1-highspeed", "MiniMax-M2"),
        supports_custom_base_url=False,
        listing_priority=72,
        provider_kind="first_party",
        auth_method="api_key",
        auth_type="api_key",
        env_var_names=("MINIMAX_CN_API_KEY",),
        base_url_env_var="MINIMAX_CN_BASE_URL",
        metadata={
            "surface": "first_party",
            "unsupported_capabilities": "reasoning,embeddings",
        },
    ),
    ProviderDefinition(
        provider_id="zhipu",
        display_name="ZhipuAI (China)",
        transport_id="openai_chat_compatible",
        catalog_summary="Use ZhipuAI's GLM models through the official China-region open.bigmodel.cn endpoint.",
        onboarding_hint="Choose a GLM model, add a ZhipuAI API key, and validate the provider from the CLI.",
        default_base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model_id="glm-5.1",
        endpoint_path_override="/chat/completions",
        required_secret_keys=("api_key",),
        required_config_keys=("model_id",),
        capability_flags=("chat", "embeddings"),
        model_hints=("glm-5.1", "glm-5", "glm-5-turbo", "glm-4.7", "glm-4.7-flashx", "glm-4.6", "glm-4.5-air", "glm-4-long"),
        supports_custom_base_url=False,
        listing_priority=73,
        docs_url="https://docs.bigmodel.cn/cn/api/introduction",
        provider_kind="first_party",
        auth_method="api_key",
        auth_type="api_key",
        env_var_names=("ZHIPU_API_KEY",),
        base_url_env_var="ZHIPU_BASE_URL",
        metadata={
            "surface": "first_party",
            "unsupported_capabilities": "reasoning",
        },
    ),
    ProviderDefinition(
        provider_id="zai",
        display_name="Z.AI / GLM",
        transport_id="openai_chat_compatible",
        catalog_summary="Use Z.AI / GLM through the provider's OpenAI-compatible endpoint.",
        onboarding_hint="Attach a GLM or Z.AI key, let Elephant Agent discover the working endpoint, and select a coding or general model.",
        default_base_url="https://api.z.ai/api/paas/v4",
        default_model_id="glm-5",
        required_secret_keys=("api_key",),
        required_config_keys=("model_id",),
        capability_flags=("chat", "embeddings"),
        model_hints=("glm-5", "glm-5.1", "glm-4.7"),
        supports_custom_base_url=False,
        listing_priority=73,
        provider_kind="first_party",
        auth_method="api_key",
        auth_type="api_key",
        env_var_names=("GLM_API_KEY", "ZAI_API_KEY", "Z_AI_API_KEY"),
        base_url_env_var="GLM_BASE_URL",
        metadata={
            "surface": "first_party",
            "unsupported_capabilities": "reasoning",
        },
    ),
    ProviderDefinition(
        provider_id="alibaba",
        display_name="Alibaba DashScope",
        transport_id="openai_chat_compatible",
        catalog_summary="Use DashScope's OpenAI-compatible endpoint directly from Elephant Agent.",
        onboarding_hint="Attach a DashScope key and choose a compatible model or coding endpoint.",
        default_base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        default_model_id="qwen-max",
        required_secret_keys=("api_key",),
        required_config_keys=("model_id",),
        capability_flags=("chat", "embeddings"),
        model_hints=("qwen-max", "qwen-plus", "qwen3-coder-plus"),
        supports_custom_base_url=False,
        listing_priority=74,
        provider_kind="first_party",
        auth_method="api_key",
        auth_type="api_key",
        env_var_names=("DASHSCOPE_API_KEY",),
        base_url_env_var="DASHSCOPE_BASE_URL",
        metadata={
            "surface": "first_party",
            "unsupported_capabilities": "reasoning",
        },
    ),
    ProviderDefinition(
        provider_id="xiaomi",
        display_name="Xiaomi MiMo",
        transport_id="openai_chat_compatible",
        catalog_summary="Use Xiaomi MiMo's hosted OpenAI-compatible endpoint for MiMo-V2 models.",
        onboarding_hint="Attach a Xiaomi MiMo API key and choose MiMo-V2 Pro, Omni, or Flash from the provider catalog.",
        default_base_url="https://api.xiaomimimo.com/v1",
        default_model_id="mimo-v2-pro",
        required_secret_keys=("api_key",),
        required_config_keys=("model_id",),
        capability_flags=("chat", "embeddings"),
        model_hints=("mimo-v2-pro", "mimo-v2-omni", "mimo-v2-flash"),
        supports_custom_base_url=False,
        listing_priority=75,
        provider_kind="first_party",
        auth_method="api_key",
        auth_type="api_key",
        env_var_names=("XIAOMI_API_KEY",),
        base_url_env_var="XIAOMI_BASE_URL",
        metadata={
            "surface": "first_party",
            "unsupported_capabilities": "reasoning",
        },
    ),
    ProviderDefinition(
        provider_id="huggingface",
        display_name="Hugging Face",
        transport_id="openai_chat_compatible",
        catalog_summary="Use Hugging Face's routed inference endpoint through the shared compatible runtime.",
        onboarding_hint="Attach an HF token and choose a supported routed model.",
        default_base_url="https://router.huggingface.co/v1",
        default_model_id="openai/gpt-oss-120b",
        required_secret_keys=("api_key",),
        required_config_keys=("model_id",),
        capability_flags=("chat", "embeddings"),
        model_hints=("openai/gpt-oss-120b", "meta-llama/Llama-3.3-70B-Instruct", "Qwen/Qwen3-235B-A22B-Instruct-2507"),
        supports_custom_base_url=False,
        listing_priority=76,
        provider_kind="aggregator",
        auth_method="api_key",
        auth_type="api_key",
        env_var_names=("HF_TOKEN",),
        base_url_env_var="HF_BASE_URL",
        metadata={
            "surface": "aggregator",
            "unsupported_capabilities": "reasoning",
        },
    ),
    ProviderDefinition(
        provider_id="opencode-zen",
        display_name="OpenCode Zen",
        transport_id="openai_chat_compatible",
        catalog_summary="Use OpenCode Zen with dynamic transport selection for GPT, Claude, and other routed models.",
        onboarding_hint="Attach an OpenCode Zen key and choose a Zen-routed model.",
        default_base_url="https://opencode.ai/zen/v1",
        default_model_id="gpt-5.4",
        required_secret_keys=("api_key",),
        required_config_keys=("model_id",),
        capability_flags=("chat",),
        model_hints=("gpt-5.4", "gpt-5.3-codex", "claude-sonnet-4-6", "gemini-3-flash"),
        supports_custom_base_url=False,
        listing_priority=78,
        provider_kind="aggregator",
        auth_method="api_key",
        auth_type="api_key",
        env_var_names=("OPENCODE_ZEN_API_KEY",),
        base_url_env_var="OPENCODE_ZEN_BASE_URL",
        metadata={
            "surface": "aggregator",
            "dynamic_transport": "opencode",
            "unsupported_capabilities": "embeddings",
        },
    ),
    ProviderDefinition(
        provider_id="opencode-go",
        display_name="OpenCode Go",
        transport_id="openai_chat_compatible",
        catalog_summary="Use OpenCode Go with dynamic transport selection for GLM, Kimi, and MiniMax models.",
        onboarding_hint="Attach an OpenCode Go key and choose a Go-routed model.",
        default_base_url="https://opencode.ai/zen/go/v1",
        default_model_id="glm-5",
        required_secret_keys=("api_key",),
        required_config_keys=("model_id",),
        capability_flags=("chat",),
        model_hints=("glm-5", "kimi-k2.5", "minimax-m2.7"),
        supports_custom_base_url=False,
        listing_priority=79,
        provider_kind="aggregator",
        auth_method="api_key",
        auth_type="api_key",
        env_var_names=("OPENCODE_GO_API_KEY",),
        base_url_env_var="OPENCODE_GO_BASE_URL",
        metadata={
            "surface": "aggregator",
            "dynamic_transport": "opencode",
            "unsupported_capabilities": "embeddings",
        },
    ),
    ProviderDefinition(
        provider_id="kilocode",
        display_name="Kilo Code",
        transport_id="openai_chat_compatible",
        catalog_summary="Use Kilo Code's gateway as another routed compatible provider.",
        onboarding_hint="Attach a Kilo gateway key, choose a routed model, and validate the provider from the CLI.",
        default_base_url="https://api.kilo.ai/api/gateway",
        default_model_id="google/gemini-3-flash-preview",
        required_secret_keys=("api_key",),
        required_config_keys=("model_id",),
        capability_flags=("chat", "embeddings"),
        model_hints=("google/gemini-3-flash-preview", "openai/gpt-5.4", "anthropic/claude-sonnet-4.6"),
        supports_custom_base_url=False,
        listing_priority=79,
        provider_kind="aggregator",
        auth_method="api_key",
        auth_type="api_key",
        env_var_names=("KILOCODE_API_KEY",),
        base_url_env_var="KILOCODE_BASE_URL",
        metadata={
            "surface": "aggregator",
            "unsupported_capabilities": "reasoning",
        },
    ),
    ProviderDefinition(
        provider_id="ollama",
        display_name="Ollama",
        transport_id="openai_chat_compatible",
        catalog_summary="Use a local Ollama /v1 endpoint through the compatible runtime path.",
        onboarding_hint="Point Elephant Agent at your Ollama endpoint, choose a local model, and grow against the local runtime.",
        default_base_url="http://127.0.0.1:11434/v1",
        default_model_id="llama3.2",
        required_secret_keys=(),
        required_config_keys=("base_url", "model_id"),
        capability_flags=("chat", "embeddings"),
        model_hints=("llama3.2", "qwen2.5:7b", "gemma3:12b"),
        supports_custom_base_url=True,
        listing_priority=80,
        provider_kind="local",
        auth_method="none",
        auth_type="none",
        metadata={
            "surface": "local_runtime",
            "unsupported_capabilities": "reasoning",
        },
    ),
    ProviderDefinition(
        provider_id="vllm",
        display_name="vLLM",
        transport_id="openai_chat_compatible",
        catalog_summary="Use a self-hosted vLLM OpenAI-compatible endpoint as Elephant Agent' live mind.",
        onboarding_hint="Point Elephant Agent at your vLLM /v1 endpoint, choose a served model id, and validate the local route.",
        default_base_url="http://127.0.0.1:8000/v1",
        default_model_id="Qwen/Qwen2.5-7B-Instruct",
        required_secret_keys=(),
        required_config_keys=("base_url", "model_id"),
        capability_flags=("chat", "embeddings"),
        model_hints=("Qwen/Qwen2.5-7B-Instruct", "meta-llama/Llama-3.1-8B-Instruct", "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B"),
        supports_custom_base_url=True,
        listing_priority=85,
        provider_kind="self_hosted",
        auth_method="none",
        auth_type="none",
        metadata={
            "surface": "self_hosted",
            "unsupported_capabilities": "reasoning",
        },
    ),
    ProviderDefinition(
        provider_id="copilot-acp",
        display_name="GitHub Copilot ACP",
        transport_id="openai_responses",
        catalog_summary="Use the local Copilot ACP process when an ACP-compatible client is installed.",
        onboarding_hint="Elephant Agent can discover the local Copilot CLI process surface, but runtime execution is not enabled until an ACP adapter exists.",
        default_base_url="acp://copilot",
        default_model_id="copilot-acp",
        required_secret_keys=(),
        required_config_keys=("model_id",),
        capability_flags=("chat",),
        model_hints=("copilot-acp",),
        supports_custom_base_url=False,
        listing_priority=90,
        provider_kind="local_process",
        auth_method="external_process",
        auth_type="external_process",
        base_url_env_var="COPILOT_ACP_BASE_URL",
        runtime_enabled=False,
        metadata={
            "surface": "external_process",
            "runtime_status": "discovery_only",
            "unsupported_capabilities": "streaming,reasoning,embeddings",
        },
    ),
)


def default_provider_definitions(*, include_discovery_only: bool = False) -> tuple[ProviderDefinition, ...]:
    if include_discovery_only:
        return _DEFAULT_PROVIDER_DEFINITIONS
    return tuple(definition for definition in _DEFAULT_PROVIDER_DEFINITIONS if definition.runtime_enabled)


def provider_definition(provider_id: str) -> ProviderDefinition | None:
    normalized = provider_id.strip().lower()
    for definition in _DEFAULT_PROVIDER_DEFINITIONS:
        if definition.provider_id == normalized:
            return definition
    return None


def resolve_transport_id(
    *,
    provider_id: str,
    default_transport_id: str,
    model_id: str | None,
) -> str:
    normalized_provider = provider_id.strip().lower()
    normalized_model = str(model_id or "").strip().lower()
    if normalized_provider == "copilot":
        if normalized_model.startswith("claude-"):
            return "anthropic_messages"
        if _uses_openai_responses_transport(normalized_model):
            return "openai_responses"
        return "openai_chat_compatible"
    if normalized_provider == "opencode-zen":
        if normalized_model.startswith("claude-"):
            return "anthropic_messages"
        if normalized_model.startswith("gpt-"):
            return "openai_responses"
        return "openai_chat_compatible"
    if normalized_provider == "opencode-go":
        if normalized_model.startswith("minimax-"):
            return "anthropic_messages"
        return "openai_chat_compatible"
    return default_transport_id


def reasoning_efforts_for(
    *,
    provider_id: str,
    model_id: str | None,
) -> tuple[str, ...]:
    normalized_provider = provider_id.strip().lower()
    normalized_model = str(model_id or "").strip().lower()
    if not normalized_model:
        return ()
    if normalized_provider in {"openai", "openai-codex"}:
        return _openai_reasoning_efforts_for_model_id(normalized_model)
    if normalized_provider == "copilot":
        return _copilot_reasoning_efforts_for_model_id(normalized_model)
    if normalized_provider in {"anthropic", "claude-code"}:
        if "haiku" in normalized_model:
            return ()
        if "opus-4-7" in normalized_model or "opus-4.7" in normalized_model:
            return ANTHROPIC_REASONING_EFFORTS_OPUS_47
        if "4-6" in normalized_model or "4.6" in normalized_model:
            return ANTHROPIC_REASONING_EFFORTS
        return ANTHROPIC_REASONING_EFFORTS_BASE
    return ()


def supports_reasoning(
    *,
    provider_id: str,
    model_id: str | None,
) -> bool:
    return bool(reasoning_efforts_for(provider_id=provider_id, model_id=model_id))


def _uses_openai_responses_transport(model_id: str) -> bool:
    match = re.match(r"^gpt-(\d+)", model_id)
    if not match:
        return False
    major = int(match.group(1))
    return major >= 5 and not model_id.startswith("gpt-5-mini")


def _openai_reasoning_efforts_for_model_id(model_id: str) -> tuple[str, ...]:
    if model_id.startswith(("o1", "o3", "o4", "gpt-o1", "gpt-o3", "gpt-o4")):
        return OPENAI_REASONING_EFFORTS_O_SERIES
    if model_id.startswith("gpt-5"):
        return OPENAI_REASONING_EFFORTS_GPT5
    return ()


def _copilot_reasoning_efforts_for_model_id(model_id: str) -> tuple[str, ...]:
    if model_id.startswith(("openai/o1", "openai/o3", "openai/o4", "o1", "o3", "o4")):
        return COPILOT_REASONING_EFFORTS_O_SERIES
    bare = model_id.split("/", 1)[1] if "/" in model_id else model_id
    if bare.startswith("gpt-5"):
        return COPILOT_REASONING_EFFORTS_GPT5
    return ()
