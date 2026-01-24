"""
ユーティリティ関数

クライアントIP抽出などの汎用関数
"""
import ipaddress
import logging
from typing import Optional
from fastapi import Request

logger = logging.getLogger(__name__)


def extract_client_ip(request: Request) -> str:
    """
    リクエストからクライアントIPアドレスを抽出
    
    優先順位:
    1. X-Forwarded-For ヘッダー（最初のIP）
    2. X-Real-IP ヘッダー
    3. request.client.host
    4. "unknown"
    
    Args:
        request: FastAPIリクエストオブジェクト
    
    Returns:
        クライアントIPアドレス文字列
    """
    # X-Forwarded-For ヘッダーをチェック
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # カンマ区切りの最初のIPを取得
        ip = forwarded_for.split(',')[0].strip()
        if validate_ip(ip):
            return ip
    
    # X-Real-IP ヘッダーをチェック
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        ip = real_ip.strip()
        if validate_ip(ip):
            return ip
    
    # request.client.hostをチェック
    if request.client and request.client.host:
        ip = request.client.host
        if validate_ip(ip):
            return ip
    
    # フォールバック
    logger.warning("Could not extract valid client IP, using 'unknown'")
    return "unknown"


def validate_ip(ip_str: str) -> bool:
    """
    IPアドレスの妥当性を検証
    
    Args:
        ip_str: IPアドレス文字列
    
    Returns:
        妥当な場合True
    """
    try:
        ipaddress.ip_address(ip_str)
        return True
    except ValueError:
        return False
