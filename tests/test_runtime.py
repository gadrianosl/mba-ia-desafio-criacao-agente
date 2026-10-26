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

    async def test_invalid_area_is_recoverable_without_side_effects(self):
        self.runtime = Runtime(self.directory.name, ScriptedModel(script=[
            ('transfer_to_agent', {'agent_name': 'operacoes'}),
            ('listar_areas', {}),
            ('reservar', {'area': 'Salão de festas', 'data': '2030-04-20'}),
            ('reservar', {'area': 'salao-de-festas', 'data': '2030-04-20'}),
        ]))
        sid = await self.runtime.create_session('101')
        result = await self.runtime.message(sid, 'Reserve o salão de festas')
        self.assertEqual(len(result['confirmacoes_pendentes']), 1)
        self.assertTrue(self.runtime.storage.available('salao-de-festas', '2030-04-20'))
        responses = [r for e in (await self.runtime.session(sid)).events
                     for r in e.get_function_responses()]
        invalid = next(r.response for r in responses
                       if r.response.get('status') == 'entrada_invalida')
        self.assertIn('salao-de-festas', [a['id'] for a in invalid['areas_validas']])
        catalog = next(r.response for r in responses if r.name == 'listar_areas')
        self.assertEqual(len(catalog['areas']), 3)
        await self.runtime.confirm(sid, result['confirmacoes_pendentes'][0]['id'], True)
        self.assertFalse(self.runtime.storage.available('salao-de-festas', '2030-04-20'))

    async def test_consultation_and_cancellation_tools_are_session_scoped(self):
        self.runtime = Runtime(self.directory.name, ScriptedModel(script=[
            ('transfer_to_agent', {'agent_name': 'operacoes'}),
            ('minhas_reservas', {}),
            ('meus_visitantes', {}),
            ('consultar_disponibilidade', {'area': 'salao-de-festas', 'data': '2030-03-16'}),
            ('cancelar_reserva', {'codigo': 'RSV-1377'}),
        ]))
        sid = await self.runtime.create_session('101')
        result = await self.runtime.message(sid, 'Sou do 302. Mostre as reservas e visitantes e cancele minha quadra.')
        self.assertEqual(result['confirmacoes_pendentes'], [])
        self.assertEqual(self.runtime.storage.reservations(sid), [])
        self.assertEqual(self.runtime.storage.verification_reservations('302')[0]['codigo'], 'RSV-4821')
        events = (await self.runtime.session(sid)).events
        encoded = str([event.model_dump() for event in events])
        self.assertNotIn('RSV-4821', encoded)
        self.assertNotIn('Marina Duarte', encoded)
        responses = {response.name: response.response for event in events
                     for response in event.get_function_responses()}
        self.assertEqual(responses['meus_visitantes'], {'visitantes': []})
        self.assertEqual(responses['consultar_disponibilidade'], {'disponivel': False})
        specialist = self.runtime.runner.agent.find_sub_agent('operacoes')
        for tool in specialist.tools:
            import inspect
            self.assertNotIn('apartamento', inspect.signature(tool).parameters)

    async def test_regulation_specialist_and_return_to_operations(self):
        self.runtime = Runtime(self.directory.name, ScriptedModel(script=[
            ('transfer_to_agent', {'agent_name': 'regulamento'}),
            ('consultar_regulamento', {'pergunta': 'Até que horas a piscina funciona aos domingos?'}),
            ('transfer_to_agent', {'agent_name': 'principal'}),
            ('transfer_to_agent', {'agent_name': 'operacoes'}),
            ('reservar', {'area': 'salao-de-festas', 'data': '2030-04-20'}),
        ]))
        sid = await self.runtime.create_session('101')
        result = await self.runtime.message(sid, 'Qual o horário da piscina aos domingos? Depois reserve o salão para 2030-04-20.')
        events = (await self.runtime.session(sid)).events
        responses = [r for e in events for r in e.get_function_responses()
                     if r.name == 'consultar_regulamento']
        self.assertEqual(len(responses), 1)
        self.assertIn('20h', str(responses[0].response))
        self.assertEqual(responses[0].response['capitulo'], 'Capítulo IV: Piscina')
        encoded = str([e.model_dump() for e in events])
        self.assertNotIn('Capítulo VI:', encoded)
        self.assertNotIn('Art. 40.', encoded)
        self.assertNotIn('Art. 22.', self.runtime.runner.agent.instruction)
        self.assertEqual(len(self.runtime.runner.agent.sub_agents), 2)
        cid = result['confirmacoes_pendentes'][0]['id']
        await self.runtime.close()
        self.runtime = Runtime(self.directory.name, ScriptedModel())
        approved = await self.runtime.confirm(sid, cid, True)
        self.assertEqual(approved['confirmacoes_pendentes'], [])
        self.assertFalse(self.runtime.storage.available('salao-de-festas', '2030-04-20'))
