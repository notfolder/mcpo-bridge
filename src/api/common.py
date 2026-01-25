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
    
    def process_data(data: Any) -> Any:
        nonlocal files
        
        if isinstance(data, dict):
            # 設定されたファイルパスフィールドをチェック
            for field_name in file_path_fields:
                if field_name in data:
                    file_path = data[field_name]
                    
                    # 相対パスの場合のみダウンロードURLを追加
                    if file_path and isinstance(file_path, str) and not os.path.isabs(file_path):
                        # ファイル名を抽出
                        filename = Path(file_path).name
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
    # クライアントIPを抽出
    client_ip = extract_client_ip(request)
    logger.info(f"{protocol_name} request from {client_ip} for server type: {server_type}")
    
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
        response_data, exit_code = await process_manager.execute_request(
            server_type=server_type,
            request_data=request_data,
            job_dir=job_dir,
            client_ip=client_ip if settings.stateful_enabled else None
        )
        
        # レスポンスを保存
        job_manager.save_response(job_id, response_data)
        
        # レスポンスをログに出力（デバッグ用）
        logger.debug(f"MCP response for job {job_id}: {response_data}")
        
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
        response_data, files = _extract_file_info(
            response_data, 
            job_id, 
            settings.base_url,
            file_path_fields
        )
        
        # Open WebUI形式: contentにfilesフィールドとダウンロード案内を追加
        if files and isinstance(response_data, dict):
            if "result" in response_data:
                # MCPツール応答の場合
                if "content" in response_data["result"]:
                    # contentが既に存在する場合
                    if isinstance(response_data["result"]["content"], list):
                        # ダウンロード案内メッセージを先頭のテキストに追加
                        for item in response_data["result"]["content"]:
                            if item.get("type") == "text" and "text" in item:
                                # 既存のテキストにダウンロードリンク情報を追加
                                download_links = "\n\n" + "\n".join([
                                    f"📎 ダウンロード: [{f['name']}]({f['url']})" 
                                    for f in files
                                ])
                                item["text"] += download_links
                                break
                        
                        # filesフィールドも追加
                        response_data["result"]["content"].append({
                            "type": "files",
                            "files": files
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
                        },
                        {
                            "type": "files",
                            "files": files
                        }
                    ]
        
        # レスポンスを返却
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
