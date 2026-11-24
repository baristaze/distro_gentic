# The prompt cache's alarm reads the metrics the runner's settled-call line
# is filtered into, from the runner's own log group, and fires on the
# cache's read share of every prompt token below its threshold, an input
# with a default. Runs offline: `terraform test` in this folder.

mock_provider "aws" {}

variables {
  environment                = "test"
  alarm_email                = "alarms@example.test"
  load_balancer_arn_suffix   = "app/acme-test/0123456789abcdef"
  target_group_arn_suffix    = "targetgroup/acme-test-api/0123456789abcdef"
  database_identifier        = "acme-test"
  cluster_name               = "acme-test"
  api_log_group_name         = "/acme/test/api"
  maintenance_log_group_name = "/acme/test/maintenance"
  runner_log_group_name      = "/acme/test/agent-session-runner"
  queue_names                = ["acme-test-webhooks"]
  service_names              = ["api", "maintenance", "agent-session-runner"]
}

run "each_prompt_token_field_of_the_runners_line_is_a_metric" {
  command = plan

  assert {
    condition = toset(keys(aws_cloudwatch_log_metric_filter.prompt_tokens)) == toset([
      "input_tokens", "cache_read_tokens", "cache_write_tokens",
    ])
    error_message = "A filter per prompt token field of the settled call's line: input, cache read, and cache write."
  }

  assert {
    condition = alltrue([
      for field, filter in aws_cloudwatch_log_metric_filter.prompt_tokens :
      filter.log_group_name == "/acme/test/agent-session-runner"
      && filter.pattern == "{ $.model_call.${field} = * }"
      && filter.metric_transformation[0].name == "acme_model_call_${field}"
      && filter.metric_transformation[0].namespace == "Acme"
      && filter.metric_transformation[0].value == "$.model_call.${field}"
    ])
    error_message = "A filter does not turn its field of the runner's settled-call line into its metric."
  }
}

run "the_alarm_fires_on_the_cache_read_share_below_its_default" {
  command = plan

  assert {
    condition = (
      aws_cloudwatch_metric_alarm.prompt_cache_read_share.alarm_name == "acme-test-prompt-cache-read-share"
      && aws_cloudwatch_metric_alarm.prompt_cache_read_share.comparison_operator == "LessThanThreshold"
      && aws_cloudwatch_metric_alarm.prompt_cache_read_share.threshold == 50
      && aws_cloudwatch_metric_alarm.prompt_cache_read_share.evaluation_periods == 3
      && aws_cloudwatch_metric_alarm.prompt_cache_read_share.treat_missing_data == "notBreaching"
      && length(aws_cloudwatch_metric_alarm.prompt_cache_read_share.alarm_actions) == 1
      && length(aws_cloudwatch_metric_alarm.prompt_cache_read_share.ok_actions) == 1
    )
    error_message = "The alarm fires below half the prompt read from the cache, for three periods, goes to the topic, and reads no quiet period as a fall."
  }

  assert {
    condition = one([
      for query in aws_cloudwatch_metric_alarm.prompt_cache_read_share.metric_query :
      query.expression if query.return_data == true
    ]) == "100 * cache_read_tokens / (input_tokens + cache_read_tokens + cache_write_tokens)"
    error_message = "The alarm reads the cache's reads as a percentage of every prompt token."
  }

  assert {
    condition = toset([
      for query in aws_cloudwatch_metric_alarm.prompt_cache_read_share.metric_query :
      "${query.id}=${query.metric[0].metric_name}/${query.metric[0].stat}/${query.metric[0].period}"
      if length(query.metric) > 0
      ]) == toset([
      for filter in aws_cloudwatch_log_metric_filter.prompt_tokens :
      "${replace(filter.metric_transformation[0].name, "acme_model_call_", "")}=${filter.metric_transformation[0].name}/Sum/3600"
    ])
    error_message = "The alarm sums each metric the filters write, over an hour, and reads every one."
  }

  assert {
    condition     = contains(output.alarm_names, "acme-test-prompt-cache-read-share")
    error_message = "The prompt cache alarm is among the environment's alarms."
  }
}

run "the_threshold_is_an_input" {
  command = plan

  variables {
    prompt_cache_read_percent   = 30
    prompt_cache_period_seconds = 900
  }

  assert {
    condition = (
      aws_cloudwatch_metric_alarm.prompt_cache_read_share.threshold == 30
      && alltrue([
        for query in aws_cloudwatch_metric_alarm.prompt_cache_read_share.metric_query :
        query.metric[0].period == 900 if length(query.metric) > 0
      ])
    )
    error_message = "An environment passes another threshold and period."
  }
}
