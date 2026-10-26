"""Confirmação nativa do ADK com efeitos protegidos pela camada de negócio.

A interface pública aceita texto ou um ID + booleano. Nunca recebe conteúdos
FunctionResponse arbitrários nem um apartamento escolhido pelo modelo.
"""

import asyncio
from pathlib import Path
from uuid import uuid4

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from google.adk.tools import ToolContext
from google.genai import types

from aurora.storage import ConfirmationConflict, SessionNotFound, Storage

APP_NAME = 'aurora'
USER_ID = 'resident'
CONFIRMATION = 'adk_request_confirmation'


def build_agent(storage, model):
    def finish_or_request(tool_context, create):
        session_id = tool_context.session.id
        confirmation = tool_context.tool_confirmation
        if confirmation is not None:
            # O runtime copia o payload persistido; o cliente envia só ID/booleano.
            return storage.confirm(session_id, confirmation.payload['business_id'],
                                   confirmation.confirmed)
        result = create(session_id)
        if result['status'] == 'pendente':
            tool_context.request_confirmation(
                hint='Aprovação obrigatória pela interface de confirmações.',
                payload={'business_id': result['id']})
            tool_context.actions.skip_summarization = True
        return result

    def reservar(area: str, data: str, tool_context: ToolContext) -> dict:
        """Solicita uma reserva; áreas pagas exigem confirmação do sistema."""
        return finish_or_request(tool_context, lambda sid: storage.reserve(sid, area, data))

    def autorizar_visitante(nome: str, data: str, tool_context: ToolContext) -> dict:
        """Solicita autorização; nunca libera entrada sem confirmação do sistema."""
        return finish_or_request(tool_context, lambda sid: storage.authorize_visitor(sid, nome, data))

    specialist = Agent(
        name='operacoes', model=model,
        description='Especialista em reservas e autorização de visitantes.',
        instruction='Use as tools para reservas e visitantes. Confirmação somente pelo sistema. Não invente resultados.',
        tools=[reservar, autorizar_visitante],
        disallow_transfer_to_parent=False,
        disallow_transfer_to_peers=True,
    )
    return Agent(
        name='principal', model=model,
        instruction='Encaminhe pedidos de reservas e visitantes ao especialista operacoes.',
        sub_agents=[specialist],
    )


class Runtime:
    def __init__(self, directory, model):
        directory = Path(directory).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        self.storage = Storage(directory / 'business.sqlite3')
        self.sessions = DatabaseSessionService(
            db_url=f'sqlite+aiosqlite:///{directory / "sessions.sqlite3"}')
        self.runner = Runner(
            # Sem resumability_config: a confirmação usa o histórico persistido.
            # O especialista permite retorno ao pai para o roteador reconhecê-lo.
            app=App(name=APP_NAME, root_agent=build_agent(self.storage, model)),
            session_service=self.sessions)
        self._locks = {}

    async def close(self):
        await self.sessions.close()

    async def create_session(self, apartment):
        sid = str(uuid4())
        self.storage.bind_session(sid, apartment)
        await self.sessions.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=sid)
        return sid

    async def session(self, sid):
        session = await self.sessions.get_session(app_name=APP_NAME, user_id=USER_ID, session_id=sid)
        if session is None:
            raise SessionNotFound('Sessão inexistente')
        return session

    async def pending(self, sid):
        session = await self.session(sid)
        business = {p['id']: p for p in self.storage.pending(sid)}
        result = []
        for event in session.events:
            for call in event.get_function_calls():
                if call.name != CONFIRMATION:
                    continue
                payload = call.args['toolConfirmation'].get('payload', {})
                item = business.get(payload.get('business_id'))
                if item:
                    result.append({**item, 'id': call.id})
        return result

    async def _run(self, sid, content):
        events = [e async for e in self.runner.run_async(
            user_id=USER_ID, session_id=sid, new_message=content)]
        texts = [part.text for event in events if event.content
                 for part in event.content.parts if part.text and event.author != 'user']
        return {'resposta': '\n'.join(texts), 'confirmacoes_pendentes': await self.pending(sid)}

    async def message(self, sid, text):
        async with self._locks.setdefault(sid, asyncio.Lock()):
            await self.session(sid)
            if await self.pending(sid):
                return {'resposta': 'Responda à confirmação pendente pela interface de confirmações.',
                        'confirmacoes_pendentes': await self.pending(sid)}
            return await self._run(sid, types.Content(role='user', parts=[types.Part(text=text)]))

    async def confirm(self, sid, confirmation_id, approved):
        if type(approved) is not bool:
            raise ValueError('Confirmação deve ser booleana')
        async with self._locks.setdefault(sid, asyncio.Lock()):
            if confirmation_id not in {p['id'] for p in await self.pending(sid)}:
                raise ConfirmationConflict('Confirmação não está pendente nesta sessão')
            session = await self.session(sid)
            call = next(call for event in session.events for call in event.get_function_calls()
                        if call.id == confirmation_id and call.name == CONFIRMATION)
            confirmation = dict(call.args['toolConfirmation'])
            confirmation['confirmed'] = approved
            response = types.FunctionResponse(id=confirmation_id, name=CONFIRMATION, response=confirmation)
            return await self._run(sid, types.Content(role='user', parts=[types.Part(function_response=response)]))
