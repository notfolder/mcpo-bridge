"""
MCPOエンドポイント

MCPOプロトコルのリクエストを処理
"""
import asyncio
import logging
from fastapi import APIRouter, Request, HTTPException, status
from typing import Dict, Any

from src.core.job_manager import job_manager
from src.core.process_manager import process_manager
from src.core.config import mcp_config, settings
from src.models.job import JobStatus
from src.utils.network import extract_client_ip

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/{server_type}")
async def mcpo_endpoint(server_type: str, request: Request):
    """
    MCPOエンドポイント
    
    MCPOプロトコルのリクエストを受け付け、対応するMCPサーバーに転送
    レスポンスはそのまま返却（変更なし）
    
    Args:
        server_type: MCPサーバータイプ（例: "powerpoint"）
        request: FastAPIリクエストオブジェクト
    
    Returns:
        MCPサーバーからのレスポンス（JSON）
    """
    # クライアントIPを抽出
    client_ip = extract_client_ip(request)
    logger.info(f"MCPO request from {client_ip} for server type: {server_type}")
    
    # サーバータイプの存在確認
    if not mcp_config.get_server_config(server_type):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown server type: {server_type}"
        )
    
    # リクエストボディを取得
    try:
        request_data = await request.json()
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
        
        # ジョブステータスを更新
        if exit_code == 0:
            job_manager.update_status(job_id, JobStatus.COMPLETED)
        else:
            job_manager.update_status(
                job_id,
                JobStatus.FAILED,
                f"Process exited with code {exit_code}"
            )
        
        # レスポンスをそのまま返却
        return response_data
    
    except asyncio.TimeoutError:
        logger.error(f"Timeout processing MCPO request for job {job_id}")
        job_manager.update_status(job_id, JobStatus.FAILED, "Timeout")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="MCP server request timeout"
        )
    
    except Exception as e:
        logger.error(f"Error processing MCPO request for job {job_id}: {e}")
        job_manager.update_status(job_id, JobStatus.FAILED, str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing request: {str(e)}"
        )
