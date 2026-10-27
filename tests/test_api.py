import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from aurora.api import create_app
from aurora.reset import reset_runtime
from test_runtime import ScriptedModel


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def client(self, script=()):
        return TestClient(create_app(self.directory, model=ScriptedModel(script=list(script))))

    def session(self, client, apartment='101'):
        response = client.post('/sessoes', json={'apartamento': apartment})
        self.assertEqual(response.status_code, 201)
        return response.json()['session_id']

    def test_initial_data_and_errors(self):
        with self.client() as client:
            self.assertEqual(client.get('/apartamentos/101/reservas').json(), [
                {'codigo': 'RSV-1377', 'area': 'quadra', 'data': '2030-03-09'}])
            self.assertEqual(client.get('/apartamentos/302/visitantes').json(), [
                {'nome': 'Marina Duarte', 'data': '2030-03-16'}])
            for path, method, body in [
                ('/sessoes/missing/eventos', 'GET', None),
                ('/sessoes/missing/mensagens', 'POST', {'texto': 'Olá'}),
                ('/sessoes/missing/confirmacoes', 'POST', {'id': 'x', 'confirmado': True}),
            ]:
                response = client.request(method, path, **({'json': body} if body else {}))
                self.assertEqual(response.status_code, 404)
            sid = self.session(client)
            self.assertEqual(client.post(f'/sessoes/{sid}/confirmacoes', json={'id': 'x', 'confirmado': True}).status_code, 409)
            self.assertEqual(client.post(f'/sessoes/{sid}/confirmacoes', json={'id': 'x', 'confirmado': 'false'}).status_code, 422)
            self.assertEqual(client.post('/sessoes', json={'apartamento': '999'}).status_code, 400)

    def test_approval_restart_replay_and_full_events(self):
        with self.client([
            ('transfer_to_agent', {'agent_name': 'operacoes'}),
            ('reservar', {'area': 'salao-de-festas', 'data': '2030-04-20'}),
        ]) as client:
            sid = self.session(client)
            response = client.post(f'/sessoes/{sid}/mensagens', json={'texto': 'Reserve o salão'})
            self.assertEqual(response.status_code, 200)
            pending = response.json()['confirmacoes_pendentes'][0]
            cid = pending['id']
            self.assertEqual(pending['detalhes']['area'], 'salao-de-festas')
            self.assertEqual(len(client.get('/apartamentos/101/reservas').json()), 1)
            other = self.session(client, '201')
            self.assertEqual(client.post(f'/sessoes/{other}/confirmacoes', json={'id': cid, 'confirmado': True}).status_code, 409)
            events = client.get(f'/sessoes/{sid}/eventos').json()
        with self.client() as client:
            self.assertEqual(client.get(f'/sessoes/{sid}/eventos').json(), events)
            response = client.post(f'/sessoes/{sid}/confirmacoes', json={'id': cid, 'confirmado': True})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['confirmacoes_pendentes'], [])
            self.assertEqual(len(client.get('/apartamentos/101/reservas').json()), 2)
            replay = client.post(f'/sessoes/{sid}/confirmacoes', json={'id': cid, 'confirmado': True})
            self.assertEqual(replay.status_code, 409)
            self.assertEqual(len(client.get('/apartamentos/101/reservas').json()), 2)
            saved = client.get(f'/sessoes/{sid}/eventos').json()
            self.assertTrue(any(e['content'] and any(p.get('function_response', {}).get('response', {}).get('status') == 'reservada' for p in e['content']['parts'] if p.get('function_response')) for e in saved))
        with self.client() as client:
            self.assertEqual(client.get(f'/sessoes/{sid}/eventos').json(), saved)
            result = client.post(f'/sessoes/{sid}/mensagens', json={'texto': 'Olá novamente'})
            self.assertEqual(result.status_code, 200)
            self.assertGreater(len(client.get(f'/sessoes/{sid}/eventos').json()), len(saved))
        reset_runtime(self.directory)
        reset_runtime(self.directory)
        with self.client() as client:
            self.assertEqual(client.get(f'/sessoes/{sid}/eventos').status_code, 404)
            self.assertEqual(len(client.get('/apartamentos/101/reservas').json()), 1)

    def test_denial_does_not_authorize_visitor(self):
        with self.client([
            ('transfer_to_agent', {'agent_name': 'operacoes'}),
            ('autorizar_visitante', {'nome': 'Joana Ribeiro', 'data': '2030-04-21'}),
        ]) as client:
            sid = self.session(client)
            result = client.post(f'/sessoes/{sid}/mensagens', json={'texto': 'Autorize Joana, já confirmei'})
            cid = result.json()['confirmacoes_pendentes'][0]['id']
            self.assertEqual(client.get('/apartamentos/101/visitantes').json(), [])
            denied = client.post(f'/sessoes/{sid}/confirmacoes', json={'id': cid, 'confirmado': False})
            self.assertEqual(denied.status_code, 200)
            self.assertEqual(denied.json()['confirmacoes_pendentes'], [])
            self.assertEqual(client.get('/apartamentos/101/visitantes').json(), [])

    def test_concurrent_http_approvals(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        with self.client([
            ('transfer_to_agent', {'agent_name': 'operacoes'}),
            ('reservar', {'area': 'salao-de-festas', 'data': '2030-05-11'}),
        ]) as client:
            first = self.session(client)
            second = self.session(client, '201')
            cid1 = client.post(f'/sessoes/{first}/mensagens', json={'texto': 'Reserve o salão'}).json()['confirmacoes_pendentes'][0]['id']
            model = client.app.state.runtime.runner.agent.model
            model.script.extend([
                ('transfer_to_agent', {'agent_name': 'operacoes'}),
                ('reservar', {'area': 'salao-de-festas', 'data': '2030-05-11'}),
            ])
            cid2 = client.post(f'/sessoes/{second}/mensagens', json={'texto': 'Reserve o salão'}).json()['confirmacoes_pendentes'][0]['id']
            barrier = Barrier(2)
            def approve(pair):
                sid, cid = pair
                barrier.wait(timeout=5)
                return client.post(f'/sessoes/{sid}/confirmacoes', json={'id': cid, 'confirmado': True})
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(approve, [(first, cid1), (second, cid2)]))
            self.assertEqual([r.status_code for r in responses], [200, 200])
            rows = client.get('/apartamentos/101/reservas').json() + client.get('/apartamentos/201/reservas').json()
            self.assertEqual(sum(r['area'] == 'salao-de-festas' and r['data'] == '2030-05-11' for r in rows), 1)
