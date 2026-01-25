"""
ヘルスチェックAPI

サービスの健全性をチェックするエンドポイント
"""
import time
from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks

from src.models.job import HealthResponse
from src.core.process_manager import process_manager
from src.core.config import settings
from src.core.garbage_collector import garbage_collector
from src.version import VERSION

router = APIRouter()

# アプリケーション起動時刻
_start_time = time.time()


@router.get("/health", response_model=HealthResponse)
async def health_check(background_tasks: BackgroundTasks):
    """
    ヘルスチェックエンドポイント
    バックグラウンドでガベージコレクションも実行する
    
    Args:
        background_tasks: FastAPIのバックグラウンドタスク
    
    Returns:
        HealthResponse: ヘルスチェック結果
    """
    # バックグラウンドでガベージコレクションを実行
    background_tasks.add_task(garbage_collector.cleanup_old_jobs)
    
    # 稼働時間を計算
    uptime = time.time() - _start_time
    
    # アクティブプロセス数を取得（ステートフルプロセスのみ）
    stateful_processes_count = 0
    if settings.stateful_enabled:
        for server_type_processes in process_manager.stateful_processes.values():
            stateful_processes_count += len(server_type_processes)
    
    # ステータス判定
    status = "ok"
    if stateful_processes_count >= settings.stateful_max_total_processes * 0.9:
        status = "degraded"
    
    return HealthResponse(
        status=status,
        timestamp=datetime.now(timezone.utc),
        version=VERSION,
        uptime=uptime,
        stateful_processes=stateful_processes_count if settings.stateful_enabled else None
    )
