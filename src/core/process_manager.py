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
from typing import Dict, Optional, Tuple
from pathlib import Path
from datetime import datetime, timezone

from src.core.config import settings, mcp_config

logger = logging.getLogger(__name__)


class StatefulProcessInfo:
    """ステートフルプロセス情報を保持するクラス"""
    
    def __init__(
        self,
        process: subprocess.Popen,
        server_type: str,
        session_key: str,
        idle_timeout: int,
        working_dir: Path,
        stderr_task: Optional[asyncio.Task] = None
    ):
        self.process = process
        self.server_type = server_type
        self.session_key = session_key  # セッションキー（ユーザーID:チャットID または IPアドレス）
        self.created_at = datetime.now(timezone.utc)
        self.last_access = datetime.now(timezone.utc)
        self.request_count = 0
        self.idle_timeout = idle_timeout
        self.working_dir = working_dir  # 実際のプロセスのワーキングディレクトリ
        # 同一プロセスへのリクエストを直列化するためのロック
        self.request_lock = asyncio.Lock()
        # stderrを読み取る非同期タスク
        self.stderr_task = stderr_task
    
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
        
        # ステートフルプロセスプール: {server_type: {session_key: StatefulProcessInfo}}
        self.stateful_processes: Dict[str, Dict[str, StatefulProcessInfo]] = {}
        self.stateful_lock = asyncio.Lock()
    
    async def execute_request(
        self,
        server_type: str,
        request_data: dict,
        job_dir: Path,
        session_key: Optional[str] = None
    ) -> Tuple[dict, int, Path]:
        """
        MCPリクエストを実行
        ステートフル/ステートレスモードを自動判定して処理
        
        Args:
            server_type: MCPサーバータイプ
            request_data: リクエストデータ
            job_dir: ジョブディレクトリ
            session_key: セッションキー（ユーザーID:チャットID または IPアドレス）
        
        Returns:
            (レスポンスデータ, 終了コード, 実際のワーキングディレクトリ) のタプル
        """
        logger.info(f"[EXECUTE_REQUEST] server_type={server_type}, method={request_data.get('method')}, session_key={session_key}")
        logger.debug(f"[EXECUTE_REQUEST] job_dir={job_dir}")
        logger.debug(f"[EXECUTE_REQUEST] request_data={request_data}")
        
        # サーバー設定を取得
        server_config = mcp_config.get_server_config(server_type)
        if not server_config:
            logger.error(f"[EXECUTE_REQUEST] Unknown server type: {server_type}")
            raise ValueError(f"Unknown server type: {server_type}")
        
        # ステートフルモードかチェック
        is_stateful = settings.stateful_enabled and mcp_config.is_stateful(server_type)
        logger.info(f"[EXECUTE_REQUEST] Mode: {'stateful' if is_stateful else 'stateless'} (stateful_enabled={settings.stateful_enabled}, server_stateful={mcp_config.is_stateful(server_type)}, has_session_key={bool(session_key)})")
        
        if is_stateful and session_key:
            return await self._execute_stateful(
                server_type, server_config, request_data, job_dir, session_key
            )
        else:
            return await self._execute_stateless(
                server_type, server_config, request_data, job_dir
            )
    
    def _resolve_file_paths(
        self,
        request_data: dict,
        resolve_path_fields: list,
        job_dir: Path
    ) -> dict:
        """
        resolve_path_fieldsで指定されたフィールドを絶対パスに変換
        
        Args:
            request_data: リクエストデータ
            resolve_path_fields: 変換対象のフィールド名リスト（mcp-servers.jsonで設定）
            job_dir: ジョブディレクトリ（相対パスの解決に使用）
        
        Returns:
            変換後のリクエストデータ
        
        Note:
            file_path_fieldsとは別用途:
            - resolve_path_fields: リクエスト時の絶対パス変換用（この関数）
            - file_path_fields: レスポンス時のURL変換用（別処理）
        """
        if not resolve_path_fields:
            return request_data
        
        # tools/callリクエストのargumentsを処理
        if request_data.get("method") == "tools/call":
            params = request_data.get("params", {})
            arguments = params.get("arguments", {})
            
            for field in resolve_path_fields:
                if field in arguments:
                    file_path = arguments[field]
                    # 文字列かつ相対パス（絶対パスでない）場合のみ変換
                    if isinstance(file_path, str) and not os.path.isabs(file_path):
                        # job_dirを基準に絶対パスに変換
                        absolute_path = str(job_dir / file_path)
                        arguments[field] = absolute_path
                        logger.debug(f"Resolved file path: {field}: {file_path} → {absolute_path}")
        
        return request_data
    
    async def _execute_stateless(
        self,
        server_type: str,
        server_config: dict,
        request_data: dict,
        job_dir: Path
    ) -> Tuple[dict, int, Path]:
        """
        ステートレスモードでリクエストを実行
        1リクエスト = 1プロセス
        
        MCPプロトコルの初期化シーケンスを自動処理:
        - initialize/notifications/initialized以外のリクエストの場合、
          自動的にinitialize → initialized を送信してからユーザーリクエストを処理
        
        Args:
            server_type: MCPサーバータイプ
            server_config: サーバー設定
            request_data: リクエストデータ
            job_dir: ジョブディレクトリ
        
        Returns:
            (レスポンスデータ, 終了コード, 実際のワーキングディレクトリ) のタプル
        """
        async with self.semaphore:
            logger.info(f"[STATELESS] Executing stateless request in {job_dir}")
            logger.debug(f"[STATELESS] Server config: {server_config}")
            
            # プロセスを起動
            process = await self._start_process(server_config, job_dir)
            
            # stderrを読み取る非同期タスクを起動
            stderr_task = asyncio.create_task(
                self._read_stderr(process, f"[{server_type}]")
            )
            
            try:
                # resolve_path_fieldsが指定されている場合、ファイルパスを絶対パスに変換
                resolve_path_fields = server_config.get("resolve_path_fields", [])
                request_data = self._resolve_file_paths(request_data, resolve_path_fields, job_dir)
                
                # リクエストのメソッドを取得
                method = request_data.get("method", "")
                
                # initialize/notifications/initialized 以外のリクエストの場合、自動初期化を実行
                if method not in ["initialize", "notifications/initialized"]:
                    logger.debug(f"Auto-initializing MCP process for method: {method}")
                    
                    # 1. initialize リクエストを送信
                    init_request = {
                        "jsonrpc": "2.0",
                        "id": 0,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-11-25",
                            "capabilities": {},
                            "clientInfo": {
                                "name": "mcpo-bridge",
                                "version": "1.0.0"
                            }
                        }
                    }
                    init_response, _ = await self._communicate(
                        process, init_request, settings.timeout
                    )
                    logger.debug(f"Auto-initialize response: {init_response}")
                    
                    # 2. notifications/initialized を送信
                    initialized_notification = {
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized"
                    }
                    await self._communicate(
                        process, initialized_notification, settings.timeout
                    )
                    logger.debug("Auto-initialized notification sent")
                
                # 3. ユーザーの実際のリクエストを送信してレスポンスを受信
                response_data, exit_code = await self._communicate(
                    process, request_data, settings.timeout
                )
                
                # tools/listレスポンスの場合、使用方法ガイドツールを追加
                response_data = self._add_usage_guide_tool(server_type, request_data, response_data)
                
                return response_data, exit_code, job_dir
            
            finally:
                # stderrタスクをキャンセル
                if not stderr_task.done():
                    stderr_task.cancel()
                    try:
                        await stderr_task
                    except asyncio.CancelledError:
                        pass
                # プロセスを確実に終了
                await self._terminate_process(process)
    
    async def _execute_stateful(
        self,
        server_type: str,
        server_config: dict,
        request_data: dict,
        job_dir: Path,
        session_key: str
    ) -> Tuple[dict, int, Path]:
        """
        ステートフルモードでリクエストを実行
        セッションキーごとにプロセスを維持
        
        Args:
            server_type: MCPサーバータイプ
            server_config: サーバー設定
            request_data: リクエストデータ
            job_dir: ジョブディレクトリ
            session_key: セッションキー（ユーザーID:チャットID または IPアドレス）
        
        Returns:
            (レスポンスデータ, 終了コード, 実際のワーキングディレクトリ) のタプル
        """
        async with self.stateful_lock:
            # プロセスプールからプロセスを取得または作成
            process_info = await self._get_or_create_stateful_process(
                server_type, server_config, job_dir, session_key
            )
        
        if not process_info:
            raise RuntimeError(f"Failed to get or create stateful process for {session_key}")
        
        # 同一プロセスへのリクエストを直列化
        async with process_info.request_lock:
            try:
                # resolve_path_fieldsが指定されている場合、ファイルパスを絶対パスに変換
                resolve_path_fields = server_config.get("resolve_path_fields", [])
                request_data = self._resolve_file_paths(request_data, resolve_path_fields, process_info.working_dir)
                
                # リクエストを送信してレスポンスを受信
                response_data, exit_code = await self._communicate(
                    process_info.process, request_data, settings.timeout
                )
                
                # tools/listレスポンスの場合、使用方法ガイドツールを追加
                response_data = self._add_usage_guide_tool(server_type, request_data, response_data)
                
                # プロセス情報を更新
                async with self.stateful_lock:
                    process_info.last_access = datetime.now(timezone.utc)
                    process_info.request_count += 1
                
                # 実際のワーキングディレクトリ(最初のjob_dir)を返す
                return response_data, exit_code, process_info.working_dir
            
            except Exception as e:
                # エラー時はプロセスを削除
                logger.error(f"Error in stateful process for {session_key}: {e}")
                async with self.stateful_lock:
                    await self._remove_stateful_process(server_type, session_key)
                raise
    
    async def _get_or_create_stateful_process(
        self,
        server_type: str,
        server_config: dict,
        job_dir: Path,
        session_key: str
    ) -> Optional[StatefulProcessInfo]:
        """
        ステートフルプロセスを取得または作成
        
        Args:
            server_type: MCPサーバータイプ
            server_config: サーバー設定
            job_dir: ジョブディレクトリ
            session_key: セッションキー（ユーザーID:チャットID または IPアドレス）
        
        Returns:
            StatefulProcessInfoオブジェクト
        """
        # サーバータイプのプールを初期化
        if server_type not in self.stateful_processes:
            self.stateful_processes[server_type] = {}
        
        # 既存プロセスをチェック
        if session_key in self.stateful_processes[server_type]:
            process_info = self.stateful_processes[server_type][session_key]
            
            # 健全性チェック
            if process_info.is_healthy():
                logger.info(f"Reusing stateful process for {session_key}")
                return process_info
            else:
                # 不健全な場合は削除
                logger.warning(f"Removing unhealthy stateful process for {session_key}")
                await self._remove_stateful_process(server_type, session_key)
        
        # 新規プロセスを起動
        logger.info(f"Creating new stateful process for {session_key}")
        idle_timeout = mcp_config.get_idle_timeout(server_type)
        process = await self._start_process(server_config, job_dir)
        
        # stderrを読み取る非同期タスクを起動
        stderr_task = asyncio.create_task(
            self._read_stderr(process, f"[{server_type}:{session_key}]")
        )
        
        # MCPプロトコルの初期化シーケンスを実行
        logger.debug(f"Initializing MCP process for {session_key}")
        
        # 1. initialize リクエストを送信
        init_request = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {
                    "name": "mcpo-bridge",
                    "version": "1.0.0"
                }
            }
        }
        init_response, _ = await self._communicate(
            process, init_request, settings.timeout
        )
        logger.debug(f"Initialize response for {session_key}: {init_response}")
        
        # 2. notifications/initialized を送信
        initialized_notification = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized"
        }
        await self._communicate(
            process, initialized_notification, settings.timeout
        )
        logger.debug(f"Initialized notification sent for {session_key}")
        
        process_info = StatefulProcessInfo(
            process=process,
            server_type=server_type,
            session_key=session_key,
            idle_timeout=idle_timeout,
            working_dir=job_dir,  # 実際のワーキングディレクトリを記録
            stderr_task=stderr_task
        )
        
        self.stateful_processes[server_type][session_key] = process_info
        logger.info(f"Stateful process created and initialized for {session_key} with working_dir: {job_dir}")
        return process_info
    
    async def _remove_stateful_process(self, server_type: str, session_key: str):
        """
        ステートフルプロセスを削除
        
        Args:
            server_type: MCPサーバータイプ
            session_key: セッションキー（ユーザーID:チャットID または IPアドレス）
        """
        if server_type in self.stateful_processes:
            if session_key in self.stateful_processes[server_type]:
                process_info = self.stateful_processes[server_type][session_key]
                # stderrタスクをキャンセル
                if process_info.stderr_task and not process_info.stderr_task.done():
                    process_info.stderr_task.cancel()
                    try:
                        await process_info.stderr_task
                    except asyncio.CancelledError:
                        pass
                await self._terminate_process(process_info.process)
                del self.stateful_processes[server_type][session_key]
                logger.info(f"Removed stateful process for {session_key}")
    
    async def _read_stderr(self, process: subprocess.Popen, prefix: str):
        """
        プロセスのstderrを非同期で読み取り、infoレベルでログ出力
        
        Args:
            process: Popenオブジェクト
            prefix: ログ出力時のプレフィックス
        """
        try:
            loop = asyncio.get_event_loop()
            while True:
                # プロセスが終了していたら中断
                if process.poll() is not None:
                    break
                
                try:
                    # stderrから1行読み込む（非同期）
                    line_bytes = await asyncio.wait_for(
                        loop.run_in_executor(None, process.stderr.readline),
                        timeout=1.0
                    )
                    
                    if not line_bytes:
                        # EOFに達した場合
                        break
                    
                    # デコードしてログ出力
                    line = line_bytes.decode('utf-8', errors='replace').rstrip('\n\r')
                    if line:  # 空行は出力しない
                        logger.info(f"{prefix} [stderr] {line}")
                
                except asyncio.TimeoutError:
                    # タイムアウトは正常（次の読み込みを試みる）
                    continue
                except Exception as e:
                    logger.debug(f"Error reading stderr: {e}")
                    break
        
        except asyncio.CancelledError:
            logger.debug(f"{prefix} stderr reader cancelled")
            raise
        except Exception as e:
            logger.error(f"{prefix} stderr reader error: {e}")
    
    
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
        
        # プレースホルダを実際の値に置換
        # {MCPO_WORKDIR} → 実際のジョブディレクトリパス
        # {MCPO_JOB_ID} → ジョブID
        resolved_env_vars = {}
        for key, value in env_vars.items():
            if isinstance(value, str):
                resolved_value = value.replace("{MCPO_WORKDIR}", str(job_dir))
                resolved_value = resolved_value.replace("{MCPO_JOB_ID}", job_dir.name)
                resolved_env_vars[key] = resolved_value
            else:
                resolved_env_vars[key] = value
        
        env.update(resolved_env_vars)
        env["MCPO_WORKDIR"] = str(job_dir)
        env["MCPO_JOB_ID"] = job_dir.name
        
        # コマンドライン引数を構築
        cmd = [command] + args
        
        logger.info(f"[START_PROCESS] Command: {' '.join(cmd)}")
        logger.info(f"[START_PROCESS] Working directory: {job_dir}")
        logger.info(f"[START_PROCESS] Custom environment variables: {resolved_env_vars}")
        logger.debug(f"[START_PROCESS] Full environment: {env}")
        
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
        
        logger.info(f"[COMMUNICATE] Sending request: method={request_data.get('method')}, id={request_data.get('id')}")
        logger.debug(f"[COMMUNICATE] Full request: {request_json.strip()}")
        
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
            
            # stdoutの内容をログ出力
            if stdout_line:
                stdout_text = stdout_line.decode('utf-8', errors='replace').rstrip('\n\r')
                if stdout_text:
                    logger.info(f"[COMMUNICATE] [stdout] {stdout_text}")
            
            # プロセスが終了したかチェック
            exit_code = process.poll()
            if exit_code is None:
                exit_code = 0  # まだ実行中
            
            logger.info(f"[COMMUNICATE] Process status: exit_code={exit_code}, still_running={exit_code is None or exit_code == 0}")
            
            # レスポンスをパース
            if stdout_line:
                try:
                    response_data = json.loads(stdout_line.decode('utf-8'))
                    logger.debug(f"[COMMUNICATE] Parsed response: {response_data}")
                except json.JSONDecodeError as e:
                    logger.error(f"[COMMUNICATE] Failed to parse MCP server response as JSON: {e}")
                    logger.error(f"[COMMUNICATE] Raw response (first 500 chars): {stdout_line.decode('utf-8', errors='replace')[:500]}")
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
                logger.warning("[COMMUNICATE] No response from MCP server")
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
            
            logger.info(f"[COMMUNICATE] Returning response with exit_code={exit_code}")
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
                
                # 非同期で3秒待機
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(process.wait),
                        timeout=3.0
                    )
                    logger.debug(f"Process {process.pid} terminated gracefully")
                except asyncio.TimeoutError:
                    # まだ終了していなければSIGKILLを送信
                    logger.warning(f"Process {process.pid} did not terminate, sending SIGKILL")
                    process.kill()
                    try:
                        await asyncio.wait_for(
                            asyncio.to_thread(process.wait),
                            timeout=2.0
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
                for session_key in list(self.stateful_processes[server_type].keys()):
                    process_info = self.stateful_processes[server_type][session_key]
                    
                    if process_info.is_idle_timeout():
                        logger.info(
                            f"Cleaning up idle process for {session_key} "
                            f"(idle for {(datetime.now(timezone.utc) - process_info.last_access).total_seconds()}s)"
                        )
                        await self._remove_stateful_process(server_type, session_key)
    
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
                    for session_key in list(self.stateful_processes[server_type].keys()):
                        try:
                            await self._remove_stateful_process(server_type, session_key)
                        except Exception as e:
                            logger.error(
                                f"Error removing process for {server_type}/{session_key}: {e}"
                            )
            
            logger.info("Process manager shut down complete")
        except Exception as e:
            logger.error(f"Error during process manager shutdown: {e}")


# グローバルプロセスマネージャーインスタンス
process_manager = ProcessManager()
