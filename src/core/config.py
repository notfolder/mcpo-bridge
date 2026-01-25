"""
設定管理モジュール

環境変数からアプリケーション設定を読み込む
MCPサーバー設定ファイルの管理
"""
import json
import os
from typing import Dict, Any, Optional, List
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    アプリケーション設定
    環境変数から設定を読み込む
    """
    
    # 基本設定
    base_url: str = "http://nginx"
    config_file: str = "/app/config/mcp-servers.json"
    jobs_dir: str = "/tmp/mcpo-jobs"
    log_level: str = "INFO"
    
    # プロセス管理設定
    max_concurrent: int = 16
    timeout: int = 300
    
    # ファイル有効期限設定（秒）
    file_expiry: int = 3600
    
    # ステートフル設定
    stateful_enabled: bool = True
    stateful_default_idle_timeout: int = 1800
    stateful_max_processes_per_ip: int = 1
    stateful_max_total_processes: int = 100
    stateful_cleanup_interval: int = 300
    
    class Config:
        env_prefix = "MCPO_"
        case_sensitive = False


class MCPServerConfig:
    """
    MCPサーバー設定管理
    mcp-servers.jsonから設定を読み込む
    """
    
    def __init__(self, config_file: str):
        """
        初期化
        
        Args:
            config_file: 設定ファイルパス
        """
        self.config_file = config_file
        self._config: Dict[str, Any] = {}
        self._load_config()
    
    def _load_config(self):
        """
        設定ファイルを読み込む
        """
        config_path = Path(self.config_file)
        
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_file}")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if "mcpServers" not in data:
            raise ValueError("Config file must have 'mcpServers' key")
        
        self._config = data["mcpServers"]
    
    def get_server_config(self, server_type: str) -> Optional[Dict[str, Any]]:
        """
        特定のサーバータイプの設定を取得
        
        Args:
            server_type: サーバータイプ名（例: "powerpoint"）
        
        Returns:
            サーバー設定辞書、存在しない場合はNone
        """
        return self._config.get(server_type)
    
    def list_server_types(self) -> List[str]:
        """
        利用可能なサーバータイプのリストを取得
        
        Returns:
            サーバータイプ名のリスト
        """
        return list(self._config.keys())
    
    def is_stateful(self, server_type: str) -> bool:
        """
        指定されたサーバータイプがステートフルモードかチェック
        
        Args:
            server_type: サーバータイプ名
        
        Returns:
            ステートフルモードの場合True
        """
        config = self.get_server_config(server_type)
        if not config:
            return False
        return config.get("mode", "stateless") == "stateful"
    
    def get_idle_timeout(self, server_type: str) -> int:
        """
        指定されたサーバータイプのアイドルタイムアウトを取得
        
        Args:
            server_type: サーバータイプ名
        
        Returns:
            アイドルタイムアウト秒数
        """
        config = self.get_server_config(server_type)
        if not config:
            return settings.stateful_default_idle_timeout
        return config.get("idle_timeout", settings.stateful_default_idle_timeout)
    
    def get_max_processes_per_ip(self, server_type: str) -> int:
        """
        指定されたサーバータイプのIPごとの最大プロセス数を取得
        
        Args:
            server_type: サーバータイプ名
        
        Returns:
            IPごとの最大プロセス数
        """
        config = self.get_server_config(server_type)
        if not config:
            return settings.stateful_max_processes_per_ip
        return config.get("max_processes_per_ip", settings.stateful_max_processes_per_ip)
    
    def get_file_path_fields(self, server_type: str) -> List[str]:
        """
        指定されたサーバータイプのファイルパスフィールド名リストを取得
        
        レスポンスに含まれるファイルパス情報のフィールド名を指定する。
        これらのフィールドに対して自動的にダウンロードURLが追加される。
        
        Args:
            server_type: サーバータイプ名
        
        Returns:
            ファイルパスフィールド名のリスト（デフォルト: ["file_path"]）
        """
        config = self.get_server_config(server_type)
        if not config:
            return ["file_path"]
        return config.get("file_path_fields", ["file_path"])
    
    def get_usage_guide(self, server_type: str) -> Optional[str]:
        """
        指定されたサーバータイプの使用方法ガイドを取得
        
        tools/listレスポンスに追加するダミーツールのdescriptionとして使用される。
        
        Args:
            server_type: サーバータイプ名
        
        Returns:
            使用方法ガイド文字列、設定されていない場合はNone
        """
        config = self.get_server_config(server_type)
        if not config:
            return None
        return config.get("usage_guide")


# グローバル設定インスタンス
settings = Settings()

# MCPサーバー設定インスタンス
mcp_config = MCPServerConfig(settings.config_file)
