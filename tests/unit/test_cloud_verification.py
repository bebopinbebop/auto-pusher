from io import BytesIO

import pytest
from pydantic import ValidationError
from test_preparation import worker_setup

from git_progressor.cloud.verify import VerificationRequest, verify_s3_bundle
from git_progressor.exceptions import InvalidPlanError
from git_progressor.services.bundles import export_bundle


class Conflict(Exception):
    response = {"Error": {"Code": "PreconditionFailed"}}


class Store:
    def __init__(self, data):
        self.data, self.report, self.reads = data, None, []
        self.size = len(data)
        self.version = "version-1"

    def get_object(self, **kwargs):
        self.reads.append(kwargs)
        if kwargs["Key"].startswith("reports/"):
            return {"Body": BytesIO(self.report)}
        return {"Body": BytesIO(self.data), "ContentLength": self.size,
                "VersionId": self.version}

    def put_object(self, **kwargs):
        assert kwargs["IfNoneMatch"] == "*"
        if self.report is not None:
            raise Conflict()
        self.report = kwargs["Body"]


def prepared(tmp_path):
    worker, job, _, _, _ = worker_setup(tmp_path)
    worker.run(job)
    path = tmp_path / "bundle.zip"
    result = export_bundle(worker, job, path)
    request = VerificationRequest(bucket="test-bucket", owner="123456789012",
                                  key="bundles/test.zip", version="version-1",
                                  sha256=result["sha256"])
    return Store(path.read_bytes()), request


def test_pinned_version_replay_and_duplicate_report(tmp_path):
    store, request = prepared(tmp_path)
    report = verify_s3_bundle(store, request)
    assert report["result"]["stages"] == 5
    assert store.reads[0]["VersionId"] == request.version
    assert store.reads[0]["ExpectedBucketOwner"] == request.owner
    assert verify_s3_bundle(store, request) == report
    store.report = b"different"
    with pytest.raises(ValueError, match="conflicting"):
        verify_s3_bundle(store, request)


@pytest.mark.parametrize("change", [{"version": "null"}, {"key": "uploads/test.zip"},
                                   {"key": "bundles/../test"}, {"sha256": "bad"}])
def test_bad_reference_rejected(change):
    values = dict(bucket="test-bucket", owner="123456789012", key="bundles/test.zip",
                  version="version-1", sha256="0" * 64)
    with pytest.raises(ValidationError):
        VerificationRequest(**(values | change))


@pytest.mark.parametrize("fault", ["version", "size", "truncated", "checksum"])
def test_invalid_download_never_writes_success(tmp_path, fault):
    store, request = prepared(tmp_path)
    if fault == "version":
        store.version = "different"
    elif fault == "size":
        store.size = 101 * 1024 * 1024
    elif fault == "truncated":
        store.size += 1
    else:
        store.data = b"x" + store.data[1:]
    with pytest.raises((ValueError, InvalidPlanError)):
        verify_s3_bundle(store, request)
    assert store.report is None
