import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from loguru import logger


class PersistenceManager:
    def __init__(self, base_dir: Optional[Path] = None):
        if base_dir is None:
            from qlib_vnpy_platform.config import PROJECT_ROOT
            base_dir = PROJECT_ROOT / "data" / "persistence"
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_directories()
        logger.info(f"PersistenceManager initialized at {self.base_dir}")

    def _ensure_directories(self):
        directories = [
            self.base_dir / "trading",
            self.base_dir / "backups",
            self.base_dir / "trades",
        ]
        for dir_path in directories:
            dir_path.mkdir(parents=True, exist_ok=True)

    def save_json(self, data: Any, file_path: Path) -> bool:
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            logger.debug(f"Data saved to {file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save data to {file_path}: {e}")
            return False

    def load_json(self, file_path: Path, default: Any = None) -> Any:
        if not file_path.exists():
            return default
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            logger.debug(f"Data loaded from {file_path}")
            return data
        except Exception as e:
            logger.error(f"Failed to load data from {file_path}: {e}")
            return default

    def create_backup(self, file_path: Path, max_backups: int = 5) -> bool:
        if not file_path.exists():
            return False
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self.base_dir / "backups" / f"{file_path.stem}_{timestamp}{file_path.suffix}"
            import shutil
            shutil.copy2(file_path, backup_path)
            
            backups = sorted(
                list(self.base_dir.glob(f"{file_path.stem}_*")),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )
            for old_backup in backups[max_backups:]:
                old_backup.unlink()
            logger.debug(f"Backup created: {backup_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to create backup: {e}")
            return False

    def save_trading_state(self, state: Dict[str, Any]) -> bool:
        file_path = self.base_dir / "trading" / "trading_state.json"
        self.create_backup(file_path)
        return self.save_json(state, file_path)

    def load_trading_state(self) -> Optional[Dict[str, Any]]:
        file_path = self.base_dir / "trading" / "trading_state.json"
        return self.load_json(file_path)

    def save_trades(self, trades: list) -> bool:
        file_path = self.base_dir / "trades" / f"trades_{datetime.now().strftime('%Y%m%d')}.json"
        return self.save_json(trades, file_path)
    
    def append_trade(self, trade: Dict[str, Any]) -> bool:
        today_file = self.base_dir / "trades" / f"trades_{datetime.now().strftime('%Y%m%d')}.json"
        trades = self.load_json(today_file, [])
        trades.append(trade)
        return self.save_json(trades, today_file)
    
    def get_backup_list(self, file_stem: str) -> list:
        """获取指定文件的备份列表"""
        backups = list(self.base_dir.glob(f"{file_stem}_*"))
        backups.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return backups
    
    def restore_from_backup(self, backup_path: Path) -> Optional[Dict[str, Any]]:
        """从备份恢复数据"""
        if not backup_path.exists():
            logger.error(f"Backup file not found: {backup_path}")
            return None
        return self.load_json(backup_path)
    
    def clean_old_backups(self, days: int = 30):
        """清理过期的备份文件"""
        from datetime import timedelta
        cutoff_date = datetime.now() - timedelta(days=days)
        deleted_count = 0
        
        for backup_file in self.base_dir.glob("**/*_????????_??????.*"):
            if backup_file.stat().st_mtime < cutoff_date.timestamp():
                try:
                    backup_file.unlink()
                    deleted_count += 1
                except Exception as e:
                    logger.error(f"Failed to delete old backup {backup_file}: {e}")
        
        if deleted_count > 0:
            logger.info(f"Cleaned {deleted_count} old backup files")
        
        return deleted_count
    
    def get_storage_stats(self) -> Dict[str, Any]:
        """获取存储统计信息"""
        stats = {
            "total_size_bytes": 0,
            "file_count": 0,
            "backup_count": 0,
            "trade_files": 0,
            "oldest_file": None,
            "newest_file": None
        }
        
        all_files = list(self.base_dir.glob("**/*"))
        all_files = [f for f in all_files if f.is_file()]
        
        if not all_files:
            return stats
        
        stats["file_count"] = len(all_files)
        stats["total_size_bytes"] = sum(f.stat().st_size for f in all_files)
        stats["backup_count"] = len(list(self.base_dir.glob("backups/*")))
        stats["trade_files"] = len(list(self.base_dir.glob("trades/*.json")))
        
        oldest = min(all_files, key=lambda f: f.stat().st_mtime)
        newest = max(all_files, key=lambda f: f.stat().st_mtime)
        
        stats["oldest_file"] = {
            "path": str(oldest.relative_to(self.base_dir)),
            "modified": datetime.fromtimestamp(oldest.stat().st_mtime).isoformat()
        }
        stats["newest_file"] = {
            "path": str(newest.relative_to(self.base_dir)),
            "modified": datetime.fromtimestamp(newest.stat().st_mtime).isoformat()
        }
        
        return stats
