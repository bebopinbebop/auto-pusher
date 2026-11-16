"""One-shot, version-pinned S3 bundle verification with immutable reports."""
import hashlib
import json
import os
import signal
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from pydantic import Field, field_validator

from git_progressor.models import StrictModel
from git_progressor.services.bundles import MAX_BUNDLE_BYTES, verify_bundle


class VerificationRequest(StrictModel):
    policy: Literal["bundle-verification-v1"] = "bundle-verification-v1"
    bucket: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
    owner: str = Field(pattern=r"^[0-9]{12}$")
    key: str = Field(min_length=9, max_length=1024)
    version: str = Field(min_length=1, max_length=1024)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("key")
    @classmethod
    def bundle_prefix(cls, value: str) -> str:
        if (not value.startswith("bundles/") or "\\" in value
                or any(part in {"", ".", ".."} for part in value.split("/"))
                or any(ord(char) < 32 for char in value)):
            raise ValueError("invalid bundle key")
        return value

    @field_validator("version")
    @classmethod
    def pinned_version(cls, value: str) -> str:
        if value == "null" or any(ord(char) < 32 for char in value):
            raise ValueError("an explicit object version is required")
        return value

    @property
    def identity(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


def verify_s3_bundle(client, request: VerificationRequest) -> dict:
    """Retry-safe computation; conditional reports prevent overwriting evidence."""
    response = client.get_object(Bucket=request.bucket, Key=request.key,
                                 VersionId=request.version, ExpectedBucketOwner=request.owner)
    with closing(response["Body"]) as stream, TemporaryDirectory(prefix="cloud-bundle-") as tmp:
        if response.get("VersionId") != request.version:
            raise ValueError("object version mismatch")
        size = response.get("ContentLength")
        if type(size) is not int or not 0 < size <= MAX_BUNDLE_BYTES:
            raise ValueError("invalid bundle size")
        path = Path(tmp) / "bundle.zip"
        received = 0
        with path.open("wb") as output:
            while chunk := stream.read(min(1024 * 1024, MAX_BUNDLE_BYTES + 1 - received)):
                received += len(chunk)
                if received > MAX_BUNDLE_BYTES or received > size:
                    raise ValueError("bundle exceeds declared size")
                output.write(chunk)
        if received != size:
            raise ValueError("incomplete bundle download")
        result = verify_bundle(path, request.sha256)
    report = {"request_id": request.identity, "policy": request.policy,
              "status": "VERIFIED", "result": result}
    body = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    key = f"reports/verification/{request.identity}.json"
    try:
        client.put_object(Bucket=request.bucket, Key=key, Body=body,
                          ExpectedBucketOwner=request.owner, IfNoneMatch="*",
                          ContentType="application/json", ServerSideEncryption="AES256")
    except Exception as exc:
        # A concurrent identical run may have written the result already.
        error = getattr(exc, "response", {}).get("Error", {}).get("Code")
        if error != "PreconditionFailed":
            raise
        existing = client.get_object(Bucket=request.bucket, Key=key,
                                     ExpectedBucketOwner=request.owner)
        with closing(existing["Body"]) as stream:
            if stream.read(len(body) + 1) != body:
                raise ValueError("conflicting verification report") from exc
    return report


def main() -> None:
    def expired(signum, frame):
        raise TimeoutError("verification deadline exceeded")

    try:
        # Linux container entry point: fixed ten-minute execution ceiling.
        signal.signal(signal.SIGALRM, expired)
        signal.alarm(600)
        import boto3
        from botocore.config import Config

        raw = os.environ.get("GIT_PROGRESSOR_VERIFICATION_REQUEST", "")
        if len(raw.encode()) > 8192:
            raise ValueError("request too large")
        request = VerificationRequest.model_validate_json(raw)
        client = boto3.client("s3", config=Config(connect_timeout=10, read_timeout=30,
                              retries={"mode": "standard", "total_max_attempts":3}))
        report = verify_s3_bundle(client, request)
        print(json.dumps({"status": "VERIFIED", "request_id": report["request_id"]}))
    except Exception as exc:
        # SDK and validation messages can contain untrusted input; never print them.
        print(json.dumps({"status": "FAILED", "error_type": type(exc).__name__}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
