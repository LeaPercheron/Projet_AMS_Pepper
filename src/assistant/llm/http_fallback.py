#!/usr/bin/env python3
# Fallback OpenAI HTTP (sans Realtime WebSocket)

from __future__ import annotations

from typing import Any, Dict, Optional


SYSTEM_PROMPT = (
    "Tu es un assistant vocal de parapharmacie spécialisé cheveux. "
    "Réponds en français, 2 à 4 phrases max, ton clair et professionnel. "
    "Pas de diagnostic médical, pas de prescription, pas de conseil médical. "
    "Si la question est médicale: 'Je ne peux pas répondre à cette question. "
    "Je vous invite à consulter le pharmacien.'"
)


class OpenAIHTTPFallbackClient:
    # Client de secours via API HTTP (Responses/Chat Completions).

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        temperature: float = 0.4,
    ):
        self.api_key = api_key
        self.model = model
        self.temperature = temperature

    @staticmethod
    def _build_user_prompt(question: str, context: Optional[Dict[str, Any]]) -> str:
        ctx = context or {}
        current_product = (ctx.get("current_product") or "").strip()
        current_ean = (ctx.get("current_ean") or "").strip()
        lines = [f"Question utilisateur: {question.strip()}"]
        if current_product:
            lines.append(f"Produit courant identifié: {current_product}")
        if current_ean:
            lines.append(f"EAN courant: {current_ean}")
        lines.append("Réponds brièvement pour une restitution vocale Pepper.")
        return "\n".join(lines)

    @staticmethod
    def _extract_text_from_response(resp: Any) -> str:
        # SDK récent
        text = getattr(resp, "output_text", "") or ""
        if text:
            return text.strip()

        # Fallback parsing générique
        output = getattr(resp, "output", None)
        if not output:
            return ""
        chunks = []
        for item in output:
            for content in getattr(item, "content", []) or []:
                ctype = getattr(content, "type", "")
                if ctype in ("output_text", "text"):
                    value = getattr(content, "text", "") or ""
                    if value:
                        chunks.append(value)
        return " ".join(chunks).strip()

    def ask(self, question: str, context: Optional[Dict[str, Any]] = None) -> str:
        question = (question or "").strip()
        if not question:
            return "Je n'ai pas reçu de question."

        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        user_prompt = self._build_user_prompt(question, context)

        # Chemin principal: Responses API
        try:
            resp = client.responses.create(
                model=self.model,
                temperature=self.temperature,
                max_output_tokens=220,
                input=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
            answer = self._extract_text_from_response(resp)
            if answer:
                return answer
        except Exception:
            pass

        # Fallback legacy: Chat Completions
        try:
            resp = client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                max_tokens=220,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
            choices = getattr(resp, "choices", []) or []
            if choices:
                content = getattr(choices[0].message, "content", "") or ""
                if content:
                    return content.strip()
        except Exception:
            pass

        return (
            "Je n'arrive pas à générer une réponse pour le moment. "
            "Veuillez réessayer dans quelques instants."
        )

