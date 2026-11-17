#!/bin/sh
# Runs once LocalStack's own services are up (LocalStack executes every
# script in /etc/localstack/init/ready.d/ automatically). Creates the S3
# bucket, the main SQS queue, and its DLQ with a redrive policy - the same
# resources infra/storage.tf and infra/queues.tf create in AWS.
set -e

awslocal s3 mb s3://prompt-patrol-batches

# The presigned PUT is followed by the browser, cross-origin from the SPA's
# dev server - without a CORS rule the preflight has nothing to approve it
# with, and the browser blocks the PUT before it ever reaches LocalStack.
# Same rule as infra/storage.tf: the frontend origin, PUT, content-type.
awslocal s3api put-bucket-cors --bucket prompt-patrol-batches --cors-configuration '{
  "CORSRules": [
    {
      "AllowedOrigins": ["http://localhost:5173"],
      "AllowedMethods": ["PUT"],
      "AllowedHeaders": ["content-type"],
      "MaxAgeSeconds": 3000
    }
  ]
}'

DLQ_ARN=$(awslocal sqs create-queue --queue-name prompt-patrol-batches-dlq --query 'QueueUrl' --output text | xargs -I{} awslocal sqs get-queue-attributes --queue-url {} --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)

awslocal sqs create-queue \
  --queue-name prompt-patrol-batches \
  --attributes "{\"VisibilityTimeout\":\"600\",\"RedrivePolicy\":\"{\\\"deadLetterTargetArn\\\":\\\"$DLQ_ARN\\\",\\\"maxReceiveCount\\\":\\\"5\\\"}\"}"

echo "LocalStack bootstrap complete: bucket + queue (VisibilityTimeout=600) + DLQ (maxReceiveCount=5) ready."
