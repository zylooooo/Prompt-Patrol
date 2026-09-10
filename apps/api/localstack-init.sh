#!/bin/sh
# Runs once LocalStack's own services are up (LocalStack executes every
# script in /etc/localstack/init/ready.d/ automatically). Creates the S3
# bucket, the main SQS queue, and its DLQ with a redrive policy - the same
# resources a real deploy creates via infra-as-code, just done by hand here
# since local dev has no infra/ directory to run.
set -e

awslocal s3 mb s3://prompt-patrol-batches

# The presigned PUT is followed by the browser, cross-origin from the SPA's
# dev server - without a CORS rule the preflight has nothing to approve it
# with, and the browser blocks the PUT before it ever reaches LocalStack.
# Real S3 needs the same rule (via infra-as-code), scoped to the real
# frontend origin instead of "*".
awslocal s3api put-bucket-cors --bucket prompt-patrol-batches --cors-configuration '{
  "CORSRules": [
    {
      "AllowedOrigins": ["*"],
      "AllowedMethods": ["PUT", "GET", "HEAD"],
      "AllowedHeaders": ["*"],
      "ExposeHeaders": ["ETag"],
      "MaxAgeSeconds": 3000
    }
  ]
}'

DLQ_ARN=$(awslocal sqs create-queue --queue-name prompt-patrol-batches-dlq --query 'QueueUrl' --output text | xargs -I{} awslocal sqs get-queue-attributes --queue-url {} --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)

awslocal sqs create-queue \
  --queue-name prompt-patrol-batches \
  --attributes "{\"RedrivePolicy\":\"{\\\"deadLetterTargetArn\\\":\\\"$DLQ_ARN\\\",\\\"maxReceiveCount\\\":\\\"3\\\"}\"}"

echo "LocalStack bootstrap complete: bucket + queue + DLQ (maxReceiveCount=3) ready."
