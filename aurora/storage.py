"""Persistência das regras de negócio; as tools recebem apenas o ID da sessão.

Sessões aqui guardam a identidade imutável. O histórico do ADK será integrado
separadamente; esta camada não simula eventos ou confirmações do Runner.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE = ROOT / '.local' / 'aurora.sqlite3'


class SessionNotFound(ValueError):
    pass


class ConfirmationConflict(ValueError):
    pass


class Storage:
    def __init__(self, path=DEFAULT_DATABASE):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS apartments (
                    number TEXT PRIMARY KEY, resident TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS areas (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    fee REAL NOT NULL CHECK(fee >= 0));
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    apartment TEXT NOT NULL REFERENCES apartments(number));
                CREATE TRIGGER IF NOT EXISTS immutable_session_apartment
                    BEFORE UPDATE OF apartment ON sessions
                    BEGIN SELECT RAISE(ABORT, 'immutable apartment'); END;
                CREATE TABLE IF NOT EXISTS reservation_codes (
                    code TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS reservations (
                    code TEXT PRIMARY KEY REFERENCES reservation_codes(code),
                    apartment TEXT NOT NULL REFERENCES apartments(number),
                    area TEXT NOT NULL REFERENCES areas(id),
                    day TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)));
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_reservation
                    ON reservations(area, day) WHERE active = 1;
                CREATE TABLE IF NOT EXISTS visitors (
                    id INTEGER PRIMARY KEY,
                    apartment TEXT NOT NULL REFERENCES apartments(number),
                    name TEXT NOT NULL, day TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS confirmations (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    action TEXT NOT NULL CHECK(action IN ('reserve','visit')),
                    details TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending','approved','denied')));
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')
        with self._transaction() as db:
            if not db.execute("SELECT 1 FROM metadata WHERE key='seeded'").fetchone():
                self._seed(db)

    @contextmanager
    def _transaction(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _seed(self, db):
        def data(name):
            return json.loads((ROOT / 'dados' / f'{name}.json').read_text())
        for row in data('apartamentos'):
            db.execute('INSERT OR REPLACE INTO apartments VALUES (?,?)',
                       (row['numero'], row['morador']))
        for row in data('areas'):
            db.execute('INSERT OR REPLACE INTO areas VALUES (?,?,?)',
                       (row['id'], row['nome'], row['taxa']))
        for row in data('reservas'):
            db.execute('INSERT OR IGNORE INTO reservation_codes VALUES (?)', (row['codigo'],))
            db.execute('INSERT INTO reservations VALUES (?,?,?,?,1)',
                       (row['codigo'], row['apartamento'], row['area'], row['data']))
        for row in data('visitantes'):
            db.execute('INSERT INTO visitors(apartment,name,day) VALUES (?,?,?)',
                       (row['apartamento'], row['nome'], row['data']))
        db.execute("INSERT OR REPLACE INTO metadata VALUES ('seeded','1')")

    def reset(self):
        """Restaura os dados iniciais e apaga vínculos e pendências de sessões.

        O registro de códigos permanece para impedir sua reutilização.
        Não execute enquanto a aplicação estiver atendendo requisições.
        """
        with self._transaction() as db:
            for table in ('confirmations', 'sessions', 'visitors', 'reservations'):
                db.execute(f'DELETE FROM {table}')
            self._seed(db)

    def bind_session(self, session_id, apartment):
        """Somente a camada de criação de sessão deve chamar este método."""
        if not session_id:
            raise ValueError('Sessão inválida')
        with self._transaction() as db:
            if not db.execute('SELECT 1 FROM apartments WHERE number=?', (apartment,)).fetchone():
                raise ValueError('Apartamento inválido')
            db.execute('INSERT INTO sessions VALUES (?,?)', (session_id, apartment))

    @staticmethod
    def _apartment(db, session_id):
        row = db.execute('SELECT apartment FROM sessions WHERE id=?', (session_id,)).fetchone()
        if row is None:
            raise SessionNotFound('Sessão inexistente')
        return row['apartment']

    @staticmethod
    def _day(value):
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError('Use data no formato AAAA-MM-DD')
        return value

    def reservations(self, session_id):
        with self._transaction() as db:
            apartment = self._apartment(db, session_id)
            return self._reservations(db, apartment)

    @staticmethod
    def _reservations(db, apartment):
        return [dict(r) for r in db.execute(
            'SELECT code AS codigo, area, day AS data FROM reservations '
            'WHERE apartment=? AND active=1 ORDER BY day,code', (apartment,))]

    def visitors(self, session_id):
        with self._transaction() as db:
            apartment = self._apartment(db, session_id)
            return self._visitors(db, apartment)

    @staticmethod
    def _visitors(db, apartment):
        return [dict(r) for r in db.execute(
            'SELECT name AS nome, day AS data FROM visitors '
            'WHERE apartment=? ORDER BY day,id', (apartment,))]

    def verification_reservations(self, apartment):
        """Leitura administrativa para a API de verificação; não expor como tool."""
        with self._transaction() as db:
            return self._reservations(db, apartment)

    def verification_visitors(self, apartment):
        """Leitura administrativa para a API de verificação; não expor como tool."""
        with self._transaction() as db:
            return self._visitors(db, apartment)

    def available(self, area, day):
        day = self._day(day)
        with self._transaction() as db:
            if not db.execute('SELECT 1 FROM areas WHERE id=?', (area,)).fetchone():
                raise ValueError('Área inválida')
            return not db.execute('SELECT 1 FROM reservations WHERE area=? AND day=? AND active=1',
                                  (area, day)).fetchone()

    @staticmethod
    def _pending(db, session_id, action, details):
        confirmation_id = str(uuid4())
        db.execute('INSERT INTO confirmations(id,session_id,action,details) VALUES (?,?,?,?)',
                   (confirmation_id, session_id, action, json.dumps(details)))
        return {'status': 'pendente', 'id': confirmation_id}

    def reserve(self, session_id, area, day):
        day = self._day(day)
        with self._transaction() as db:
            apartment = self._apartment(db, session_id)
            row = db.execute('SELECT fee FROM areas WHERE id=?', (area,)).fetchone()
            if row is None:
                raise ValueError('Área inválida')
            if row['fee'] > 0:
                return self._pending(db, session_id, 'reserve',
                                     {'area': area, 'data': day, 'taxa': row['fee']})
            return self._insert_reservation(db, apartment, area, day)

    @staticmethod
    def _insert_reservation(db, apartment, area, day):
        # A exclusividade é decidida pelo índice UNIQUE, na mesma transação.
        while True:
            code = 'RSV-' + uuid4().hex
            if db.execute('INSERT OR IGNORE INTO reservation_codes VALUES (?)', (code,)).rowcount:
                break
        try:
            db.execute('INSERT INTO reservations VALUES (?,?,?,?,1)', (code, apartment, area, day))
        except sqlite3.IntegrityError as error:
            if 'reservations.area, reservations.day' not in str(error):
                raise
            return {'status': 'indisponivel'}
        return {'status': 'reservada', 'codigo': code, 'area': area, 'data': day}

    def cancel(self, session_id, code):
        with self._transaction() as db:
            apartment = self._apartment(db, session_id)
            changed = db.execute('UPDATE reservations SET active=0 '
                                 'WHERE code=? AND apartment=? AND active=1', (code, apartment)).rowcount
            return {'status': 'cancelada' if changed else 'nao_encontrada'}

    def authorize_visitor(self, session_id, name, day):
        day = self._day(day)
        name = name.strip()
        if not name:
            raise ValueError('Nome obrigatório')
        with self._transaction() as db:
            self._apartment(db, session_id)
            return self._pending(db, session_id, 'visit', {'nome': name, 'data': day})

    def pending(self, session_id):
        with self._transaction() as db:
            self._apartment(db, session_id)
            return [{'id': r['id'], 'acao': r['action'], 'detalhes': json.loads(r['details'])}
                    for r in db.execute("SELECT * FROM confirmations WHERE session_id=? AND status='pending' ORDER BY rowid", (session_id,))]

    def confirm(self, session_id, confirmation_id, approved):
        """Chamar somente pela rota de confirmação, nunca disponibilizar ao modelo."""
        if type(approved) is not bool:
            raise ValueError('Confirmação deve ser booleana')
        with self._transaction() as db:
            apartment = self._apartment(db, session_id)
            row = db.execute("SELECT * FROM confirmations WHERE id=? AND session_id=? AND status='pending'",
                             (confirmation_id, session_id)).fetchone()
            if row is None:
                raise ConfirmationConflict('Confirmação não está pendente nesta sessão')
            db.execute('UPDATE confirmations SET status=? WHERE id=?',
                       ('approved' if approved else 'denied', confirmation_id))
            if not approved:
                return {'status': 'negada'}
            details = json.loads(row['details'])
            if row['action'] == 'reserve':
                return self._insert_reservation(db, apartment, details['area'], details['data'])
            db.execute('INSERT INTO visitors(apartment,name,day) VALUES (?,?,?)',
                       (apartment, details['nome'], details['data']))
            return {'status': 'autorizada'}
