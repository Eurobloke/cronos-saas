# -*- coding: utf-8 -*-
import json
import os
import re
from datetime import date

import requests

ANTHROPIC_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://localhost:11434/api/chat')
OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'qwen2.5:7b')

BOTS_DISPONIBLES = """
BOTS DISPONIBLES:
- HOROSCOPO: videos de astrología y signos del zodiaco (costo: 20 créditos)
- MOTIVACION: videos motivacionales y frases de éxito (costo: 15 créditos)
- NOTICIAS_RD: videos de noticias dominicanas (costo: 10 créditos)
"""

# Prompt más corto y directo para modelos pequeños
SYSTEM_PROMPT = """Eres Cronos, asistente de la plataforma Cronos AI para creadores de contenido en YouTube.

REGLAS ESTRICTAS:
1. Siempre responde en español
2. Responde ÚNICAMENTE con un objeto JSON válido, sin texto adicional
3. Usa EXACTAMENTE uno de estos dos formatos:

Para ejecutar un bot:
{{"type":"action","bot":"NOMBRE_BOT","params":{{}},"message":"Descripción breve de lo que harás"}}

Para responder sin ejecutar:
{{"type":"message","content":"Tu respuesta aquí"}}

EJEMPLOS:
Usuario: "crea el horóscopo de hoy"
Respuesta: {{"type":"action","bot":"HOROSCOPO","params":{{"fecha":"{fecha_hoy}","signos":"todos"}},"message":"Voy a crear el horóscopo completo para los 12 signos de hoy."}}

Usuario: "haz un video motivacional"
Respuesta: {{"type":"action","bot":"MOTIVACION","params":{{"categoria":"exito"}},"message":"Voy a crear un video motivacional sobre el éxito."}}

Usuario: "¿qué puedes hacer?"
Respuesta: {{"type":"message","content":"Puedo crear videos de horóscopo, motivación y noticias para tu canal de YouTube."}}

{bots_info}

PERFIL DEL CANAL:
{niche_context}

FECHA HOY: {fecha_hoy}

IMPORTANTE: Solo responde con JSON. Nada más."""


def _parse_response(text: str) -> dict:
    """Extrae el JSON de la respuesta del LLM y valida que tenga el formato correcto."""
    text = text.strip()
    # Limpiar bloques de código markdown
    text = re.sub(r'```(?:json)?\s*', '', text).strip()
    text = re.sub(r'```\s*$', '', text).strip()

    # Buscar bloque JSON
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group())
            # Validar que tenga la clave "type"
            if 'type' in parsed:
                return parsed
            # Si el modelo devolvió JSON pero sin "type", tratarlo como mensaje
            return {"type": "message", "content": "Entendido. ¿Qué contenido quieres crear hoy?"}
        except json.JSONDecodeError:
            pass

    # Sin JSON válido → tratar como mensaje de texto
    return {"type": "message", "content": text or "¿En qué puedo ayudarte?"}


def _call_anthropic(messages: list, niche_context: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    system = SYSTEM_PROMPT.format(
        niche_context=niche_context,
        bots_info=BOTS_DISPONIBLES,
        fecha_hoy=date.today().strftime('%Y-%m-%d'),
    )
    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=512,
        system=system,
        messages=messages,
    )
    return response.content[0].text


def _call_ollama(messages: list, niche_context: str) -> str:
    system = SYSTEM_PROMPT.format(
        niche_context=niche_context,
        bots_info=BOTS_DISPONIBLES,
        fecha_hoy=date.today().strftime('%Y-%m-%d'),
    )
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "system", "content": system}] + messages,
        "stream": False,
        "options": {
            "temperature": 0.1,  # Más determinista para seguir instrucciones
            "num_predict": 256,
        }
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()['message']['content']


def process_message(user_message: str, history: list, niche_context: str) -> dict:
    messages = history + [{"role": "user", "content": user_message}]
    try:
        if ANTHROPIC_KEY:
            raw_text = _call_anthropic(messages, niche_context)
        else:
            raw_text = _call_ollama(messages, niche_context)
    except Exception as exc:
        return {"type": "message", "content": f"Error al contactar la IA: {exc}"}
    return _parse_response(raw_text)
