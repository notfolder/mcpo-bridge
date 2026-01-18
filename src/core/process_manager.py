"""
プロセス管理モジュール

MCPサーバープロセスの起動、監視、通信を管理
ステートレス（ephemeral）とステートフル（persistent）の両モードをサポート
"""
import asyncio
import subprocess
import json
import logging
import signal
import time
import os
from typing import Dict, Optional, Any, Tuple
from pathlib import Path
from datetime import datetime, timezone

from src.core.config import settings, mcp_config
from src.models.job import JobStatus

logger = logging.getLogger(__name__)


class StatefulProcessInfo:
    """ステートフルプロセス情報を保持するクラス"""
    
    def __init__(
        self,
        process: subprocess.Popen,
        server_type: str,
        client_ip: str,
        idle_timeout: int
    ):
        self.process = process
        self.server_type = server_type
        self.client_ip = client_ip
        self.created_at = datetime.now(timezone.utc)
        self.last_access = datetime.now(timezone.utc)
        self.request_count = 0
        self.idle_timeout = idle_timeout
    
    def is_healthy(self) -> bool:
        """
        プロセスが健全な状態かチェック
        
        Returns:
            健全な場合True
        """
        # プロセスが終了していないかチェック
        if self.process.poll() is not None:
            return False
        
        # 標準入出力パイプの有効性確認
        try:
            if self.process.stdin and self.process.stdin.closed:
                return False
            if self.process.stdout and self.process.stdout.closed:
                return False
        except Exception:
            return False
        
        return True
    
    def is_idle_timeout(self) -> bool:
        """
        アイドルタイムアウトしているかチェック
        
        Returns:
            タイムアウトしている場合True
        """
        idle_seconds = (datetime.now(timezone.utc) - self.last_access).total_seconds()
        return idle_seconds > self.idle_timeout


class ProcessManager:
    """
    プロセス管理クラス
    MCPサーバープロセスの起動、通信、終了を管理
    """
    
    def __init__(self):
        """初期化"""
        self.semaphore = asyncio.Semaphore(settings.max_concurrent)
        
        # ステートフルプロセスプール: {server_type: {client_ip: StatefulProcessInfo}}
        self.stateful_processes: Dict[str, Dict[str, StatefulProcessInfo]] = {}
        self.stateful_lock = asyncio.Lock()
    
    async def execute_request(
        self,
        server_type: str,
        request_data: dict,
        job_dir: Path,
        client_ip: Optional[str] = None
    ) -> Tuple[dict, int]:
        """
        MCPリクエストを実行
        ステートフル/ステートレスモードを自動判定して処理
        
        Args:
            server_type: MCPサーバータイプ
            request_data: リクエストデータ
            job_dir: ジョブディレクトリ
            client_ip: クライアントIPアドレス
        
        Returns:
            (レスポンスデータ, 終了コード) のタプル
        """
        # サーバー設定を取得
        server_config = mcp_config.get_server_config(server_type)
        if not server_config:
            raise ValueError(f"Unknown server type: {server_type}")
        
        # ステートフルモードかチェック
        is_stateful = settings.stateful_enabled and mcp_config.is_stateful(server_type)
        
        if is_stateful and client_ip:
            return await self._execute_stateful(
                server_type, server_config, request_data, job_dir, client_ip
            )
        else:
            return await self._execute_stateless(
                server_config, request_data, job_dir
            )
    
    async def _execute_stateless(
        self,
        server_config: dict,
        request_data: dict,
        job_dir: Path
    ) -> Tuple[dict, int]:
        """
        ステートレスモードでリクエストを実行
        1リクエスト = 1プロセス
        
        Args:
            server_config: サーバー設定
            request_data: リクエストデータ
            job_dir: ジョブディレクトリ
        
        Returns:
            (レスポンスデータ, 終了コード) のタプル
        """
        async with self.semaphore:
            logger.info(f"Executing stateless request in {job_dir}")
            
            # プロセスを起動
            process = await self._start_process(server_config, job_dir)
            
            try:
                # リクエストを送信してレスポンスを受信
                response_data, exit_code = await self._communicate(
                    process, request_data, settings.timeout
                )
                return response_data, exit_code
            
            finally:
                # プロセスを確実に終了
                await self._terminate_process(process)
    
    async def _execute_stateful(
        self,
        server_type: str,
        server_config: dict,
        request_data: dict,
        job_dir: Path,
        client_ip: str
    ) -> Tuple[dict, int]:
        """
        ステートフルモードでリクエストを実行
        IPアドレスごとにプロセスを維持
        
        Args:
            server_type: MCPサーバータイプ
            server_config: サーバー設定
            request_data: リクエストデータ
            job_dir: ジョブディレクトリ
            client_ip: クライアントIPアドレス
        
        Returns:
            (レスポンスデータ, 終了コード) のタプル
        """
        async with self.stateful_lock:
            # プロセスプールからプロセスを取得または作成
            process_info = await self._get_or_create_stateful_process(
                server_type, server_config, job_dir, client_ip
            )
        
        if not process_info:
            raise RuntimeError(f"Failed to get or create stateful process for {client_ip}")
        
        try:
            # リクエストを送信してレスポンスを受信
            response_data, exit_code = await self._communicate(
                process_info.process, request_data, settings.timeout
            )
            
            # プロセス情報を更新
            async with self.stateful_lock:
                process_info.last_access = datetime.now(timezone.utc)
                process_info.request_count += 1
            
            return response_data, exit_code
        
        except Exception as e:
            # エラー時はプロセスを削除
            logger.error(f"Error in stateful process for {client_ip}: {e}")
            async with self.stateful_lock:
                await self._remove_stateful_process(server_type, client_ip)
            raise
    
    async def _get_or_create_stateful_process(
        self,
        server_type: str,
        server_config: dict,
        job_dir: Path,
        client_ip: str
    ) -> Optional[StatefulProcessInfo]:
        """
        ステートフルプロセスを取得または作成
        
        Args:
            server_type: MCPサーバータイプ
            server_config: サーバー設定
            job_dir: ジョブディレクトリ
            client_ip: クライアントIPアドレス
        
        Returns:
            StatefulProcessInfoオブジェクト
        """
        # サーバータイプのプールを初期化
        if server_type not in self.stateful_processes:
            self.stateful_processes[server_type] = {}
        
        # 既存プロセスをチェック
        if client_ip in self.stateful_processes[server_type]:
            process_info = self.stateful_processes[server_type][client_ip]
            
            # 健全性チェック
            if process_info.is_healthy():
                logger.info(f"Reusing stateful process for {client_ip}")
                return process_info
            else:
                # 不健全な場合は削除
                logger.warning(f"Removing unhealthy stateful process for {client_ip}")
                await self._remove_stateful_process(server_type, client_ip)
        
        # 新規プロセスを起動
        logger.info(f"Creating new stateful process for {client_ip}")
        idle_timeout = mcp_config.get_idle_timeout(server_type)
        process = await self._start_process(server_config, job_dir)
        
        process_info = StatefulProcessInfo(
            process=process,
            server_type=server_type,
            client_ip=client_ip,
            idle_timeout=idle_timeout
        )
        
        self.stateful_processes[server_type][client_ip] = process_info
        return process_info
    
    async def _remove_stateful_process(self, server_type: str, client_ip: str):
        """
        ステートフルプロセスを削除
        
        Args:
            server_type: MCPサーバータイプ
            client_ip: クライアントIPアドレス
        """
        if server_type in self.stateful_processes:
            if client_ip in self.stateful_processes[server_type]:
                process_info = self.stateful_processes[server_type][client_ip]
                await self._terminate_process(process_info.process)
                del self.stateful_processes[server_type][client_ip]
                logger.info(f"Removed stateful process for {client_ip}")
    
    async def _start_process(
        self,
        server_config: dict,
        job_dir: Path
    ) -> subprocess.Popen:
        """
        MCPサーバープロセスを起動
        
        Args:
            server_config: サーバー設定
            job_dir: ジョブディレクトリ
        
        Returns:
            Popenオブジェクト
        """
        command = server_config["command"]
        args = server_config.get("args", [])
        env_vars = server_config.get("env", {})
        
        # 環境変数を構築
        env = os.environ.copy()
        env.update(env_vars)
        env["MCPO_WORKDIR"] = str(job_dir)
        env["MCPO_JOB_ID"] = job_dir.name
        
        # コマンドライン引数を構築
        cmd = [command] + args
        
        logger.info(f"Starting process: {' '.join(cmd)}")
        
        # プロセスを起動
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=str(job_dir)
        )
        
        return process
    
    async def _communicate(
        self,
        process: subprocess.Popen,
        request_data: dict,
        timeout: int
    ) -> Tuple[dict, int]:
        """
        プロセスとの通信を行う
        
        Args:
            process: Popenオブジェクト
            request_data: リクエストデータ
            timeout: タイムアウト秒数
        
        Returns:
            (レスポンスデータ, 終了コード) のタプル
        """
        # リクエストをJSON文字列に変換
        request_json = json.dumps(request_data) + "\n"
        request_bytes = request_json.encode('utf-8')
        
        try:
            # 標準入力にリクエストを書き込み、標準出力からレスポンスを読み込む
            stdout_data, stderr_data = await self._communicate_sync(process, request_bytes, timeout)
            
            # 終了コードを取得（非同期）
            loop = asyncio.get_event_loop()
            exit_code = await loop.run_in_executor(None, lambda: process.wait(timeout=1))
            
            # レスポンスをパース
            if stdout_data:
                response_data = json.loads(stdout_data.decode('utf-8'))
            else:
                response_data = {"error": "No response from MCP server"}
            
            return response_data, exit_code
        
        except asyncio.TimeoutError:
            logger.error(f"Process timeout after {timeout} seconds")
            await self._terminate_process(process)
            raise
        except Exception as e:
            logger.error(f"Process communication error: {e}")
            raise
    
    async def _communicate_sync(
        self,
        process: subprocess.Popen,
        request_bytes: bytes,
        timeout: int
    ) -> Tuple[bytes, bytes]:
        """
        同期的にプロセスと通信（非同期化のため別スレッドで実行）
        
        Args:
            process: Popenオブジェクト
            request_bytes: リクエストバイト列
            timeout: タイムアウト秒数
        
        Returns:
            (stdout, stderr) のタプル
        """
        loop = asyncio.get_event_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: process.communicate(input=request_bytes)
            ),
            timeout=timeout
        )
    
    async def _terminate_process(self, process: subprocess.Popen):
        """
        プロセスを終了
        
        Args:
            process: Popenオブジェクト
        """
        if process.poll() is None:
            try:
                # まずSIGTERMを送信
                process.terminate()
                
                # 10秒待機
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    # まだ終了していなければSIGKILLを送信
                    logger.warning("Process did not terminate, sending SIGKILL")
                    process.kill()
                    process.wait(timeout=5)
            except Exception as e:
                logger.error(f"Error terminating process: {e}")
    
    async def start_cleanup_task(self):
        """
        ステートフルプロセスのクリーンアップタスクを開始
        定期的にアイドルタイムアウトしたプロセスを削除
        """
        logger.info("Starting stateful process cleanup task")
        
        while True:
            try:
                await asyncio.sleep(settings.stateful_cleanup_interval)
                await self._cleanup_idle_processes()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")
    
    async def _cleanup_idle_processes(self):
        """
        アイドルタイムアウトしたプロセスをクリーンアップ
        """
        async with self.stateful_lock:
            for server_type in list(self.stateful_processes.keys()):
                for client_ip in list(self.stateful_processes[server_type].keys()):
                    process_info = self.stateful_processes[server_type][client_ip]
                    
                    if process_info.is_idle_timeout():
                        logger.info(
                            f"Cleaning up idle process for {client_ip} "
                            f"(idle for {(datetime.now(timezone.utc) - process_info.last_access).total_seconds()}s)"
                        )
                        await self._remove_stateful_process(server_type, client_ip)
    
    async def shutdown(self):
        """
        全プロセスを終了してシャットダウン
        """
        logger.info("Shutting down process manager...")
        
        async with self.stateful_lock:
            for server_type in list(self.stateful_processes.keys()):
                for client_ip in list(self.stateful_processes[server_type].keys()):
                    await self._remove_stateful_process(server_type, client_ip)
        
        logger.info("Process manager shut down complete")


# グローバルプロセスマネージャーインスタンス
process_manager = ProcessManager()
