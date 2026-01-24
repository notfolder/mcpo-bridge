"""
ジョブ管理モジュール

ジョブIDの発行、ディレクトリの作成、メタデータ管理を行う
"""
import uuid
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple

from src.models.job import JobMetadata, JobStatus
from src.core.config import settings

logger = logging.getLogger(__name__)


class JobManager:
    """
    ジョブ管理クラス
    ジョブディレクトリとメタデータの管理を行う
    """
    
    def __init__(self):
        """初期化"""
        self.jobs_dir = Path(settings.jobs_dir)
        self._ensure_jobs_dir()
    
    def _ensure_jobs_dir(self):
        """
        ジョブディレクトリの存在を確認し、必要に応じて作成
        """
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Jobs directory ensured: {self.jobs_dir}")
    
    def create_job(self, server_type: str, client_ip: Optional[str] = None) -> Tuple[str, Path]:
        """
        新しいジョブを作成
        
        Args:
            server_type: MCPサーバータイプ
            client_ip: クライアントIPアドレス
        
        Returns:
            (job_id, job_dir) のタプル
        """
        # UUID v4でジョブIDを生成
        job_id = str(uuid.uuid4())
        
        # ジョブディレクトリを作成
        job_dir = self.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        
        # メタデータを作成
        metadata = JobMetadata(
            job_id=job_id,
            server_type=server_type,
            client_ip=client_ip
        )
        
        # メタデータを保存
        self.save_metadata(job_id, metadata)
        
        logger.info(f"Created job: {job_id} for server type: {server_type}")
        return job_id, job_dir
    
    def get_job_dir(self, job_id: str) -> Path:
        """
        ジョブディレクトリのパスを取得
        
        Args:
            job_id: ジョブID
        
        Returns:
            ジョブディレクトリのパス
        """
        return self.jobs_dir / job_id
    
    def save_metadata(self, job_id: str, metadata: JobMetadata):
        """
        メタデータをファイルに保存
        
        Args:
            job_id: ジョブID
            metadata: メタデータオブジェクト
        """
        job_dir = self.get_job_dir(job_id)
        metadata_file = job_dir / "metadata.json"
        
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata.model_dump(mode='json'), f, indent=2, ensure_ascii=False)
    
    def load_metadata(self, job_id: str) -> Optional[JobMetadata]:
        """
        メタデータをファイルから読み込む
        
        Args:
            job_id: ジョブID
        
        Returns:
            メタデータオブジェクト、存在しない場合はNone
        """
        job_dir = self.get_job_dir(job_id)
        metadata_file = job_dir / "metadata.json"
        
        if not metadata_file.exists():
            return None
        
        try:
            with open(metadata_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return JobMetadata(**data)
        except Exception as e:
            logger.error(f"Failed to load metadata for job {job_id}: {e}")
            return None
    
    def update_status(self, job_id: str, status: JobStatus, error: Optional[str] = None):
        """
        ジョブステータスを更新
        
        Args:
            job_id: ジョブID
            status: 新しいステータス
            error: エラーメッセージ（オプション）
        """
        metadata = self.load_metadata(job_id)
        if metadata:
            metadata.status = status
            if error:
                metadata.error = error
            self.save_metadata(job_id, metadata)
            logger.info(f"Updated job {job_id} status to {status}")
    
    def save_request(self, job_id: str, request_data: dict):
        """
        リクエストデータを保存
        
        Args:
            job_id: ジョブID
            request_data: リクエストデータ
        """
        job_dir = self.get_job_dir(job_id)
        request_file = job_dir / "request.json"
        
        with open(request_file, 'w', encoding='utf-8') as f:
            json.dump(request_data, f, indent=2, ensure_ascii=False)
        
        # メタデータも更新
        metadata = self.load_metadata(job_id)
        if metadata:
            metadata.request = request_data
            self.save_metadata(job_id, metadata)
    
    def save_response(self, job_id: str, response_data: dict):
        """
        レスポンスデータを保存
        
        Args:
            job_id: ジョブID
            response_data: レスポンスデータ
        """
        job_dir = self.get_job_dir(job_id)
        response_file = job_dir / "response.json"
        
        with open(response_file, 'w', encoding='utf-8') as f:
            json.dump(response_data, f, indent=2, ensure_ascii=False)
        
        # メタデータも更新
        metadata = self.load_metadata(job_id)
        if metadata:
            metadata.response = response_data
            self.save_metadata(job_id, metadata)


# グローバルジョブマネージャーインスタンス
job_manager = JobManager()
