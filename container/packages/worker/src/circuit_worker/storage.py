import io
import logging
import os
import tempfile
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from circuit_worker.config import config

logger = logging.getLogger(__name__)


class WorkerStorage:
    """Synchronous S3/MinIO client for the worker."""

    def __init__(self):
        self.client = boto3.client(
            "s3",
            endpoint_url=f"http{'s' if config.MINIO_SECURE else ''}://{config.MINIO_ENDPOINT}",
            aws_access_key_id=config.MINIO_ACCESS_KEY,
            aws_secret_access_key=config.MINIO_SECRET_KEY,
        )
        self.bucket = config.MINIO_BUCKET

    def ensure_bucket(self):
        """Create the bucket if it doesn't exist."""
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket)
            logger.info("Created bucket: %s", self.bucket)

    def download_file(self, key: str, local_path: str):
        """Download a file from MinIO to local path."""
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, key, local_path)
        logger.debug("Downloaded %s -> %s", key, local_path)

    def download_dataset_files(self, dataset_id: str, target_dir: str) -> list[str]:
        """Download all files for a dataset to a local directory.

        Returns list of local file paths.
        """
        prefix = f"uploads/{dataset_id}/"
        response = self.client.list_objects_v2(Bucket=self.bucket, Prefix=prefix)

        local_paths = []
        for obj in response.get("Contents", []):
            key = obj["Key"]
            filename = key.split("/")[-1]
            local_path = os.path.join(target_dir, filename)
            self.download_file(key, local_path)
            local_paths.append(local_path)

        return local_paths

    def upload_file(self, key: str, local_path: str, content_type: str = "application/octet-stream"):
        """Upload a local file to MinIO."""
        self.client.upload_file(
            local_path, self.bucket, key,
            ExtraArgs={"ContentType": content_type},
        )
        logger.debug("Uploaded %s -> %s", local_path, key)

    def upload_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream"):
        """Upload raw bytes to MinIO."""
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=io.BytesIO(data),
            ContentType=content_type,
        )

    def upload_directory(self, local_dir: str, prefix: str):
        """Recursively upload a local directory to MinIO under prefix."""
        local_dir = Path(local_dir)
        for path in local_dir.rglob("*"):
            if path.is_file():
                relative = path.relative_to(local_dir)
                key = f"{prefix}/{relative}"
                content_type = self._guess_content_type(path)
                self.upload_file(key, str(path), content_type)

    def _guess_content_type(self, path: Path) -> str:
        suffix = path.suffix.lower()
        return {
            ".json": "application/json",
            ".csv": "text/csv",
            ".parquet": "application/octet-stream",
            ".png": "image/png",
            ".md": "text/markdown",
            ".yaml": "application/x-yaml",
            ".yml": "application/x-yaml",
        }.get(suffix, "application/octet-stream")


storage = WorkerStorage()
