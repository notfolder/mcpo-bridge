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
    
    def create_job(self, server_type: str, session_key: Optional[str] = None) -> Tuple[str, Path]:
        """
        新しいジョブを作成
        
        Args:
            server_type: MCPサーバータイプ
            session_key: セッションキー(user:xxx:chat:yyyまたはuser:xxx形式)
        
        Returns:
            (job_id, job_dir) のタプル
        """
        # UUID v4でジョブIDを生成
        job_id = str(uuid.uuid4())
        
        logger.info(f"[CREATE_JOB] Creating job {job_id} for server_type={server_type}, session_key={session_key}")
        
        # ジョブディレクトリを作成
        job_dir = self.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"[CREATE_JOB] Created job directory: {job_dir}")
        
        # メタデータを作成
        metadata = JobMetadata(
            job_id=job_id,
            server_type=server_type,
            session_key=session_key
        )
        
        # メタデータを保存
        self.save_metadata(job_id, metadata)
        
        logger.info(f"[CREATE_JOB] Successfully created job: {job_id}")
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
        
        logger.debug(f"[SAVE_METADATA] Saving metadata for job {job_id} to {metadata_file}")
        
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata.model_dump(mode='json'), f, indent=2, ensure_ascii=False)
        
        logger.debug(f"[SAVE_METADATA] Successfully saved metadata for job {job_id}")
    
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
        
        logger.debug(f"[LOAD_METADATA] Loading metadata for job {job_id} from {metadata_file}")
        
        if not metadata_file.exists():
            logger.warning(f"[LOAD_METADATA] Metadata file not found for job {job_id}")
            return None
        
        try:
            with open(metadata_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            metadata = JobMetadata(**data)
            logger.debug(f"[LOAD_METADATA] Successfully loaded metadata for job {job_id}: status={metadata.status}")
            return metadata
        except Exception as e:
            logger.error(f"[LOAD_METADATA] Failed to load metadata for job {job_id}: {e}", exc_info=True)
            return None
    
    def update_status(self, job_id: str, status: JobStatus, error: Optional[str] = None):
        """
        ジョブステータスを更新
        
        Args:
            job_id: ジョブID
            status: 新しいステータス
            error: エラーメッセージ（オプション）
        """
        logger.info(f"[UPDATE_STATUS] Job {job_id}: {status}" + (f" - {error}" if error else ""))
        
        metadata = self.load_metadata(job_id)
        if metadata:
            metadata.status = status
            if error:
                metadata.error = error
            self.save_metadata(job_id, metadata)
            logger.debug(f"[UPDATE_STATUS] Successfully updated job {job_id} status to {status}")
        else:
            logger.warning(f"[UPDATE_STATUS] Could not load metadata for job {job_id}, status update skipped")
    
    def save_request(self, job_id: str, request_data: dict):
        """
        リクエストデータを保存
        
        Args:
            job_id: ジョブID
            request_data: リクエストデータ
        """
        job_dir = self.get_job_dir(job_id)
        request_file = job_dir / "request.json"
        
        logger.debug(f"[SAVE_REQUEST] Saving request for job {job_id}")
        logger.debug(f"[SAVE_REQUEST] Request method: {request_data.get('method')}")
        
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
        
        logger.debug(f"[SAVE_RESPONSE] Saving response for job {job_id}")
        
        with open(response_file, 'w', encoding='utf-8') as f:
            json.dump(response_data, f, indent=2, ensure_ascii=False)
        
        # メタデータも更新
        metadata = self.load_metadata(job_id)
        if metadata:
            metadata.response = response_data
            self.save_metadata(job_id, metadata)


# グローバルジョブマネージャーインスタンス
job_manager = JobManager()
