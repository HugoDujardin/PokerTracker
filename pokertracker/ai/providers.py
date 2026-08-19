"""Fournisseurs de modeles pour le coach.

Gemini (Google AI Studio) est le fournisseur par defaut: son palier gratuit
permet d'utiliser le coach sans abonnement. Anthropic reste disponible pour
qui possede deja une cle.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Protocol


class ProviderError(RuntimeError):
    """Erreur d'appel (cle manquante, quota, reseau)."""


@dataclass
class ProviderConfig:
    api_key: str = ""
    model: str = ""
    deep_analysis: bool = True         # laisse le modele « reflechir » plus longtemps
    max_tokens: int = 4096


class Provider(Protocol):
    name: str
    label: str
    env_var: str
    package: str
    install_hint: str
    default_model: str
    models: List[str]
    free_tier: bool

    def available(self, config: ProviderConfig) -> tuple[bool, str]: ...

    def stream(self, config: ProviderConfig, system: str, prompt: str,
               on_chunk: Optional[Callable[[str], None]] = None,
               stop: Optional[Callable[[], bool]] = None) -> str: ...


class _Base:
    name = ""
    label = ""
    env_var = ""
    package = ""
    install_hint = ""
    default_model = ""
    models: List[str] = []
    free_tier = False

    def resolved_key(self, config: ProviderConfig) -> str:
        return config.api_key or os.environ.get(self.env_var, "")

    def available(self, config: ProviderConfig) -> tuple[bool, str]:
        try:
            __import__(self.package)
        except ImportError:
            return False, f"Module « {self.package} » absent. Installez-le: {self.install_hint}"
        if not self.resolved_key(config):
            return False, (f"Aucune cle d'API {self.label}. Collez-la dans l'onglet Coach IA "
                           f"ou definissez la variable d'environnement {self.env_var}.")
        return True, ""


class GeminiProvider(_Base):
    """Google Gemini via AI Studio (palier gratuit)."""

    name = "gemini"
    label = "Google Gemini"
    env_var = "GEMINI_API_KEY"
    package = "google.genai"
    install_hint = "pip install google-genai"
    default_model = "gemini-2.5-flash"
    #: modeles proposes par defaut; la liste reelle du compte est recuperee
    #: par `list_models()` des qu'une cle est saisie
    models = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro", "gemini-2.0-flash"]
    free_tier = True
    key_url = "https://aistudio.google.com/apikey"

    def __init__(self, client=None) -> None:
        self._client = client            # injectable pour les tests

    def client(self, config: ProviderConfig):
        if self._client is not None:
            return self._client
        ok, reason = self.available(config)
        if not ok:
            raise ProviderError(reason)
        from google import genai

        return genai.Client(api_key=self.resolved_key(config))

    def list_models(self, config: ProviderConfig) -> List[str]:
        """Modeles reellement disponibles pour cette cle."""
        try:
            client = self.client(config)
            names = []
            for model in client.models.list():
                name = (getattr(model, "name", "") or "").replace("models/", "")
                actions = getattr(model, "supported_actions", None) or []
                if name.startswith("gemini") and (not actions or "generateContent" in actions):
                    names.append(name)
            return sorted(set(names)) or list(self.models)
        except Exception:
            return list(self.models)

    def stream(self, config: ProviderConfig, system: str, prompt: str,
               on_chunk: Optional[Callable[[str], None]] = None,
               stop: Optional[Callable[[], bool]] = None) -> str:
        from google.genai import types

        client = self.client(config)
        thinking = types.ThinkingConfig(thinking_budget=-1 if config.deep_analysis else 0)
        settings = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=config.max_tokens,
            temperature=0.4,
            thinking_config=thinking,
        )
        pieces: List[str] = []
        try:
            for chunk in client.models.generate_content_stream(
                    model=config.model or self.default_model, contents=prompt, config=settings):
                text = getattr(chunk, "text", None)
                if text:
                    pieces.append(text)
                    if on_chunk:
                        on_chunk(text)
                if stop and stop():
                    break
        except Exception as exc:
            raise ProviderError(_readable_error(exc)) from exc
        if not pieces:
            raise ProviderError("Le modele n'a renvoye aucun texte (contenu bloque ou quota "
                                "atteint). Reessayez, ou choisissez un autre modele.")
        return "".join(pieces)


class AnthropicProvider(_Base):
    """Claude via l'API Anthropic (payante, pour qui possede deja une cle)."""

    name = "anthropic"
    label = "Anthropic Claude"
    env_var = "ANTHROPIC_API_KEY"
    package = "anthropic"
    install_hint = "pip install anthropic"
    default_model = "claude-opus-5"
    models = ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"]
    free_tier = False
    key_url = "https://console.anthropic.com/settings/keys"

    def __init__(self, client=None) -> None:
        self._client = client

    def client(self, config: ProviderConfig):
        if self._client is not None:
            return self._client
        ok, reason = self.available(config)
        if not ok:
            raise ProviderError(reason)
        import anthropic

        return anthropic.Anthropic(api_key=self.resolved_key(config))

    def list_models(self, config: ProviderConfig) -> List[str]:
        return list(self.models)

    def stream(self, config: ProviderConfig, system: str, prompt: str,
               on_chunk: Optional[Callable[[str], None]] = None,
               stop: Optional[Callable[[], bool]] = None) -> str:
        client = self.client(config)
        pieces: List[str] = []
        try:
            with client.messages.stream(
                model=config.model or self.default_model,
                max_tokens=max(1024, config.max_tokens),
                system=system,
                thinking={"type": "adaptive"},
                output_config={"effort": "high" if config.deep_analysis else "low"},
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                for text in stream.text_stream:
                    pieces.append(text)
                    if on_chunk:
                        on_chunk(text)
                    if stop and stop():
                        break
                else:
                    final = stream.get_final_message()
                    if getattr(final, "stop_reason", "") == "refusal":
                        raise ProviderError("Le modele a refuse de repondre a cette demande.")
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(_readable_error(exc)) from exc
        return "".join(pieces)


def _readable_error(exc: Exception) -> str:
    """Message d'erreur comprehensible pour l'utilisateur."""
    text = str(exc)
    low = text.lower()
    if "429" in text or "quota" in low or "rate limit" in low or "resource_exhausted" in low:
        return ("Quota atteint pour cette cle. Le palier gratuit de Gemini est limite par "
                "minute et par jour: patientez une minute, ou choisissez un modele plus leger "
                "(gemini-2.5-flash-lite).")
    if "api key" in low or "401" in text or "403" in text or "permission" in low:
        return "Cle d'API refusee. Verifiez-la (elle doit correspondre au fournisseur choisi)."
    if "not found" in low or "404" in text:
        return "Modele introuvable pour cette cle. Cliquez sur « Modeles disponibles »."
    if "connection" in low or "timeout" in low or "network" in low:
        return "Connexion impossible a l'API. Verifiez votre acces internet."
    return f"Appel a l'assistant impossible: {text}"


PROVIDERS = {p.name: p for p in (GeminiProvider(), AnthropicProvider())}
DEFAULT_PROVIDER = "gemini"


def get_provider(name: str):
    return PROVIDERS.get(name or DEFAULT_PROVIDER, PROVIDERS[DEFAULT_PROVIDER])
