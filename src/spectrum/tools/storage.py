import hashlib
from functools import lru_cache

import boto3
from botocore.config import Config

from spectrum.runtime_config import runtime_settings


@lru_cache
def storage():
    settings = runtime_settings()
    return boto3.client(
        "s3", endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name="us-east-1", config=Config(retries={"max_attempts": 0}, proxies={}),
    )


def initialize_storage() -> None:
    bucket = runtime_settings().s3_bucket
    buckets = storage().list_buckets()["Buckets"]
    if bucket not in {item["Name"] for item in buckets}:
        storage().create_bucket(Bucket=bucket)


def put_text(content: str, prefix: str) -> tuple[str, str]:
    body = content.encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    key = f"{prefix}/{digest}.md"
    storage().put_object(
        Bucket=runtime_settings().s3_bucket, Key=key, Body=body,
        ContentType="text/markdown; charset=utf-8", Metadata={"sha256": digest},
    )
    return key, digest
