"""
MCPOエンドポイント

MCPOプロトコルのリクエストを処理
"""
import logging
from fastapi import APIRouter, Request

from src.api.common import process_mcp_request

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
    return await process_mcp_request(server_type, request, "MCPO")
