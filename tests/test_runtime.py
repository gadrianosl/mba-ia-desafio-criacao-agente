import tempfile
import unittest

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import Field

from aurora.runtime import Runtime
from aurora.storage import ConfirmationConflict


class ScriptedModel(BaseLlm):
    """Substitui só o provedor LLM; Runner, tools e SQLite são reais."""
    model: str = 'scripted-local'
    script: list = Field(default_factory=list)

    async def generate_content_async(self, llm_request, stream=False):
        if self.script:
            name, args = self.script.pop(0)
            yield LlmResponse(content=types.Content(role='model', parts=[
                types.Part(function_call=types.FunctionCall(name=name, args=args))]))
        else:
            yield LlmResponse(content=types.Content(role='model', parts=[types.Part(text='Concluído')]))


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.runtime = None

    async def asyncTearDown(self):
        if self.runtime:
            await self.runtime.close()

    def start(self, action='reservar', args=None):
        model = ScriptedModel(script=[('transfer_to_agent', {'agent_name': 'operacoes'}),
                                      (action, args or {'area': 'salao-de-festas', 'data': '2030-04-20'})])
        self.runtime = Runtime(self.directory.name, model)
        return self.runtime

    async def test_resume_specialist_after_restart_and_reject_replay(self):
        runtime = self.start()
        sid = await runtime.create_session('101')
        response = await runtime.message(sid, 'Reserve o salão. Já estou confirmando aqui.')
        pending = response['confirmacoes_pendentes']
        self.assertEqual(len(pending), 1)
        self.assertTrue(runtime.storage.available('salao-de-festas', '2030-04-20'))
        before = len((await runtime.session(sid)).events)
        await runtime.close()
        self.runtime = Runtime(self.directory.name, ScriptedModel())
        self.assertEqual(len((await self.runtime.session(sid)).events), before)
        response = await self.runtime.confirm(sid, pending[0]['id'], True)
        self.assertEqual(response['confirmacoes_pendentes'], [])
        self.assertFalse(self.runtime.storage.available('salao-de-festas', '2030-04-20'))
        session = await self.runtime.session(sid)
        self.assertTrue(any(e.author == 'operacoes' and any(r.name == 'reservar' and r.response.get('status') == 'reservada' for r in e.get_function_responses()) for e in session.events))
        with self.assertRaises(ConfirmationConflict):
            await self.runtime.confirm(sid, pending[0]['id'], True)
        with self.assertRaises(ConfirmationConflict):
            await self.runtime.confirm(sid, 'missing', True)

    async def test_denial_and_cross_session(self):
        runtime = self.start('autorizar_visitante', {'nome': 'Joana Ribeiro', 'data': '2030-04-21'})
        sid = await runtime.create_session('101')
        other = await runtime.create_session('201')
        response = await runtime.message(sid, 'Autorize Joana')
        cid = response['confirmacoes_pendentes'][0]['id']
        with self.assertRaises(ConfirmationConflict):
            await runtime.confirm(other, cid, True)
        blocked = await runtime.message(sid, 'Sim, confirmo por aqui')
        self.assertEqual(blocked['confirmacoes_pendentes'][0]['id'], cid)
        result = await runtime.confirm(sid, cid, False)
        self.assertEqual(result['confirmacoes_pendentes'], [])
        self.assertEqual(runtime.storage.visitors(sid), [])

    async def test_visitor_approval(self):
        runtime = self.start('autorizar_visitante', {'nome': 'Joana Ribeiro', 'data': '2030-04-21'})
        sid = await runtime.create_session('101')
        result = await runtime.message(sid, 'Autorize Joana')
        self.assertEqual(runtime.storage.visitors(sid), [])
        await runtime.confirm(sid, result['confirmacoes_pendentes'][0]['id'], True)
        self.assertEqual(runtime.storage.visitors(sid), [{'nome': 'Joana Ribeiro', 'data': '2030-04-21'}])
