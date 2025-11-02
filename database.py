import sqlite3
from datetime import datetime
import json


class Database:
    def __init__(self, db_path='trading.db'):
        self.db_path = db_path
        self.init_database()
    
    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_database(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                trade_type TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL,
                stop_loss REAL,
                target REAL,
                quantity INTEGER NOT NULL,
                entry_time TIMESTAMP NOT NULL,
                exit_time TIMESTAMP,
                pnl REAL,
                pnl_percent REAL,
                status TEXT DEFAULT 'OPEN',
                exit_reason TEXT,
                order_id TEXT,
                confidence REAL,
                score REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                log_type TEXT NOT NULL,
                message TEXT NOT NULL,
                data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def save_trade(self, decision, order_result):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO trades (
                symbol, trade_type, entry_price, stop_loss, target,
                quantity, entry_time, order_id, confidence, score, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            decision['symbol'],
            decision['type'],
            decision['entry'],
            decision['stop_loss'],
            decision['target'],
            decision['quantity'],
            datetime.now(),
            order_result.get('order_id'),
            decision.get('confidence', 0),
            decision.get('score', 0),
            'OPEN'
        ))
        
        trade_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return trade_id
    
    def get_active_positions(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM trades WHERE status = "OPEN" ORDER BY entry_time DESC')
        positions = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return positions
    
    def get_trades(self, limit=50):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM trades ORDER BY created_at DESC LIMIT ?', (limit,))
        trades = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return trades
    
    def get_trading_stats(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) as total FROM trades WHERE status = "CLOSED"')
        total_trades = cursor.fetchone()['total']
        
        cursor.execute('SELECT COUNT(*) as wins FROM trades WHERE status = "CLOSED" AND pnl > 0')
        wins = cursor.fetchone()['wins']
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        
        cursor.execute('SELECT SUM(pnl_percent) as total_pnl FROM trades WHERE status = "CLOSED"')
        total_pnl = cursor.fetchone()['total_pnl'] or 0
        
        conn.close()
        
        return {
            'total_trades': total_trades,
            'win_rate': round(win_rate, 2),
            'total_pnl': round(total_pnl, 2)
        }
    
    def log_event(self, log_type, message, data=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO system_logs (log_type, message, data)
            VALUES (?, ?, ?)
        ''', (log_type, message, json.dumps(data) if data else None))
        
        conn.commit()
        conn.close()