"""
MCPOエンドポイント

MCPOプロトコルとOpenAI API互換エンドポイントの処理
"""
import logging
from fastapi import APIRouter, Request, HTTPException, status

from src.api.common import process_mcp_request
from src.core.config import mcp_config, settings
from src.core.process_manager import process_manager
from src.core.job_manager import job_manager

router = APIRouter()
logger = logging.getLogger(__name__)


async def _generate_openapi_spec(server_type: str, request: Request):
    """
    OpenAPI仕様書を生成する内部関数
    
    指定されたMCPサーバーからtools/listを取得し、
    OpenAI API互換の関数定義に変換してOpenAPI仕様書として返す
    
    Args:
        server_type: MCPサーバータイプ（例: "powerpoint"）
        request: FastAPIリクエストオブジェクト
    
    Returns:
        OpenAPI 3.0仕様書（JSON）
    """
    # サーバータイプの存在確認
    if not mcp_config.get_server_config(server_type):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown server type: {server_type}"
        )
    
    # セッション情報を取得(OpenAPI仕様書取得時はセッション不要だが、
    # 将来的な拡張のため一貫性を保つ)
    user_id = request.headers.get("X-OpenWebUI-User-Id")
    chat_id = request.headers.get("X-OpenWebUI-Chat-Id")
    session_key = None
    if chat_id:
        session_key = f"chat:{chat_id}"
        if user_id:
            session_key = f"user:{user_id}:{session_key}"
    elif user_id:
        session_key = f"user:{user_id}"
    
    # tools/listリクエストを作成
    # 注: MCP protocolではparamsフィールドが必須（空でもOK）
    tools_list_request = {
        "jsonrpc": "2.0",
        "method": "tools/list",
        "params": {},
        "id": 1
    }
    
    # 一時的なジョブIDを作成(OpenAPI仕様書生成用)
    job_id, job_dir = job_manager.create_job(server_type, session_key)
    
    try:
        # MCPサーバーからツール一覧を取得
        response_data, exit_code, actual_job_dir = await process_manager.execute_request(
            server_type=server_type,
            request_data=tools_list_request,
            job_dir=job_dir,
            session_key=session_key if settings.stateful_enabled else None
        )
        
        # デバッグ: tools/list レスポンスをログ出力
        logger.debug(f"[DEBUG] tools/list response for {server_type}: {response_data}")
        
        # レスポンスからツール情報を抽出
        tools = []
        if isinstance(response_data, dict) and "result" in response_data:
            result = response_data["result"]
            if isinstance(result, dict) and "tools" in result:
                tools = result["tools"]
        
        logger.debug(f"[DEBUG] Retrieved {len(tools)} tools from {server_type}")
        
        # usage guideを取得
        usage_guide = mcp_config.get_usage_guide(server_type)
        logger.debug(f"[DEBUG] Usage guide for {server_type}: {'Found' if usage_guide else 'Not found'}")
        if usage_guide:
            logger.debug(f"[DEBUG] Usage guide length: {len(usage_guide)}")
            logger.debug(f"[DEBUG] Usage guide preview: {usage_guide[:200]}...")
        
        # OpenAPI仕様書を生成
        description = f"OpenAI-compatible API for {server_type} MCP server"
        if usage_guide:
            description = f"{description}\n\n{usage_guide}"
        
        openapi_spec = {
            "openapi": "3.0.0",
            "info": {
                "title": f"{server_type} MCP Server API",
                "description": description,
                "version": "1.0.0"
            },
            "servers": [
                {
                    # OpenWebUIはTool Server設定のURLを直接使用するため、
                    # ここではダミーのURLを設定（実際には使われない）
                    "url": "/"
                }
            ],
            "paths": {},
            "components": {
                "schemas": {}
            }
        }
        
        # ツールが取得できない場合はダミーツールを追加
        if not tools and usage_guide:
            tools = [
                {
                    "name": f"{server_type}_usage_guide",
                    "description": f"Usage guide for {server_type} MCP server:\n\n{usage_guide}",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Your question about how to use this tool"
                            }
                        },
                        "required": []
                    }
                }
            ]
        
        # 各ツールをOpenAPI paths形式に変換
        # Open WebUIはpathsセクションからoperationIdを使ってツールを抽出する
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            
            tool_name = tool.get("name", "")
            tool_description = tool.get("description", "")
            input_schema = tool.get("inputSchema", {})
            
            # usage guideが存在し、ダミーツールでない場合は説明に追加
            # LLMが直接参照するのはoperation.descriptionなので、ここに含める
            original_description = tool_description
            if usage_guide and not tool_name.endswith("_usage_guide"):
                tool_description = f"{tool_description}\n\n## Usage Guide\n\n{usage_guide}"
                logger.debug(f"[DEBUG] Tool '{tool_name}': Added usage guide to description")
                logger.debug(f"[DEBUG]   Original length: {len(original_description)}")
                logger.debug(f"[DEBUG]   New length: {len(tool_description)}")
            
            # ツール名をパスに変換
            # OpenWebUIはTool Server設定のURL（例: http://nginx/mcpo/powerpoint）を
            # ベースURLとして使用し、ここで定義したpathを追加する
            # したがって、path = "/{tool_name}" とすると、
            # 最終的なURL = http://nginx/mcpo/powerpoint/{tool_name} となる
            path = f"/{tool_name}"
            
            # OpenAPI path item定義
            # operation.descriptionにusage guideを含める（LLMが参照するのはここ）
            logger.debug(f"[DEBUG] Creating OpenAPI path for '{tool_name}'")
            logger.debug(f"[DEBUG]   summary: {tool.get('description', '')[:100]}...")
            logger.debug(f"[DEBUG]   description: {tool_description[:100]}...")
            
            openapi_spec["paths"][path] = {
                "post": {
                    "operationId": tool_name,
                    "summary": tool.get("description", ""),  # 元のツール説明
                    "description": tool_description,  # usage guide含む完全な説明
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": input_schema
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Successful operation",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object"
                                    }
                                }
                            }
                        }
                    }
                }
            }
        
        # 最終的なOpenAPI仕様書のサマリーをログ出力
        logger.debug(f"[DEBUG] OpenAPI spec generated for {server_type}:")
        logger.debug(f"[DEBUG]   Paths count: {len(openapi_spec['paths'])}")
        logger.debug(f"[DEBUG]   Info description length: {len(openapi_spec['info'].get('description', ''))}")
        
        return openapi_spec
    
    except Exception as e:
        logger.error(f"Failed to generate OpenAPI spec for {server_type}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate OpenAPI specification: {str(e)}"
        )


@router.get("/{server_type}/openapi.json")
async def get_openapi_spec_with_suffix(server_type: str, request: Request):
    """
    OpenAI API互換のOpenAPI仕様書を生成（/openapi.json付き）
    
    Args:
        server_type: MCPサーバータイプ（例: "powerpoint"）
        request: FastAPIリクエストオブジェクト
    
    Returns:
        OpenAPI 3.0仕様書（JSON）
    """
    logger.info(f"[ENDPOINT] GET /{server_type}/openapi.json called")
    return await _generate_openapi_spec(server_type, request)


@router.get("/{server_type}")
async def get_openapi_spec_root(server_type: str, request: Request):
    """
    OpenAI API互換のOpenAPI仕様書を生成（ルートパス）
    
    Open WebUIは/{server_type}にGETリクエストを送ってOpenAPI仕様を取得するため、
    このエンドポイントでも同じ仕様書を返す
    
    Args:
        server_type: MCPサーバータイプ（例: "powerpoint"）
        request: FastAPIリクエストオブジェクト
    
    Returns:
        OpenAPI 3.0仕様書（JSON）
    """
    logger.info(f"[ENDPOINT] GET /{server_type} called")
    return await _generate_openapi_spec(server_type, request)


@router.post("/{server_type}/{tool_name}")
async def mcpo_tool_endpoint_with_path(server_type: str, tool_name: str, request: Request):
    """
    MCPOツールエンドポイント（パスパラメータ版）
    
    Args:
        server_type: MCPサーバータイプ（例: "powerpoint"）
        tool_name: ツール名（例: "create_presentation"）
        request: FastAPIリクエストオブジェクト
    
    Returns:
        OpenAI互換形式のレスポンス（JSON）
    """
    params = await request.json()
    logger.info(f"[ENDPOINT] POST /{server_type}/{tool_name} called")
    logger.info(f"[ENDPOINT] Tool parameters: {params}")
    
    return await _handle_mcpo_tool_call(server_type, tool_name, params, request)


@router.post("/{server_type}")
async def mcpo_tool_endpoint_legacy(server_type: str, request: Request):
    """
    MCPOツールエンドポイント（レガシー版 - OpenWebUI互換）
    
    OpenWebUIがリクエストボディに_tool_nameを含めて送信する場合に対応
    
    Args:
        server_type: MCPサーバータイプ（例: "powerpoint"）
        request: FastAPIリクエストオブジェクト
    
    Returns:
        OpenAI互換形式のレスポンス（JSON）
    """
    body = await request.json()
    logger.info(f"[ENDPOINT] POST /{server_type} called")
    logger.info(f"[ENDPOINT] Request body: {body}")
    
    # ツール名を抽出（OpenWebUIが送る場合）
    tool_name = body.pop("_tool_name", None)
    
    if not tool_name:
        # ツール名がない場合はエラー
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing _tool_name in request body"
        )
    
    return await _handle_mcpo_tool_call(server_type, tool_name, body, request)


async def _handle_mcpo_tool_call(
    server_type: str,
    tool_name: str,
    params: dict,
    request: Request
) -> dict:
    """
    MCPOツール呼び出しの共通処理
    
    Args:
        server_type: MCPサーバータイプ
        tool_name: ツール名
        params: ツールパラメータ
        request: FastAPIリクエストオブジェクト
    
    Returns:
        OpenAI互換形式のレスポンス
    """
    # MCP JSON-RPC形式にリクエストを構築
    mcp_request = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": params
        },
        "id": 1
    }
    
    logger.debug(f"[MCPO] Calling tool '{tool_name}' with params: {params}")
    logger.debug(f"[MCPO] MCP request: {mcp_request}")
    
    # process_mcp_requestに渡す前に、requestオブジェクトのボディを置き換え
    class MockRequest:
        def __init__(self, original_request, new_body):
            self._original = original_request
            self._body = new_body
            self.headers = original_request.headers
            self.client = original_request.client
        
        async def json(self):
            return self._body
    
    mock_request = MockRequest(request, mcp_request)
    
    return await process_mcp_request(server_type, mock_request, "MCPO")
