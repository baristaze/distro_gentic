# The session runner's grant reads a tenant's own secrets and nothing else:
# no write, no delete, and nothing outside the application prefix's org/
# part, where the platform's own credentials and the operator tokens live.
# The platform's model keys exist from the first apply, holding "off".
# Runs offline: `terraform test` in this folder.

mock_provider "aws" {
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_partition" {
    defaults = { partition = "aws" }
  }
  mock_data "aws_region" {
    defaults = { region = "us-west-2" }
  }
}

variables {
  environment               = "staging"
  prefix                    = "acme/staging/"
  database_password         = "not-a-secret"
  database_password_version = 1
  database_username         = "acme"
  database_address          = "db.example.test"
  database_port             = 5432
  database_name             = "acme"
  destroyable               = false
}

run "the_runner_reads_a_tenants_secrets_and_writes_none" {
  command = plan

  assert {
    condition     = length(data.aws_iam_policy_document.runner.statement) == 1
    error_message = "the runner's grant is one statement"
  }

  assert {
    condition = toset(data.aws_iam_policy_document.runner.statement[0].actions) == toset([
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
    ])
    error_message = "the runner reads and describes; it never creates, writes, or deletes a secret"
  }

  assert {
    condition = toset(data.aws_iam_policy_document.runner.statement[0].resources) == toset([
      "arn:aws:secretsmanager:us-west-2:123456789012:secret:acme/staging/app/org/*",
    ])
    error_message = "the runner reads under the application prefix's org/ part alone"
  }

  assert {
    condition     = toset(keys(aws_secretsmanager_secret.model_key)) == toset(["anthropic_api_key", "openai_api_key"]) && alltrue([for key in aws_secretsmanager_secret.model_key : !startswith(key.name, "acme/staging/app/")])
    error_message = "one model key per provider, named outside the application prefix"
  }

  assert {
    condition     = alltrue([for version in aws_secretsmanager_secret_version.model_key : version.secret_string == "off"])
    error_message = "a model key holds \"off\" until a person writes one, so nothing is spent on the platform's account before"
  }
}
