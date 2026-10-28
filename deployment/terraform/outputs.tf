output "artifact_bucket" {
  value = aws_s3_bucket.artifacts.id
}

output "publisher_instance_profile" {
  value = aws_iam_instance_profile.publisher.name
}

output "publisher_role_arn" {
  value = aws_iam_role.publisher.arn
}
