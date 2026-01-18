"""
ガーベジコレクションモジュール

古いジョブディレクトリを定期的に削除する
"""
import asyncio
import shutil
import logging
from pathlib import Path
from datetime import datetime, timedelta

from src.core.config import settings
from src.core.job_manager import job_manager

logger = logging.getLogger(__name__)


class GarbageCollector:
    """
    ガーベジコレクタークラス
    古いジョブディレクトリを定期的に削除
    """
    
    def __init__(self):
        """初期化"""
        self.jobs_dir = Path(settings.jobs_dir)
        self.file_expiry = settings.file_expiry
    
    def cleanup_old_jobs(self):
        """
        古いジョブディレクトリを削除
        file_expiry秒以上経過したジョブを削除対象とする
        """
        if not self.jobs_dir.exists():
            logger.warning(f"Jobs directory does not exist: {self.jobs_dir}")
            return
        
        cutoff_time = datetime.utcnow() - timedelta(seconds=self.file_expiry)
        deleted_count = 0
        
        logger.info(f"Starting garbage collection (cutoff: {cutoff_time})")
        
        # ジョブディレクトリを走査
        for job_dir in self.jobs_dir.iterdir():
            if not job_dir.is_dir():
                continue
            
            # ディレクトリ作成時刻をチェック
            try:
                # metadata.jsonから作成時刻を取得
                metadata = job_manager.load_metadata(job_dir.name)
                
                if metadata:
                    created_at = metadata.created_at
                    if isinstance(created_at, str):
                        created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                else:
                    # メタデータがない場合はディレクトリの変更時刻を使用
                    mtime = datetime.fromtimestamp(job_dir.stat().st_mtime)
                    created_at = mtime
                
                # 削除判定
                if created_at < cutoff_time:
                    logger.info(f"Deleting old job directory: {job_dir.name}")
                    self._safe_delete(job_dir)
                    deleted_count += 1
            
            except Exception as e:
                logger.error(f"Error processing job directory {job_dir.name}: {e}")
        
        logger.info(f"Garbage collection complete. Deleted {deleted_count} job directories")
    
    def _safe_delete(self, path: Path):
        """
        安全にディレクトリを削除
        
        Args:
            path: 削除対象のパス
        """
        # 安全性チェック: jobs_dir配下のみ削除可能
        try:
            path_resolved = path.resolve()
            jobs_dir_resolved = self.jobs_dir.resolve()
            
            if not str(path_resolved).startswith(str(jobs_dir_resolved)):
                logger.error(f"Attempted to delete path outside jobs directory: {path}")
                return
            
            # シンボリックリンクでないことを確認
            if path.is_symlink():
                logger.warning(f"Skipping symlink: {path}")
                return
            
            # ディレクトリを削除
            shutil.rmtree(path)
            logger.debug(f"Deleted: {path}")
        
        except Exception as e:
            logger.error(f"Failed to delete {path}: {e}")
    
    async def start(self):
        """
        ガーベジコレクションタスクを開始
        定期的にcleanup_old_jobsを実行
        """
        logger.info("Starting garbage collection task")
        
        # 1時間ごとに実行
        interval = 3600  # 1 hour
        
        while True:
            try:
                await asyncio.sleep(interval)
                self.cleanup_old_jobs()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in garbage collection task: {e}")


# グローバルガーベジコレクターインスタンス
garbage_collector = GarbageCollector()
