# Application releases only. Uploaded projects must never become container images.
resource "aws_ecr_repository" "worker" {
  name                 = "${var.name_prefix}-worker"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

output "worker_repository_url" {
  description = "Push tested worker releases here; deployments should pin image digests."
  value       = aws_ecr_repository.worker.repository_url
}
