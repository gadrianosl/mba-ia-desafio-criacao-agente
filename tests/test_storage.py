import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from aurora.storage import ConfirmationConflict, SessionNotFound, Storage


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'aurora.db'
        self.store = Storage(self.path)
        self.store.bind_session('s1', '101')
        self.store.bind_session('s2', '201')

    def test_seed_and_isolation(self):
        self.assertEqual(self.store.reservations('s1')[0]['codigo'], 'RSV-1377')
        self.assertEqual(self.store.visitors('s1'), [])
        self.assertEqual(self.store.cancel('s1', 'RSV-4821')['status'], 'nao_encontrada')
        self.assertEqual(self.store.verification_reservations('302')[0]['codigo'], 'RSV-4821')
        self.assertFalse(self.store.available('salao-de-festas', '2030-03-16'))
        with self.assertRaises(SessionNotFound):
            self.store.reservations('missing')
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.bind_session('s1', '302')
        with sqlite3.connect(self.path) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE sessions SET apartment='302' WHERE id='s1'")

    def test_free_reservation_and_cancel_preserve_code(self):
        result = self.store.reserve('s1', 'quadra', '2030-04-06')
        self.assertEqual(result['status'], 'reservada')
        self.assertEqual(self.store.pending('s1'), [])
        self.store.cancel('s1', result['codigo'])
        other = self.store.reserve('s1', 'quadra', '2030-04-06')
        self.assertNotEqual(result['codigo'], other['codigo'])
        with sqlite3.connect(self.path) as db:
            self.assertIsNotNone(db.execute('SELECT 1 FROM reservation_codes WHERE code=?', (result['codigo'],)).fetchone())
        self.assertEqual(self.store.cancel('s1', 'RSV-1377')['status'], 'cancelada')

    def test_paid_confirmation_denial_approval_and_replay(self):
        pending = self.store.reserve('s1', 'salao-de-festas', '2030-04-20')
        self.assertTrue(self.store.available('salao-de-festas', '2030-04-20'))
        with self.assertRaises(ConfirmationConflict):
            self.store.confirm('s2', pending['id'], True)
        self.store.confirm('s1', pending['id'], False)
        self.assertTrue(self.store.available('salao-de-festas', '2030-04-20'))
        with self.assertRaises(ConfirmationConflict):
            self.store.confirm('s1', pending['id'], True)
        pending = self.store.reserve('s1', 'salao-de-festas', '2030-04-20')
        self.assertEqual(self.store.confirm('s1', pending['id'], True)['status'], 'reservada')
        with self.assertRaises(ConfirmationConflict):
            self.store.confirm('s1', pending['id'], True)
        with self.assertRaises(ConfirmationConflict):
            self.store.confirm('s1', 'missing', True)

    def test_persisted_pending_and_visitors(self):
        pending = self.store.authorize_visitor('s1', 'Joana Ribeiro', '2030-04-21')
        self.assertEqual(self.store.visitors('s1'), [])
        reopened = Storage(self.path)
        self.assertEqual(reopened.pending('s1')[0]['id'], pending['id'])
        reopened.confirm('s1', pending['id'], True)
        self.assertEqual(Storage(self.path).visitors('s1'), [{'nome': 'Joana Ribeiro', 'data': '2030-04-21'}])
        self.assertEqual(Storage(self.path).pending('s1'), [])

    def test_concurrent_approvals_have_one_winner(self):
        ids = [self.store.reserve(session, 'salao-de-festas', '2030-05-11')['id'] for session in ('s1', 's2')]
        barrier = Barrier(2)
        def approve(pair):
            barrier.wait(timeout=5)
            return Storage(self.path).confirm(*pair, True)['status']
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(approve, zip(('s1', 's2'), ids)))
        self.assertCountEqual(outcomes, ['reservada', 'indisponivel'])
        rows = self.store.reservations('s1') + self.store.reservations('s2')
        self.assertEqual(sum(r['area']=='salao-de-festas' and r['data']=='2030-05-11' for r in rows), 1)

    def test_database_constraint_and_reset(self):
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO reservation_codes VALUES ('new-code')")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO reservations VALUES ('new-code','101','quadra','2030-03-09',1)")
        self.store.cancel('s1', 'RSV-1377')
        self.store.reset()
        with self.assertRaises(SessionNotFound):
            self.store.pending('s1')
        self.assertEqual(self.store.verification_reservations('101')[0]['codigo'], 'RSV-1377')
        self.store.reset()
        self.assertEqual(len(self.store.verification_visitors('302')), 1)

    def test_validation(self):
        for day in ('20300420', '2030-02-30'):
            with self.assertRaises(ValueError):
                self.store.reserve('s1', 'quadra', day)
        with self.assertRaises(ValueError):
            self.store.reserve('s1', 'unknown', '2030-04-20')
        with self.assertRaises(ValueError):
            self.store.authorize_visitor('s1', ' ', '2030-04-20')
        pending = self.store.reserve('s1', 'salao-de-festas', '2030-04-20')
        with self.assertRaises(ValueError):
            self.store.confirm('s1', pending['id'], 'true')


if __name__ == '__main__':
    unittest.main()
