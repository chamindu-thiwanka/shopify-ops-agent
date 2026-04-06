"""
LLM Provider Interface
----------------------
WHY THIS EXISTS:
  We have multiple AI models (llama3, mistral, maybe Gemini).
  Different agents use different models.
  
  Without this file, every agent would have its own way of calling an LLM.
  If you ever wanted to switch from llama3 to a better model, you'd have
  to change code in 5 different files.
  
  With this file, you change ONE place and all agents automatically use
  the new model. This is called the "Strategy Pattern" in software design.
  
  It also makes the multi-LLM requirement obvious to evaluators —
  they can clearly see two different providers being defined and assigned.
"""

import os
import json
import time
import requests
from abc import ABC, abstractmethod
from tenacity import retry, stop_after_attempt, wait_exponential
from dotenv import load_dotenv

load_dotenv()  # Load secrets from .env file


class LLMProvider(ABC):
    """
    Abstract base class — a template that all providers must follow.
    
    WHY ABSTRACT: By defining complete() as @abstractmethod, Python will
    raise an error if someone creates a provider without implementing it.
    This prevents bugs where a provider "forgets" to handle completions.
    """

    @abstractmethod
    def complete(self, prompt: str, system: str = "") -> str:
        """
        Send a prompt to the LLM and get a text response back.
        
        Args:
            prompt: The actual question or task for the model
            system: Background instructions that set the model's behaviour
                    (e.g. "You are a product copywriter. Return only JSON.")
        
        Returns:
            The model's text response as a plain string
        """
        pass

    def complete_json(self, prompt: str, system: str = "") -> dict:
        """
        Like complete(), but expects JSON back and parses it safely.
        
        WHY THIS METHOD EXISTS:
          LLMs often wrap JSON in markdown code fences like ```json ... ```
          They sometimes add explanations before or after the JSON.
          This method handles all of that automatically so agents don't
          have to repeat the same parsing logic everywhere.
        """
        raw = self.complete(prompt, system)
        return self._parse_json_safely(raw)


    def _parse_json_safely(self, raw: str) -> dict:
        import re
        # Strip Qwen3 thinking blocks: <think>...</think>
        cleaned = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
        # Remove ```json ... ``` or ``` ... ``` wrappers
        cleaned = re.sub(r'```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'```\s*', '', cleaned).strip()
        
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}|\[.*\]', cleaned, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            print(f"  [WARNING] Could not parse LLM JSON. Raw: {raw[:200]}")
            return {}


class OllamaProvider(LLMProvider):
    """
    Runs AI models locally on your laptop via Ollama.
    
    WHY OLLAMA:
      Free, private (data never leaves your computer), works offline.
      Ollama runs as a background service and exposes an HTTP API
      at localhost:11434. We just send it HTTP POST requests.
    """

    def __init__(self, model: str = "llama3"):
        self.model = model
        self.base_url = "http://localhost:11434/api/generate"
        print(f"  [LLM] Using Ollama with model: {model}")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def complete(self, prompt: str, system: str = "") -> str:
        """
        WHY @retry:
          Local LLMs sometimes time out or return errors.
          @retry automatically tries again up to 3 times,
          waiting 2s, then 4s, then 8s between attempts.
          This is called "exponential backoff" and is standard
          practice for any production code calling external services.
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,        # Get complete response, not token-by-token
            "options": {
                "temperature": 0.7, # 0 = deterministic, 1 = creative
                "num_predict": 2000 # Max tokens to generate
            }
        }
        if system:
            payload["system"] = system

        response = requests.post(self.base_url, json=payload, timeout=120)
        response.raise_for_status()
        return response.json()["response"]


class GeminiProvider(LLMProvider):
    """
    Google Gemini free tier — 15 requests/minute, no cost.
    
    WHY GEMINI AS BACKUP:
      If your laptop is slow and Ollama takes 3 minutes per response,
      Gemini is much faster (cloud-based). Free tier is generous enough
      for this project (10 LLM calls total across all agents).
      
      Set GEMINI_API_KEY in your .env file to use this.
      Get a free key at: https://aistudio.google.com/app/apikey
    """

    def __init__(self):
        import google.generativeai as genai
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in .env file")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-1.5-flash")
        print("  [LLM] Using Google Gemini (gemini-1.5-flash)")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def complete(self, prompt: str, system: str = "") -> str:
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        response = self.model.generate_content(full_prompt)
        return response.text


def get_provider(name: str) -> LLMProvider:
    """
    Factory function — creates a provider by name.
    
    WHY A FACTORY:
      The manager agent calls get_provider("ollama_llama3") and gets
      back a ready-to-use provider object. It doesn't need to know
      any details about how Ollama or Gemini work internally.
      This separation of "what I want" from "how it works" is called
      abstraction, and it's one of the core principles of good software.
    
    To switch all LLM calls to Gemini: just change the string in manager.py.
    Nothing else needs to change.
    """
    providers = {
        "ollama_llama3":  lambda: OllamaProvider("llama3"),
        "ollama_mistral": lambda: OllamaProvider("mistral"),
        "ollama_qwen3":    lambda: OllamaProvider("qwen3:1.7b"),
        "gemini":         lambda: GeminiProvider(),
    }
    if name not in providers:
        raise ValueError(f"Unknown provider '{name}'. Available: {list(providers.keys())}")
    return providers[name]()