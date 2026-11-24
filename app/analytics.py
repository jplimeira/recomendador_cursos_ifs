"""Contadores anônimos opcionais: não armazena textos, IPs ou identificadores."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

class AnonymousMetrics:
    def __init__(self, db_path):
        self.db_path = str(db_path)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path, timeout=5) as db:
            db.execute('CREATE TABLE IF NOT EXISTS daily_metrics (day TEXT PRIMARY KEY, searches INTEGER NOT NULL DEFAULT 0)')

    def record_search(self):
        day = datetime.now(timezone.utc).date().isoformat()
        with sqlite3.connect(self.db_path, timeout=5) as db:
            db.execute('INSERT INTO daily_metrics(day, searches) VALUES (?, 1) ON CONFLICT(day) DO UPDATE SET searches = searches + 1', (day,))
