# The session runner holds what its loop needs and nothing more (ADR 2026):
# its task role reads a tenant's own secrets and writes none, reaches no
# inbound queue, and holds neither the purge login nor an identity
# provider's key. Each policy below takes a name of its own for the plan,
# since a mock's ARN is unknown until an apply. Runs offline under mock
# providers: `terraform test` in this folder.

mock_provider "aws" {
  mock_data "aws_partition" {
    defaults = { partition = "aws", dns_suffix = "amazonaws.com" }
  }
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_region" {
    defaults = { name = "us-west-2", region = "us-west-2" }
  }
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  mock_resource "aws_acm_certificate" {
    override_during = plan
    defaults = {
      arn = "arn:aws:acm:us-east-1:123456789012:certificate/test"
      domain_validation_options = [
        { domain_name = "example.test", resource_record_name = "_x.example.test.", resource_record_type = "CNAME", resource_record_value = "_y.acm-validations.aws." },
      ]
    }
  }
  mock_data "aws_availability_zones" {
    defaults = { names = ["us-west-2a", "us-west-2b"] }
  }
}

mock_provider "aws" {
  alias = "us_east_1"

  mock_resource "aws_acm_certificate" {
    override_during = plan
    defaults = {
      arn = "arn:aws:acm:us-east-1:123456789012:certificate/test"
      domain_validation_options = [
        { domain_name = "example.test", resource_record_name = "_x.example.test.", resource_record_type = "CNAME", resource_record_value = "_y.acm-validations.aws." },
      ]
    }
  }
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
}

override_resource {
  target          = module.environment.module.queue.aws_iam_policy.use
  override_during = plan
  values          = { arn = "arn:aws:iam::123456789012:policy/queues" }
}

override_resource {
  target          = module.environment.module.buckets.aws_iam_policy.use
  override_during = plan
  values          = { arn = "arn:aws:iam::123456789012:policy/buckets" }
}

override_resource {
  target          = module.environment.module.keys.aws_iam_policy.use
  override_during = plan
  values          = { arn = "arn:aws:iam::123456789012:policy/keys" }
}

override_resource {
  target          = module.environment.module.secrets.aws_iam_policy.application
  override_during = plan
  values          = { arn = "arn:aws:iam::123456789012:policy/secrets" }
}

override_resource {
  target          = module.environment.module.secrets.aws_iam_policy.runner
  override_during = plan
  values          = { arn = "arn:aws:iam::123456789012:policy/secrets-runner" }
}

override_resource {
  target          = module.environment.module.secrets.aws_iam_policy.operator_tokens
  override_during = plan
  values          = { arn = "arn:aws:iam::123456789012:policy/operator-tokens" }
}

variables {
  api_image            = "123456789012.dkr.ecr.us-west-2.amazonaws.com/acme-api@sha256:0000000000000000000000000000000000000000000000000000000000000000"
  maintenance_image    = "123456789012.dkr.ecr.us-west-2.amazonaws.com/acme-maintenance@sha256:0000000000000000000000000000000000000000000000000000000000000000"
  session_runner_image = "123456789012.dkr.ecr.us-west-2.amazonaws.com/acme-session-runner@sha256:0000000000000000000000000000000000000000000000000000000000000000"
  api_domain_name      = "api.staging.example.test"
  app_domain_name      = "app.staging.example.test"
  alarm_email          = "alarms@example.test"
}

run "the_runner_holds_its_own_reads_and_no_queue" {
  command = plan

  assert {
    condition = toset(module.environment.session_runner_access.policy_arns) == toset([
      "arn:aws:iam::123456789012:policy/buckets",
      "arn:aws:iam::123456789012:policy/keys",
      "arn:aws:iam::123456789012:policy/secrets-runner",
    ])
    error_message = "the runner's task role attaches the buckets, the key, and its own secrets' reads, and nothing else"
  }

  assert {
    condition     = !contains(module.environment.session_runner_access.policy_arns, "arn:aws:iam::123456789012:policy/queues")
    error_message = "the runner reaches no inbound queue: its work is a work item on its loop lane"
  }

  assert {
    condition     = !contains(module.environment.session_runner_access.policy_arns, "arn:aws:iam::123456789012:policy/secrets")
    error_message = "the runner never holds the application grant, which writes and deletes a tenant's secrets"
  }

  assert {
    condition = module.environment.session_runner_access.secret_names == tolist([
      "ACME_ANTHROPIC_API_KEY",
      "ACME_DATABASE_SYSTEM_URL",
      "ACME_DATABASE_URL",
      "ACME_LAUNCHDARKLY_SDK_KEY",
      "ACME_OPENAI_API_KEY",
      "ACME_SENTRY_DSN",
    ])
    error_message = "the runner is injected with the serving logins, the error tracker's DSN, the flags' SDK key (the infra root it boots refuses the launchdarkly backend without it), and the platform's model keys: no purge login, no identity provider's key"
  }
}
