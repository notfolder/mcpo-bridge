"""
プロセス管理モジュール

MCPサーバープロセスの起動、監視、通信を管理
ステートレス（ephemeral）とステートフル（persistent）の両モードをサポート
"""
import asyncio
import subprocess
import json
import logging
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
        # 同一プロセスへのリクエストを直列化するためのロック
        self.request_lock = asyncio.Lock()
    
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
                server_type, server_config, request_data, job_dir
            )
    
    async def _execute_stateless(
        self,
        server_type: str,
        server_config: dict,
        request_data: dict,
        job_dir: Path
    ) -> Tuple[dict, int]:
        """
        ステートレスモードでリクエストを実行
        1リクエスト = 1プロセス
        
        Args:
            server_type: MCPサーバータイプ
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
                
                # tools/listレスポンスの場合、使用方法ガイドツールを追加
                response_data = self._add_usage_guide_tool(server_type, request_data, response_data)
                
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
        
        # 同一プロセスへのリクエストを直列化
        async with process_info.request_lock:
            try:
                # リクエストを送信してレスポンスを受信
                response_data, exit_code = await self._communicate(
                    process_info.process, request_data, settings.timeout
                )
                
                # tools/listレスポンスの場合、使用方法ガイドツールを追加server_type, 
                response_data = self._add_usage_guide_tool(request_data, response_data)
                
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
        logger.info(f"Working directory: {job_dir}")
        logger.info(f"Environment variables: {env_vars}")
        
        # プロセスを起動
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=str(job_dir)
        )
        
        # プロセスが即座に終了していないか確認
        import time
        time.sleep(0.1)  # 100ms待機
        if process.poll() is not None:
            # プロセスが既に終了している場合、stderrを読んでログ出力
            try:
                _, stderr = process.communicate(timeout=1)
                stderr_text = stderr.decode('utf-8', errors='replace')
                logger.error(f"Process exited immediately with code {process.returncode}")
                logger.error(f"stderr: {stderr_text}")
            except Exception as e:
                logger.error(f"Failed to read stderr: {e}")
        
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
        
        # 通知かどうかを判定（"id"フィールドがないリクエストは通知）
        is_notification = "id" not in request_data
        
        try:
            # 標準入力にリクエストを書き込み
            loop = asyncio.get_event_loop()
            await asyncio.wait_for(
                loop.run_in_executor(None, process.stdin.write, request_bytes),
                timeout=5
            )
            await asyncio.wait_for(
                loop.run_in_executor(None, process.stdin.flush),
                timeout=5
            )
            
            # 通知の場合はレスポンスを待たない
            if is_notification:
                logger.debug(f"Sent notification: {request_data.get('method')}")
                # プロセスが終了したかチェック
                exit_code = process.poll()
                if exit_code is None:
                    exit_code = 0  # まだ実行中
                
                # 通知には空のレスポンスを返す
                return {}, exit_code
            
            # 標準出力から1行（JSON-RPCレスポンス）を読み込む
            stdout_line = await asyncio.wait_for(
                loop.run_in_executor(None, process.stdout.readline),
                timeout=timeout
            )
            
            # stderrを非ブロッキングで読み込む（あれば）
            stderr_data = b""
            # ここでは stderr は読まないようにする（ブロックする可能性があるため）
            
            # プロセスが終了したかチェック
            exit_code = process.poll()
            if exit_code is None:
                exit_code = 0  # まだ実行中
            
            logger.debug(f"Process status: exit_code={exit_code}, still_running={exit_code is None or exit_code == 0}")
            
            # レスポンスをパース
            if stdout_line:
                try:
                    response_data = json.loads(stdout_line.decode('utf-8'))
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse MCP server response as JSON: {e}")
                    # JSON-RPC エラーレスポンス形式で返す
                    response_data = {
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32700,
                            "message": "Parse error",
                            "data": stdout_line.decode('utf-8', errors='replace')[:500]
                        },
                        "id": request_data.get("id")
                    }
            else:
                # JSON-RPC エラーレスポンス形式で返す
                response_data = {
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32603,
                        "message": "Internal error",
                        "data": "No response from MCP server"
                    },
                    "id": request_data.get("id")
                }
            
            return response_data, exit_code if exit_code is not None else 0
        
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
        プロセスを終了（非同期版）
        
        Args:
            process: Popenオブジェクト
        """
        if process.poll() is None:
            try:
                # まずSIGTERMを送信
                logger.debug(f"Sending SIGTERM to process {process.pid}")
                process.terminate()
                
                # 非同期で10秒待機
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(process.wait),
                        timeout=10.0
                    )
                    logger.debug(f"Process {process.pid} terminated gracefully")
                except asyncio.TimeoutError:
                    # まだ終了していなければSIGKILLを送信
                    logger.warning(f"Process {process.pid} did not terminate, sending SIGKILL")
                    process.kill()
                    try:
                        await asyncio.wait_for(
                            asyncio.to_thread(process.wait),
                            timeout=5.0
                        )
                        logger.debug(f"Process {process.pid} killed")
                    except asyncio.TimeoutError:
                        logger.error(f"Process {process.pid} could not be killed")
            except Exception as e:
                logger.error(f"Error terminating process {process.pid}: {e}")
    
    def _add_usage_guide_tool(self, server_type: str, request_data: dict, response_data: dict) -> dict:
        """
        tools/listレスポンスに使用方法ガイドのダミーツールを追加
        
        Args:
            server_type: MCPサーバータイプ
            request_data: リクエストデータ
            response_data: レスポンスデータ
        
        Returns:
            ガイドツール追加後のレスポンスデータ
        """
        # tools/listリクエストかチェック
        if request_data.get("method") != "tools/list":
            return response_data
        
        # レスポンスが正常な形式かチェック
        if not isinstance(response_data, dict):
            return response_data
        
        if "result" not in response_data or not isinstance(response_data["result"], dict):
            return response_data
        
        if "tools" not in response_data["result"] or not isinstance(response_data["result"]["tools"], list):
            return response_data
        
        # サーバー設定から使用方法ガイドを取得
        usage_guide_text = mcp_config.get_usage_guide(server_type)
        
        # 使用方法ガイドが設定されていない場合はスキップ
        if not usage_guide_text:
            logger.debug(f"No usage guide configured for server type: {server_type}")
            return response_data
        
        # 使用方法ガイドのダミーツールを作成
        usage_guide_tool = {
            "name": "📖_usage_instructions",
            "description": usage_guide_text,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "_note": {
                        "type": "string",
                        "description": "This is a documentation tool and cannot be executed"
                    }
                },
                "required": []
            }
        }
        
        # ツールリストの先頭に追加（最初に表示されるように）
        response_data["result"]["tools"].insert(0, usage_guide_tool)
        
        logger.info(f"Added usage guide tool to tools/list response for {server_type} ({len(response_data['result']['tools'])} tools total)")
        
        return response_data
    
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
        全プロセスを終了してシャットダウン（タイムアウト付き）
        """
        logger.info("Shutting down process manager...")
        
        try:
            async with self.stateful_lock:
                total_processes = sum(
                    len(clients) 
                    for clients in self.stateful_processes.values()
                )
                logger.info(f"Terminating {total_processes} stateful processes...")
                
                for server_type in list(self.stateful_processes.keys()):
                    for client_ip in list(self.stateful_processes[server_type].keys()):
                        try:
                            await self._remove_stateful_process(server_type, client_ip)
                        except Exception as e:
                            logger.error(
                                f"Error removing process for {server_type}/{client_ip}: {e}"
                            )
            
            logger.info("Process manager shut down complete")
        except Exception as e:
            logger.error(f"Error during process manager shutdown: {e}")


# グローバルプロセスマネージャーインスタンス
process_manager = ProcessManager()
