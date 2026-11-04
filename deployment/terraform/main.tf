resource "aws_s3_bucket" "artifacts" {
  bucket        = var.bucket_name
  force_destroy = false
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_policy" "tls" {
  bucket = aws_s3_bucket.artifacts.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.artifacts.arn, "${aws_s3_bucket.artifacts.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

resource "aws_iam_role" "publisher" {
  count = var.enable_legacy_ec2_role ? 1 : 0
  name  = "${var.name_prefix}-publisher"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "artifacts" {
  count = var.enable_legacy_ec2_role ? 1 : 0
  name  = "prepared-bundles-and-reports"
  role  = aws_iam_role.publisher[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.artifacts.arn
        Condition = {
          StringLike = { "s3:prefix" = ["bundles/", "bundles/*", "reports/", "reports/*"] }
        }
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:GetObjectVersion"]
        Resource = "${aws_s3_bucket.artifacts.arn}/bundles/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${aws_s3_bucket.artifacts.arn}/reports/*"
      }
    ]
  })
}

resource "aws_iam_instance_profile" "publisher" {
  count = var.enable_legacy_ec2_role ? 1 : 0
  name  = "${var.name_prefix}-publisher"
  role  = aws_iam_role.publisher[0].name
}

moved {
  from = aws_iam_role.publisher
  to   = aws_iam_role.publisher[0]
}

moved {
  from = aws_iam_role_policy.artifacts
  to   = aws_iam_role_policy.artifacts[0]
}

moved {
  from = aws_iam_instance_profile.publisher
  to   = aws_iam_instance_profile.publisher[0]
}
