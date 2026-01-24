"""
日時ユーティリティ

日時変換の共通関数
"""
from datetime import datetime
from typing import Union


def parse_datetime(dt: Union[str, datetime]) -> datetime:
    """
    文字列またはdatetimeオブジェクトをdatetimeに変換
    
    Args:
        dt: 日時文字列またはdatetimeオブジェクト
    
    Returns:
        datetimeオブジェクト
    """
    if isinstance(dt, datetime):
        return dt
    
    if isinstance(dt, str):
        # ISO 8601形式の文字列をパース
        # 'Z'サフィックスを'+00:00'に置換
        dt_str = dt.replace('Z', '+00:00')
        return datetime.fromisoformat(dt_str)
    
    raise ValueError(f"Cannot parse datetime from type {type(dt)}")
