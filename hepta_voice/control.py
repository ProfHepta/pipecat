"""Small, provider-independent session/side-effect boundaries.
External side effects are intentionally NOT implemented by this local baseline.
"""
from __future__ import annotations
import hashlib
import json
import re
import sqlite3
import threading
import time
from pathlib import Path

class Rejected(ValueError):
    pass

def checked_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,96}', value):
        raise Rejected('invalid_request_id')
    return value

class Epoch:
    """Invalidate ALL late output, not just the LLM coroutine."""
    def __init__(self):
        self.value = 0
        self.stop = threading.Event()
    def advance(self):
        self.stop.set()
        self.stop = threading.Event()
        self.value += 1
        return self.value, self.stop
    def valid(self, value):
        return self.value == value and not self.stop.is_set()

class Ledger:
    """Durable deduplication; exactly-once applies ONLY to our SQLite note tool.
    A crashed conversational request is UNKNOWN, never automatically retried.
    """
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path, timeout=5, isolation_level=None)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS requests (
          id TEXT PRIMARY KEY, digest TEXT NOT NULL, kind TEXT NOT NULL,
          status TEXT NOT NULL, result TEXT, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS notes (
          id TEXT PRIMARY KEY, text TEXT NOT NULL, created REAL NOT NULL);
        ''')
        self.db.execute("UPDATE requests SET status='unknown' WHERE status='pending'")
    @staticmethod
    def digest(payload):
        return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    def reserve(self, rid, kind, payload):
        checked_id(rid)
        digest = self.digest({'kind':kind,'payload':payload})
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.db.execute('SELECT digest,status,result FROM requests WHERE id=?',(rid,)).fetchone()
            if row:
                if row[0] != digest: raise Rejected('request_identity_conflict')
                result = {'status':row[1], 'duplicate':True, 'result':json.loads(row[2]) if row[2] else None}
            else:
                self.db.execute('INSERT INTO requests VALUES (?,?,?,?,?,?)',(rid,digest,kind,'pending',None,time.time()))
                result = {'status':'pending','duplicate':False}
            self.db.execute('COMMIT'); return result
        except BaseException:
            self.db.execute('ROLLBACK'); raise
    def finish(self, rid, status, result=None):
        if status not in ('done','interrupted','failed','unknown'):raise Rejected('invalid_status')
        self.db.execute('UPDATE requests SET status=?,result=? WHERE id=? AND status=?',
                        (status,json.dumps(result,ensure_ascii=False) if result else None,rid,'pending'))
    def local_note(self, rid, text):
        checked_id(rid)
        if not isinstance(text,str) or not 1 <= len(text.strip()) <= 500:raise Rejected('invalid_note')
        digest = self.digest({'kind':'local_note','text':text})
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row=self.db.execute('SELECT digest,status,result FROM requests WHERE id=?',(rid,)).fetchone()
            if row:
                if row[0] != digest:raise Rejected('request_identity_conflict')
                if row[1]!='done':raise Rejected('unresolved_prior_result')
                result={**json.loads(row[2]),'duplicate':True}
            else:
                now=time.time()
                # The effect and receipt commit atomically in the SAME database.
                self.db.execute('INSERT INTO notes VALUES (?,?,?)',(rid,text,now))
                result={'note_id':rid,'status':'saved_locally','external_action':False}
                self.db.execute('INSERT INTO requests VALUES (?,?,?,?,?,?)',
                                (rid,digest,'local_note','done',json.dumps(result),now))
            self.db.execute('COMMIT');return result
        except BaseException:
            self.db.execute('ROLLBACK');raise
    def count_notes(self):return self.db.execute('SELECT count(*) FROM notes').fetchone()[0]
    def close(self):self.db.close()

def split_clause(buffer: str, final=False):
    """Never narrate thought/tool syntax; low-latency phrase boundary."""
    for i,c in enumerate(buffer):
        if c in '。！？!?\n；;' or (c in '，,' and i>=5):
            return buffer[:i+1].strip(),buffer[i+1:]
    if len(buffer)>=40:return buffer[:40],buffer[40:]
    if final:return buffer.strip(),''
    return '',buffer
