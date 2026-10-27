"""Provedor determinístico do roteiro; não avalia compreensão pelo Gemini.

As decisões abaixo são fixtures de teste. O sistema de produção não importa
este módulo. Runner, HTTP, tools e bancos usados pelo roteiro são reais.
"""
import re

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types


class AcceptanceModel(BaseLlm):
    model: str = 'acceptance-fixture'

    async def generate_content_async(self, llm_request, stream=False):
        contents = llm_request.contents
        latest_user = next((c for c in reversed(contents) if c.role == 'user'
                            and any(p.text for p in c.parts)
                            and not any(p.text and p.text.startswith('For context:') for p in c.parts)), None)
        text = ' '.join(p.text for p in latest_user.parts if p.text) if latest_user else ''
        lower = text.lower()
        # Cada execução do roteiro tem um único pedido por mensagem.
        last = contents[-1]
        responses = [p.function_response for p in last.parts if p.function_response]
        tools = llm_request.tools_dict
        if responses and any(r.name != 'transfer_to_agent' for r in responses):
            answer = 'A piscina fecha às 20h aos domingos (Art. 22, II).' if 'piscina' in lower else 'Operação consultada; verifique o resultado da tool.'
            yield LlmResponse(content=types.Content(role='model', parts=[types.Part(text=answer)]))
            return
        target = 'regulamento' if 'piscina' in lower else 'operacoes'
        if (target == 'regulamento' and 'consultar_regulamento' not in tools) or (target == 'operacoes' and 'reservar' not in tools):
            # Especialistas retornam ao principal antes de trocar de assunto.
            agent_name = target if 'reservar' not in tools and 'consultar_regulamento' not in tools else 'principal'
            name, args = 'transfer_to_agent', {'agent_name': agent_name}
        elif 'piscina' in lower:
            name, args = 'consultar_regulamento', {'pergunta': text}
        elif 'quais' in lower:
            name, args = 'minhas_reservas', {}
        elif 'cancele' in lower:
            # Fixtures têm códigos conhecidos; a produção obtém códigos via tools.
            name, args = 'cancelar_reserva', {'codigo': 'RSV-1377'}
            if '2030-03-16' in lower:
                # Nenhum código de outro morador entra no contexto da sessão.
                name, args = 'minhas_reservas', {}
        elif 'joana' in lower:
            name, args = 'autorizar_visitante', {'nome': 'Joana Ribeiro', 'data': '2030-04-21'}
        elif 'reserve' in lower:
            day = re.search(r'\d{4}-\d{2}-\d{2}', text).group()
            name, args = 'reservar', {'area': 'quadra' if 'quadra' in lower else 'salao-de-festas', 'data': day}
        else:
            raise AssertionError('Mensagem não prevista na fixture de aceitação')
        yield LlmResponse(content=types.Content(role='model', parts=[
            types.Part(function_call=types.FunctionCall(name=name, args=args))]))
