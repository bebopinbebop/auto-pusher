variable "verification_image" {
  description = "Optional digest-pinned ECR verifier image; null disables one-shot infrastructure."
  type        = string
  default     = null
  validation {
    condition     = var.verification_image == null ? true : can(regex("^[0-9]{12}\\.dkr\\.ecr\\.us-east-1\\.amazonaws\\.com/git-progressor-worker@sha256:[0-9a-f]{64}$", var.verification_image))
    error_message = "Use the private US East 1 worker repository with an exact SHA-256 digest."
  }
}

locals {
  verifier_enabled = var.verification_image != null
  ecs_trust = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = var.account_id }
        ArnLike      = { "aws:SourceArn" = "arn:aws:ecs:${var.region}:${var.account_id}:*" }
      }
    }]
  })
}

resource "aws_vpc" "verifier" {
  count                = local.verifier_enabled ? 1 : 0
  cidr_block           = "10.78.0.0/24"
  enable_dns_support   = true
  enable_dns_hostnames = true
}
resource "aws_subnet" "verifier" {
  count      = local.verifier_enabled ? 1 : 0
  vpc_id     = aws_vpc.verifier[0].id
  cidr_block = "10.78.0.0/26"
}
resource "aws_internet_gateway" "verifier" {
  count  = local.verifier_enabled ? 1 : 0
  vpc_id = aws_vpc.verifier[0].id
}
resource "aws_route_table" "verifier" {
  count  = local.verifier_enabled ? 1 : 0
  vpc_id = aws_vpc.verifier[0].id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.verifier[0].id
  }
}
resource "aws_route_table_association" "verifier" {
  count          = local.verifier_enabled ? 1 : 0
  subnet_id      = aws_subnet.verifier[0].id
  route_table_id = aws_route_table.verifier[0].id
}
resource "aws_security_group" "verifier" {
  count       = local.verifier_enabled ? 1 : 0
  name_prefix = "git-progressor-verifier-"
  vpc_id      = aws_vpc.verifier[0].id
  description = "One-shot verifier: no inbound connections, HTTPS outbound"
  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
resource "aws_ecs_cluster" "verifier" {
  count = local.verifier_enabled ? 1 : 0
  name  = "git-progressor-verifier"
}
resource "aws_cloudwatch_log_group" "verifier" {
  count             = local.verifier_enabled ? 1 : 0
  name              = "/git-progressor/verifier"
  retention_in_days = 7
}
resource "aws_iam_role" "verifier_execution" {
  count              = local.verifier_enabled ? 1 : 0
  name               = "git-progressor-verifier-execution"
  assume_role_policy = local.ecs_trust
}
resource "aws_iam_role_policy" "verifier_execution" {
  count = local.verifier_enabled ? 1 : 0
  role  = aws_iam_role.verifier_execution[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
      { Effect = "Allow", Action = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"], Resource = aws_ecr_repository.worker.arn },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.verifier[0].arn}:*" }
    ]
  })
}
resource "aws_iam_role" "verifier" {
  count              = local.verifier_enabled ? 1 : 0
  name               = "git-progressor-verifier"
  assume_role_policy = local.ecs_trust
}
resource "aws_iam_role_policy" "verifier" {
  count = local.verifier_enabled ? 1 : 0
  role  = aws_iam_role.verifier[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObjectVersion"], Resource = "${aws_s3_bucket.artifacts.arn}/bundles/*" },
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = "${aws_s3_bucket.artifacts.arn}/reports/verification/*" }
    ]
  })
}
resource "aws_ecs_task_definition" "verifier" {
  count                    = local.verifier_enabled ? 1 : 0
  family                   = "git-progressor-verifier"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.verifier_execution[0].arn
  task_role_arn            = aws_iam_role.verifier[0].arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
  volume { name = "scratch" }
  container_definitions = jsonencode([{
    name            = "verifier", image = var.verification_image, essential = true,
    user            = "10001:10001", readonlyRootFilesystem = true,
    mountPoints     = [{ sourceVolume = "scratch", containerPath = "/scratch", readOnly = false }],
    linuxParameters = { capabilities = { drop = ["ALL"] } },
    logConfiguration = { logDriver = "awslogs", options = {
      awslogs-group  = aws_cloudwatch_log_group.verifier[0].name,
      awslogs-region = var.region, awslogs-stream-prefix = "verification"
    } }
  }])
}

output "verification_runtime" {
  value = local.verifier_enabled ? {
    cluster         = aws_ecs_cluster.verifier[0].arn
    task_definition = aws_ecs_task_definition.verifier[0].arn
    subnet          = aws_subnet.verifier[0].id
    security_group  = aws_security_group.verifier[0].id
  } : null
}
