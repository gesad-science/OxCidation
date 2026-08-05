"""LLM provider factory for OpenAI, OpenRouter, and Ollama."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

import ollama
from langchain_core.output_parsers import JsonOutputParser
from langchain_openai import ChatOpenAI
from pydantic import BaseModel


@dataclass
class LLMResponse:
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMProvider(Protocol):
    name: str

    def chat(self, prompt: str, *, json_mode: bool = False) -> LLMResponse: ...


class OllamaProvider:
    name = "ollama"

    def __init__(self, model: str, base_url: str | None = None):
        self.model = model
        host = base_url or os.getenv("OLLAMA_HOST")
        self._client = ollama.Client(host=host) if host else ollama.Client()

    def chat(self, prompt: str, *, json_mode: bool = False) -> LLMResponse:
        kwargs: dict = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if json_mode:
            kwargs["format"] = "json"

        response = self._client.chat(**kwargs)
        return LLMResponse(
            content=response.message.content or "",
            prompt_tokens=response.prompt_eval_count or 0,
            completion_tokens=response.eval_count or 0,
        )


class OpenAICompatibleProvider:
    def __init__(self, name: str, llm: ChatOpenAI):
        self.name = name
        self._llm = llm

    def chat(self, prompt: str, *, json_mode: bool = False) -> LLMResponse:
        llm = self._llm
        if json_mode:
            llm = llm.bind(response_format={"type": "json_object"})

        response = llm.invoke(prompt)
        usage = response.usage_metadata or {}
        return LLMResponse(
            content=response.content or "",
            prompt_tokens=usage.get("input_tokens", 0),
            completion_tokens=usage.get("output_tokens", 0),
        )

    def structured_chat(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        structured_llm = self._llm.with_structured_output(
            schema, method="json_schema", strict=True
        )
        return structured_llm.invoke(prompt)

    def chat_with_json_parser(
        self, prompt: str, schema: type[BaseModel]
    ) -> LLMResponse:
        parser = JsonOutputParser(pydantic_object=schema)
        fallback_prompt = (
            "You are an expert C to Rust translator.\n"
            f"{parser.get_format_instructions()}\n\n"
            f"{prompt}"
        )
        response = self.chat(fallback_prompt, json_mode=True)
        parsed = parser.invoke(response.content)
        return LLMResponse(
            content=parsed.get("rust_code", ""),
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
        )


def create_provider(config: dict) -> LLMProvider | OpenAICompatibleProvider:
    provider = config.get("provider", "openrouter").lower()
    model = config.get("model", "openai/gpt-oss-120b:free")

    if provider == "ollama":
        return OllamaProvider(model=model, base_url=config.get("base_url"))

    if provider == "openrouter":
        llm = ChatOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY", "dummy"),
            model=model,
        )
        return OpenAICompatibleProvider("openrouter", llm)

    llm = ChatOpenAI(api_key=os.getenv("OPENAI_API_KEY", "dummy"), model=model)
    return OpenAICompatibleProvider("openai", llm)
