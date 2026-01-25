"""
共通MCP処理モジュール

MCP/MCPOエンドポイントの共通処理ロジック
"""
import asyncio
import logging
import os
from pathlib import Path
from typing import Any
from fastapi import Request, HTTPException, status

from src.core.job_manager import job_manager
from src.core.process_manager import process_manager
from src.core.config import mcp_config, settings
from src.models.job import JobStatus
from src.utils.network import extract_client_ip

logger = logging.getLogger(__name__)


def _convert_mcp_to_openai_format(mcp_response: dict, files: list[dict]) -> dict:
    """
    MCPレスポンスをOpenAI互換形式に変換
    
    Args:
        mcp_response: MCPサーバーからのレスポンス（既にファイル情報が追加されている）
        files: ファイル情報のリスト
    
    Returns:
        OpenAI互換形式のレスポンス
    """
    # MCPレスポンスからテキストコンテンツを抽出
    result_text = ""
    
    if isinstance(mcp_response, dict):
        # MCP標準形式: {"jsonrpc": "2.0", "id": 1, "result": {"content": [...]}}
        if "result" in mcp_response:
            result = mcp_response["result"]
            
            if isinstance(result, dict) and "content" in result:
                # contentフィールドから全てのテキストを結合
                # ファイル情報は既に_extract_file_infoで追加されている
                content_list = result["content"]
                if isinstance(content_list, list):
                    text_parts = []
                    for item in content_list:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text_parts.append(item.get("text", ""))
                    result_text = "\n".join(text_parts)
            elif isinstance(result, str):
                # resultが文字列の場合はそのまま使用
                result_text = result
            else:
                # その他の場合はJSON文字列化
                import json
                result_text = json.dumps(result, ensure_ascii=False, indent=2)
        
        # エラーレスポンスの場合
        elif "error" in mcp_response:
            error = mcp_response["error"]
            if isinstance(error, dict):
                result_text = f"Error: {error.get('message', 'Unknown error')}"
            else:
                result_text = f"Error: {error}"
    
    # 結果がない場合は成功メッセージ
    if not result_text:
        result_text = "操作が正常に完了しました。"
    
    # OpenAI互換形式で返却
    # ファイル情報は既にresult_textに含まれている（_extract_file_infoで追加済み）
    return {
        "result": result_text
    }


def _extract_file_info(
    data: Any, 
    job_id: str, 
    base_url: str,
    file_path_fields: list[str]
) -> tuple[Any, list[dict]]:
    """
    レスポンスデータからファイル情報を抽出してOpen WebUI形式に変換
    
    Args:
        data: レスポンスデータ（dict, list, または他の型）
        job_id: ジョブID
        base_url: ベースURL（例: http://nginx）
        file_path_fields: ファイルパス情報を含むフィールド名のリスト
    
    Returns:
        (ダウンロードURL情報が追加されたデータ, ファイル情報のリスト)
    """
    files = []
    jobs_dir = settings.jobs_dir
    
    def extract_filename_from_path(file_path: str) -> str | None:
        """パスからファイル名を抽出（絶対パス・相対パス両対応）"""
        # /tmp/mcpo-jobs/{job_id}/filename.xlsx → filename.xlsx
        if f"/mcpo-jobs/{job_id}/" in file_path:
            return file_path.split(f"/mcpo-jobs/{job_id}/")[-1]
        # 相対パスの場合はそのままファイル名として使用
        elif not os.path.isabs(file_path):
            return Path(file_path).name
        return None
    
    def process_data(data: Any) -> Any:
        nonlocal files
        
        if isinstance(data, dict):
            # 設定されたファイルパスフィールドをチェック
            for field_name in file_path_fields:
                if field_name in data:
                    file_path = data[field_name]
                    
                    if file_path and isinstance(file_path, str):
                        filename = extract_filename_from_path(file_path)
                        
                        if filename:
                            # ダウンロードURLを生成
                            download_url = f"{base_url}/files/{job_id}/{filename}"
                            
                            # Open WebUI形式のファイル情報を追加
                            files.append({
                                "type": "file",
                                "url": download_url,
                                "name": filename
                            })
                            
                            # 後方互換性のため_download_urlも追加
                            data["_download_url"] = download_url
                            logger.debug(f"Added file info for {field_name}={file_path}: {download_url}")
            
            # contentフィールド内のテキストもチェック（Excelツール対応）
            if "content" in data and isinstance(data["content"], list):
                for item in data["content"]:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text = item.get("text", "")
                        # テキスト内の絶対パスを検出して変換
                        if f"/mcpo-jobs/{job_id}/" in text:
                            import re
                            # パスパターンを検出: /tmp/mcpo-jobs/{job_id}/filename.ext
                            pattern = rf'/tmp/mcpo-jobs/{job_id}/([^\s\)]+\.\w+)'
                            matches = re.findall(pattern, text)
                            
                            for filename in matches:
                                download_url = f"{base_url}/files/{job_id}/{filename}"
                                
                                # ファイル情報リストに追加（重複チェック）
                                if not any(f["name"] == filename for f in files):
                                    files.append({
                                        "type": "file",
                                        "url": download_url,
                                        "name": filename
                                    })
                                    logger.debug(f"Extracted file from text: {filename} → {download_url}")
                                
                                # テキスト内のパスを相対パスに置換
                                text = text.replace(f"/tmp/mcpo-jobs/{job_id}/{filename}", filename)
                            
                            # 更新されたテキストを設定
                            item["text"] = text
            
            # ネストされた辞書も再帰的に処理
            for key, value in data.items():
                data[key] = process_data(value)
        
        elif isinstance(data, list):
            # リスト内の各要素を再帰的に処理
            data = [process_data(item) for item in data]
        
        return data
    
    processed_data = process_data(data)
    return processed_data, files


async def process_mcp_request(
    server_type: str,
    request: Request,
    protocol_name: str = "MCP"
) -> dict:
    """
    MCP/MCPOリクエストの共通処理
    
    Args:
        server_type: MCPサーバータイプ（例: "powerpoint"）
        request: FastAPIリクエストオブジェクト
        protocol_name: プロトコル名（ログ用、"MCP"または"MCPO"）
    
    Returns:
        MCPサーバーからのレスポンス（JSON）
    """
    # ファイルパスフィールド名を取得
    file_path_fields = mcp_config.get_file_path_fields(server_type)
    
    # セッションキーを決定（ヘッダー情報優先、フォールバックとしてIPアドレス）
    session_key = None
    client_ip = extract_client_ip(request)
    
    if settings.enable_forward_user_info_headers:
        # Open WebUI ヘッダーからユーザーIDを取得
        user_id = request.headers.get("X-OpenWebUI-User-Id")
        chat_id = request.headers.get("X-OpenWebUI-Chat-Id")
        
        if user_id:
            # ユーザーIDとチャットIDを組み合わせてセッションキーを作成
            # チャットIDがある場合はチャット単位、ない場合はユーザー単位でセッション管理
            session_key = f"user:{user_id}"
            if chat_id:
                session_key = f"{session_key}:chat:{chat_id}"
            logger.debug(f"Using session key from headers: {session_key}")
    
    # ヘッダー情報がない場合はIPアドレスを使用
    if not session_key:
        session_key = f"ip:{client_ip}"
        logger.debug(f"Using session key from IP address: {session_key}")
    
    logger.info(f"{protocol_name} request from {client_ip} (session: {session_key}) for server type: {server_type}")
    
    # サーバータイプの存在確認
    if not mcp_config.get_server_config(server_type):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown server type: {server_type}"
        )
    
    # リクエストボディを取得
    try:
        request_data = await request.json()
        logger.debug(f"MCP request data: {request_data}")
    except Exception as e:
        logger.error(f"Failed to parse request JSON: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON in request body"
        )
    
    # ジョブを作成
    job_id, job_dir = job_manager.create_job(server_type, client_ip)
    
    try:
        # リクエストを保存
        job_manager.save_request(job_id, request_data)
        
        # MCPサーバープロセスでリクエストを実行
        response_data, exit_code, actual_job_dir = await process_manager.execute_request(
            server_type=server_type,
            request_data=request_data,
            job_dir=job_dir,
            session_key=session_key if settings.stateful_enabled else None
        )
        
        # 実際のワーキングディレクトリのjob_idを取得(statefulモード対応)
        actual_job_id = actual_job_dir.name
        
        # レスポンスを保存
        job_manager.save_response(job_id, response_data)
        
        # レスポンスをログに出力(デバッグ用)
        logger.debug(f"MCP response for job {job_id}: {response_data}")
        if actual_job_id != job_id:
            logger.debug(f"Stateful mode: actual working directory is {actual_job_id}")
        
        # ジョブステータスを更新
        if exit_code == 0:
            job_manager.update_status(job_id, JobStatus.COMPLETED)
        else:
            job_manager.update_status(
                job_id,
                JobStatus.FAILED,
                f"Process exited with code {exit_code}"
            )
        
        # レスポンスにダウンロードURLとファイル情報を追加
        # statefulモードの場合は実際のjob_idを使用
        response_data, files = _extract_file_info(
            response_data, 
            actual_job_id,  # 実際のワーキングディレクトリのjob_idを使用
            settings.base_url,
            file_path_fields
        )
        
        # Open WebUI形式: contentにダウンロード案内を追加
        if files and isinstance(response_data, dict):
            if "result" in response_data:
                # MCPツール応答の場合
                if "content" in response_data["result"]:
                    # contentが既に存在する場合
                    if isinstance(response_data["result"]["content"], list):
                        # ダウンロードリンクを新しいテキスト要素として追加
                        download_text = "\n\n" + "\n".join([
                            f"📎 ダウンロード: [{f['name']}]({f['url']})" 
                            for f in files
                        ])
                        response_data["result"]["content"].append({
                            "type": "text",
                            "text": download_text
                        })
                else:
                    # contentがない場合は作成
                    download_text = "\n".join([
                        f"📎 ダウンロード: [{f['name']}]({f['url']})" 
                        for f in files
                    ])
                    response_data["result"]["content"] = [
                        {
                            "type": "text",
                            "text": download_text
                        }
                    ]
        
        # MCPOプロトコルの場合はOpenAI互換形式に変換
        if protocol_name == "MCPO":
            openai_response = _convert_mcp_to_openai_format(response_data, files)
            logger.debug(f"Converted to OpenAI format: {openai_response}")
            return openai_response
        
        # MCP形式のまま返却（従来の動作）
        return response_data
    
    except asyncio.TimeoutError:
        logger.error(f"Timeout processing {protocol_name} request for job {job_id}")
        job_manager.update_status(job_id, JobStatus.FAILED, "Timeout")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="MCP server request timeout"
        )
    
    except Exception as e:
        logger.error(f"Error processing {protocol_name} request for job {job_id}: {e}")
        job_manager.update_status(job_id, JobStatus.FAILED, str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing request: {str(e)}"
        )
