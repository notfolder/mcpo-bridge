"""
データモデル定義

ジョブ、リクエスト、レスポンスのデータ構造を定義
"""
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from enum import Enum


class JobStatus(str, Enum):
    """ジョブステータス"""
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobMetadata(BaseModel):
    """
    ジョブメタデータ
    各ジョブディレクトリに保存されるメタ情報
    """
    job_id: str = Field(..., description="ジョブの一意識別子（UUID）")
    server_type: str = Field(..., description="使用したMCPサーバータイプ")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="作成日時")
    status: JobStatus = Field(default=JobStatus.PROCESSING, description="ジョブステータス")
    request: Optional[Dict[str, Any]] = Field(None, description="受信したMCPリクエスト")
    response: Optional[Dict[str, Any]] = Field(None, description="MCPサーバーレスポンス")
    error: Optional[str] = Field(None, description="エラーメッセージ（失敗時のみ）")
    client_ip: Optional[str] = Field(None, description="クライアントIPアドレス")


class HealthResponse(BaseModel):
    """
    ヘルスチェックレスポンス
    """
    status: str = Field(..., description="健全性ステータス（ok/degraded/down）")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="チェック実行時刻")
    version: str = Field(default="1.0.0", description="Bridgeバージョン")
    uptime: Optional[float] = Field(None, description="稼働時間（秒）")
    active_processes: Optional[int] = Field(None, description="アクティブなプロセス数")
    stateful_processes: Optional[int] = Field(None, description="ステートフルプロセス数")


class MCPRequest(BaseModel):
    """
    MCPリクエスト
    最小限のJSON-RPC 2.0構造検証
    """
    model_config = ConfigDict(extra='allow')
    
    jsonrpc: Optional[str] = Field(default="2.0", description="JSON-RPCバージョン")
    id: Optional[Any] = Field(None, description="リクエストID")
    method: Optional[str] = Field(None, description="メソッド名")
    params: Optional[Dict[str, Any]] = Field(None, description="パラメータ")


class MCPORequest(BaseModel):
    """
    MCPOリクエスト
    最小限のJSON-RPC 2.0構造検証
    """
    model_config = ConfigDict(extra='allow')
    
    jsonrpc: Optional[str] = Field(default="2.0", description="JSON-RPCバージョン")
    id: Optional[Any] = Field(None, description="リクエストID")
    method: Optional[str] = Field(None, description="メソッド名")
    params: Optional[Dict[str, Any]] = Field(None, description="パラメータ")


class ProcessInfo(BaseModel):
    """
    プロセス情報
    ステートフルプロセス管理用（参照データモデル、実際の管理は別クラス）
    """
    process_id: int = Field(..., description="プロセスID")
    server_type: str = Field(..., description="MCPサーバータイプ")
    client_ip: str = Field(..., description="クライアントIPアドレス")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="プロセス作成日時")
    last_access: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="最終アクセス日時")
    request_count: int = Field(default=0, description="処理したリクエスト数")
    idle_timeout: int = Field(..., description="アイドルタイムアウト秒数")
