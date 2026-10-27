"""API do Residencial Aurora: uv run uvicorn aurora.api:app --port 8000."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from aurora.config import PROJECT_ROOT, load_settings
from aurora.runtime import Runtime
from aurora.storage import ConfirmationConflict, SessionNotFound

RUNTIME_DIRECTORY = PROJECT_ROOT / '.local' / 'runtime'


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class SessionInput(Input):
    apartamento: str = Field(min_length=1)


class MessageInput(Input):
    texto: str = Field(min_length=1)


class ConfirmationInput(Input):
    id: str = Field(min_length=1)
    confirmado: StrictBool


class Pending(BaseModel):
    id: str
    acao: str
    detalhes: dict


class ConversationResponse(BaseModel):
    resposta: str
    confirmacoes_pendentes: list[Pending]


def create_app(directory: Path = RUNTIME_DIRECTORY, *, model=None) -> FastAPI:
    """Injeção de modelo permite testar HTTP/Runner sem chamar o Gemini."""
    @asynccontextmanager
    async def lifespan(app):
        selected_model = model if model is not None else load_settings().gemini_model
        runtime = Runtime(directory, selected_model)
        app.state.runtime = runtime
        try:
            yield
        finally:
            await runtime.close()

    app = FastAPI(title='Assistente do Residencial Aurora', lifespan=lifespan)

    @app.exception_handler(SessionNotFound)
    async def missing_session(request: Request, error: SessionNotFound):
        return JSONResponse(status_code=404, content={'detail': str(error)})

    @app.exception_handler(ConfirmationConflict)
    async def conflicting_confirmation(request: Request, error: ConfirmationConflict):
        return JSONResponse(status_code=409, content={'detail': str(error)})

    @app.post('/sessoes', status_code=201)
    async def create_session(body: SessionInput, request: Request):
        try:
            sid = await request.app.state.runtime.create_session(body.apartamento)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {'session_id': sid}

    @app.post('/sessoes/{session_id}/mensagens', response_model=ConversationResponse)
    async def message(session_id: str, body: MessageInput, request: Request):
        return await request.app.state.runtime.message(session_id, body.texto)

    @app.post('/sessoes/{session_id}/confirmacoes', response_model=ConversationResponse)
    async def confirm(session_id: str, body: ConfirmationInput, request: Request):
        return await request.app.state.runtime.confirm(session_id, body.id, body.confirmado)

    @app.get('/sessoes/{session_id}/eventos')
    async def events(session_id: str, request: Request):
        session = await request.app.state.runtime.session(session_id)
        return [event.model_dump(mode='json') for event in session.events]

    @app.get('/apartamentos/{numero}/reservas')
    async def reservations(numero: str, request: Request):
        return request.app.state.runtime.storage.verification_reservations(numero)

    @app.get('/apartamentos/{numero}/visitantes')
    async def visitors(numero: str, request: Request):
        return request.app.state.runtime.storage.verification_visitors(numero)

    return app


app = create_app()
