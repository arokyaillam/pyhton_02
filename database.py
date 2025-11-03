import sqlite3
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)


class Database:
    """Enhanced Database with Exit Updates and Performance Indexes"""
    
    def __init__(self, db_path='trading.db'):
        self.db_path = db_path
        self.init_database()
        logger.info(f"Database initialized: {db_path}")
    
    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_database(self):
        """Initialize database with indexes"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Trades table
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
                engine_type TEXT DEFAULT 'futures',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # NEW: Add indexes for performance
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_entry_time ON trades(entry_time)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_status ON trades(status)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_symbol ON trades(symbol)
        ''')
        
        # System logs table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                log_type TEXT NOT NULL,
                message TEXT NOT NULL,
                data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # NEW: Risk tracking table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date DATE NOT NULL UNIQUE,
                total_trades INTEGER DEFAULT 0,
                winning_trades INTEGER DEFAULT 0,
                losing_trades INTEGER DEFAULT 0,
                total_pnl REAL DEFAULT 0,
                max_drawdown REAL DEFAULT 0,
                largest_win REAL DEFAULT 0,
                largest_loss REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("Database schema initialized with indexes")
    
    def save_trade(self, decision, order_result, engine_type='futures'):
        """Save new trade entry"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO trades (
                    symbol, trade_type, entry_price, stop_loss, target,
                    quantity, entry_time, order_id, confidence, score, 
                    status, engine_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                'OPEN',
                engine_type
            ))
            
            trade_id = cursor.lastrowid
            conn.commit()
            
            logger.info(f"Trade saved: ID={trade_id}, Type={decision['type']}, Entry={decision['entry']}")
            return trade_id
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error saving trade: {e}", exc_info=True)
            return None
        finally:
            conn.close()
    
    def update_trade_exit(self, trade_id, exit_price, pnl, pnl_percent, exit_reason):
        """NEW: Update trade on exit"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE trades 
                SET exit_price = ?, 
                    exit_time = ?, 
                    pnl = ?, 
                    pnl_percent = ?, 
                    status = 'CLOSED', 
                    exit_reason = ?
                WHERE id = ?
            ''', (
                exit_price,
                datetime.now(),
                pnl,
                pnl_percent,
                exit_reason,
                trade_id
            ))
            
            conn.commit()
            
            # Update daily stats
            self.update_daily_stats(pnl)
            
            logger.info(f"Trade exited: ID={trade_id}, P&L={pnl:.2f}, Reason={exit_reason}")
            return True
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error updating trade exit: {e}", exc_info=True)
            return False
        finally:
            conn.close()
    
    def update_daily_stats(self, pnl):
        """NEW: Update daily statistics"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            today = datetime.now().date()
            
            # Check if today's record exists
            cursor.execute('''
                SELECT id, total_pnl, largest_win, largest_loss 
                FROM daily_stats 
                WHERE trade_date = ?
            ''', (today,))
            
            row = cursor.fetchone()
            
            if row:
                # Update existing record
                cursor.execute('''
                    UPDATE daily_stats
                    SET total_trades = total_trades + 1,
                        winning_trades = winning_trades + ?,
                        losing_trades = losing_trades + ?,
                        total_pnl = total_pnl + ?,
                        largest_win = MAX(largest_win, ?),
                        largest_loss = MIN(largest_loss, ?)
                    WHERE trade_date = ?
                ''', (
                    1 if pnl > 0 else 0,
                    1 if pnl < 0 else 0,
                    pnl,
                    pnl if pnl > 0 else row['largest_win'],
                    pnl if pnl < 0 else row['largest_loss'],
                    today
                ))
            else:
                # Create new record
                cursor.execute('''
                    INSERT INTO daily_stats (
                        trade_date, total_trades, winning_trades, 
                        losing_trades, total_pnl, largest_win, largest_loss
                    ) VALUES (?, 1, ?, ?, ?, ?, ?)
                ''', (
                    today,
                    1 if pnl > 0 else 0,
                    1 if pnl < 0 else 0,
                    pnl,
                    pnl if pnl > 0 else 0,
                    pnl if pnl < 0 else 0
                ))
            
            conn.commit()
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error updating daily stats: {e}", exc_info=True)
        finally:
            conn.close()
    
    def get_active_positions(self):
        """Get all open positions"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT * FROM trades 
                WHERE status = "OPEN" 
                ORDER BY entry_time DESC
            ''')
            positions = [dict(row) for row in cursor.fetchall()]
            return positions
        except Exception as e:
            logger.error(f"Error fetching active positions: {e}", exc_info=True)
            return []
        finally:
            conn.close()
    
    def get_active_position_by_id(self, trade_id):
        """NEW: Get specific active position"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT * FROM trades 
                WHERE id = ? AND status = "OPEN"
            ''', (trade_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error fetching position: {e}", exc_info=True)
            return None
        finally:
            conn.close()
    
    def get_trades(self, limit=50, status=None):
        """Get trade history with optional status filter"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            if status:
                cursor.execute('''
                    SELECT * FROM trades 
                    WHERE status = ?
                    ORDER BY created_at DESC 
                    LIMIT ?
                ''', (status, limit))
            else:
                cursor.execute('''
                    SELECT * FROM trades 
                    ORDER BY created_at DESC 
                    LIMIT ?
                ''', (limit,))
            
            trades = [dict(row) for row in cursor.fetchall()]
            return trades
        except Exception as e:
            logger.error(f"Error fetching trades: {e}", exc_info=True)
            return []
        finally:
            conn.close()
    
    def get_trading_stats(self):
        """Get comprehensive trading statistics"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # Overall stats
            cursor.execute('''
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'CLOSED' THEN 1 ELSE 0 END) as closed,
                    SUM(CASE WHEN status = 'OPEN' THEN 1 ELSE 0 END) as open
                FROM trades
            ''')
            overall = dict(cursor.fetchone())
            
            # Closed trade stats
            cursor.execute('''
                SELECT 
                    COUNT(*) as total_closed,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losses,
                    SUM(pnl) as total_pnl,
                    AVG(pnl) as avg_pnl,
                    MAX(pnl) as max_win,
                    MIN(pnl) as max_loss,
                    AVG(pnl_percent) as avg_pnl_percent
                FROM trades 
                WHERE status = 'CLOSED'
            ''')
            closed_stats = dict(cursor.fetchone())
            
            total_closed = closed_stats['total_closed'] or 0
            wins = closed_stats['wins'] or 0
            win_rate = (wins / total_closed * 100) if total_closed > 0 else 0
            
            # Today's stats
            cursor.execute('''
                SELECT * FROM daily_stats
                WHERE trade_date = DATE('now')
            ''')
            today_row = cursor.fetchone()
            today_stats = dict(today_row) if today_row else {
                'total_trades': 0,
                'total_pnl': 0,
                'winning_trades': 0
            }
            
            return {
                'total_trades': overall['total'],
                'open_positions': overall['open'],
                'closed_trades': total_closed,
                'win_rate': round(win_rate, 2),
                'total_pnl': round(closed_stats['total_pnl'] or 0, 2),
                'avg_pnl': round(closed_stats['avg_pnl'] or 0, 2),
                'max_win': round(closed_stats['max_win'] or 0, 2),
                'max_loss': round(closed_stats['max_loss'] or 0, 2),
                'avg_pnl_percent': round(closed_stats['avg_pnl_percent'] or 0, 2),
                'today_trades': today_stats['total_trades'],
                'today_pnl': round(today_stats['total_pnl'], 2),
                'today_wins': today_stats['winning_trades']
            }
            
        except Exception as e:
            logger.error(f"Error fetching trading stats: {e}", exc_info=True)
            return {
                'total_trades': 0,
                'win_rate': 0,
                'total_pnl': 0,
                'avg_pnl': 0,
                'max_win': 0,
                'max_loss': 0
            }
        finally:
            conn.close()
    
    def log_event(self, log_type, message, data=None):
        """Log system events"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO system_logs (log_type, message, data)
                VALUES (?, ?, ?)
            ''', (log_type, message, json.dumps(data) if data else None))
            
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Error logging event: {e}", exc_info=True)
        finally:
            conn.close()
    
    def cleanup_old_logs(self, days=7):
        """NEW: Clean up old system logs"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                DELETE FROM system_logs 
                WHERE created_at < datetime('now', '-' || ? || ' days')
            ''', (days,))
            
            deleted = cursor.rowcount
            conn.commit()
            logger.info(f"Cleaned up {deleted} old log entries")
            return deleted
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error cleaning up logs: {e}", exc_info=True)
            return 0
        finally:
            conn.close()


logger.info("✅ Enhanced Database Module Loaded")
logger.info("🗄️  Features: Trade Updates, Daily Stats, Performance Indexes")