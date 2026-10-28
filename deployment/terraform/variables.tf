variable "region" {
  description = "AWS deployment region."
  type        = string
  default     = "ap-northeast-1"
}

variable "account_id" {
  description = "Expected AWS account; prevents deployment with the wrong login."
  type        = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "Supply a 12-digit AWS account ID."
  }
}

variable "bucket_name" {
  description = "Globally unique private artifact bucket name."
  type        = string
}

variable "name_prefix" {
  description = "Dedicated IAM resource name prefix."
  type        = string
  default     = "git-progressor"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,39}$", var.name_prefix))
    error_message = "Use 3-40 lowercase letters, digits or hyphens, starting with a letter."
  }
}
