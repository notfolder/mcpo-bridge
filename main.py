"""
MCPO On-Demand Bridge - メインアプリケーション

FastAPIベースのMCPO Bridgeサーバー
MCPサーバーを動的に起動し、ファイル生成リクエストを処理する
"""
import asyncio
import logging
import signal
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import settings
from src.api import health, mcp, mcpo
from src.core.process_manager import process_manager
from src.core.garbage_collector import garbage_collector
from src.version import VERSION

# ロギング設定
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# シャットダウンフラグ
shutdown_event = asyncio.Event()


def handle_shutdown_signal(signum, frame):
    """
    シグナルハンドラー
    SIGTERMまたはSIGINTを受信したときにシャットダウンイベントを設定
    """
    sig_name = signal.Signals(signum).name
    logger.info(f"Received {sig_name} signal, initiating graceful shutdown...")
    shutdown_event.set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    アプリケーションのライフサイクル管理
    起動時と終了時の処理を定義
    """
    # 起動時処理
    logger.info("MCPO Bridge starting up...")
    logger.info(f"Jobs directory: {settings.jobs_dir}")
    logger.info(f"Config file: {settings.config_file}")
    logger.info(f"Max concurrent: {settings.max_concurrent}")
    logger.info(f"Stateful mode: {settings.stateful_enabled}")
    
    # シグナルハンドラーの登録
    signal.signal(signal.SIGTERM, handle_shutdown_signal)
    signal.signal(signal.SIGINT, handle_shutdown_signal)
    
    # ガーベジコレクションの初期クリーンアップ
    logger.info("Running initial garbage collection...")
    garbage_collector.cleanup_old_jobs()
    
    # ガーベジコレクションタスクの開始
    gc_task = asyncio.create_task(garbage_collector.start())
    
    # ステートフルプロセスクリーンアップタスクの開始
    if settings.stateful_enabled:
        logger.info("Starting stateful process cleanup task...")
        cleanup_task = asyncio.create_task(process_manager.start_cleanup_task())
    else:
        cleanup_task = None
    
    logger.info("MCPO Bridge started successfully")
    
    yield
    
    # 終了時処理
    logger.info("MCPO Bridge shutting down...")
    
    # シャットダウンイベントをセット（外部からの停止要求の場合）
    shutdown_event.set()
    
    # ガーベジコレクションタスクのキャンセル
    logger.info("Cancelling garbage collection task...")
    gc_task.cancel()
    try:
        await asyncio.wait_for(gc_task, timeout=5.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        logger.debug("Garbage collection task cancelled")
    
    # ステートフルプロセスクリーンアップタスクのキャンセル
    if cleanup_task:
        logger.info("Cancelling cleanup task...")
        cleanup_task.cancel()
        try:
            await asyncio.wait_for(cleanup_task, timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            logger.debug("Cleanup task cancelled")
    
    # 全プロセスの終了（タイムアウト付き）
    logger.info("Shutting down all MCP processes...")
    try:
        await asyncio.wait_for(process_manager.shutdown(), timeout=30.0)
        logger.info("All processes shut down successfully")
    except asyncio.TimeoutError:
        logger.warning("Process shutdown timed out after 30 seconds")
    
    logger.info("MCPO Bridge shut down successfully")


# FastAPIアプリケーションの作成
app = FastAPI(
    title="MCPO On-Demand Bridge",
    description="MCP/MCPOプロトコル対応のファイル生成系MCPサーバーブリッジ",
    version=VERSION,
    lifespan=lifespan
)

# CORSミドルウェアの追加
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ルーターの登録
app.include_router(health.router, tags=["Health"])
app.include_router(mcp.router, prefix="/mcp", tags=["MCP"])
app.include_router(mcpo.router, prefix="/mcpo", tags=["MCPO"])


@app.get("/")
async def root():
    """
    ルートエンドポイント
    """
    return {
        "service": "MCPO On-Demand Bridge",
        "version": VERSION,
        "status": "running"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8080,
        log_level=settings.log_level.lower(),
        timeout_graceful_shutdown=50  # グレースフルシャットダウンのタイムアウト（秒）
    )
