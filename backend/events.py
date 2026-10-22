"""One local SQLite store; committed rows are the event stream's source of truth."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

from backend.app.contracts import Alert, Run, Trace


def utcnow():
    return datetime.now(timezone.utc)


class EventStore:
    def __init__(self, path: Path, data_mode='sample'):
        self.path, self.data_mode = path, data_mode
        self.clock_id = str(uuid4())
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS run_clocks (
                    run_id TEXT PRIMARY KEY REFERENCES runs(id), origin TEXT NOT NULL, started REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS traces (
                    run_id TEXT NOT NULL REFERENCES runs(id), seq INTEGER NOT NULL,
                    body TEXT NOT NULL, PRIMARY KEY(run_id, seq));
                CREATE TABLE IF NOT EXISTS alerts (
                    cursor INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
                    run_id TEXT NOT NULL REFERENCES runs(id), body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS receipts (
                    alert_id TEXT NOT NULL REFERENCES alerts(id), client_id TEXT NOT NULL,
                    body TEXT NOT NULL, PRIMARY KEY(alert_id, client_id));
            ''')

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            if write:
                db.commit()
        except BaseException:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    def create_run(self, run: Run):
        if run.data_mode != self.data_mode:
            raise ValueError('run data mode differs from store')
        with self.connection(write=True) as db:
            db.execute('INSERT INTO runs VALUES (?, ?)', (run.id, run.model_dump_json()))
            db.execute('INSERT INTO run_clocks VALUES (?,?,?)', (run.id, self.clock_id, time.monotonic()))
        return run

    def get_run(self, run_id):
        with self.connection() as db:
            row = db.execute('SELECT body FROM runs WHERE id=?', (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return Run.model_validate_json(row['body'])

    def list_runs(self, limit=100):
        with self.connection() as db:
            return [json.loads(r['body']) for r in db.execute('SELECT body FROM runs ORDER BY rowid DESC LIMIT ?', (limit,))]

    def _trace(self, db, run_id, sim_ts, kind, payload, agent='system', **metrics):
        row = db.execute('SELECT body FROM runs WHERE id=?', (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        run = Run.model_validate_json(row['body'])
        seq = db.execute('SELECT COALESCE(MAX(seq),0)+1 FROM traces WHERE run_id=?', (run_id,)).fetchone()[0]
        trace = Trace(run_id=run_id, scenario_id=run.scenario_id, seq=seq, wall_ts=utcnow(),
                      sim_ts=sim_ts, kind=kind, payload=payload, agent=agent, **metrics)
        db.execute('INSERT INTO traces VALUES (?,?,?)', (run_id, seq, trace.model_dump_json()))
        return trace

    def append_trace(self, run_id, sim_ts, kind, payload, agent='system', **metrics):
        with self.connection(write=True) as db:
            return self._trace(db, run_id, sim_ts, kind, payload, agent, **metrics)

    def traces(self, run_id, after=0, limit=100):
        with self.connection() as db:
            return [json.loads(r['body']) for r in db.execute(
                'SELECT body FROM traces WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?', (run_id, after, limit))]

    def create_alert(self, alert: Alert, sim_ts):
        with self.connection(write=True) as db:
            db.execute('INSERT INTO alerts(id,run_id,body) VALUES (?,?,?)',
                       (alert.id, alert.run_id, alert.model_dump_json()))
            self._trace(db, alert.run_id, sim_ts, 'alert', alert.model_dump(mode='json'))
        return alert

    def alerts(self, after=0, limit=100, recent=False):
        with self.connection() as db:
            order = 'DESC' if recent else 'ASC'
            return [{'cursor': r['cursor'], **json.loads(r['body']),
                     'sim_ts': json.loads(r['trace'])['sim_ts'] if r['trace'] else json.loads(r['body'])['created_at']}
                    for r in db.execute(f'''SELECT a.cursor,a.body,t.body AS trace FROM alerts a
                        LEFT JOIN traces t ON t.run_id=a.run_id AND t.seq=1
                        WHERE a.cursor>? ORDER BY a.cursor {order} LIMIT ?''', (after, limit))]

    def receipt(self, alert_id, client_id, browser_received_at, sim_ts):
        with self.connection(write=True) as db:
            existing = db.execute('SELECT body FROM receipts WHERE alert_id=? AND client_id=?',
                                  (alert_id, client_id)).fetchone()
            if existing:
                return json.loads(existing['body'])
            row = db.execute('SELECT body FROM alerts WHERE id=?', (alert_id,)).fetchone()
            if row is None:
                raise KeyError(alert_id)
            alert = Alert.model_validate_json(row['body'])
            now = utcnow()
            clock = db.execute('SELECT origin,started FROM run_clocks WHERE run_id=?', (alert.run_id,)).fetchone()
            elapsed = (time.monotonic() - clock['started']) * 1000 if clock and clock['origin'] == self.clock_id else None
            receipt = {'alert_id': alert_id, 'client_id': client_id, 'run_to_receipt_ms': elapsed,
                       'clock_id': self.clock_id,
                       'browser_received_at': browser_received_at.isoformat(), 'server_received_at': now.isoformat()}
            db.execute('INSERT INTO receipts VALUES (?,?,?)', (alert_id, client_id, json.dumps(receipt)))
            if alert.status == 'created':
                alert = Alert.model_validate({**alert.model_dump(), 'status': 'received', 'received_at': now})
                db.execute('UPDATE alerts SET body=? WHERE id=?', (alert.model_dump_json(), alert_id))
            self._trace(db, alert.run_id, sim_ts, 'received', receipt)
        return receipt

    def acknowledge(self, alert_id, client_id, operator, sim_ts):
        with self.connection(write=True) as db:
            row = db.execute('SELECT body FROM alerts WHERE id=?', (alert_id,)).fetchone()
            if row is None:
                raise KeyError(alert_id)
            alert = Alert.model_validate_json(row['body'])
            if not db.execute('SELECT 1 FROM receipts WHERE alert_id=? AND client_id=?', (alert_id, client_id)).fetchone():
                raise ValueError('this client must record receipt before acknowledgement')
            if alert.status == 'acknowledged':
                return alert
            alert = Alert.model_validate({**alert.model_dump(), 'status': 'acknowledged', 'acknowledged_at': utcnow()})
            db.execute('UPDATE alerts SET body=? WHERE id=?', (alert.model_dump_json(), alert_id))
            self._trace(db, alert.run_id, sim_ts, 'acknowledged',
                        {'alert_id': alert_id, 'client_id': client_id, 'operator': operator})
        return alert
