output "artifact_bucket" {
  value = aws_s3_bucket.artifacts.id
}

output "publisher_instance_profile" {
  value = try(aws_iam_instance_profile.publisher[0].name, null)
}

output "publisher_role_arn" {
  value = try(aws_iam_role.publisher[0].arn, null)
}
