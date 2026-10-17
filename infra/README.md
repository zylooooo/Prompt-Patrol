# infra

The single Terraform root for Prompt Patrol's AWS deployment. One account
(`420974348257`), one environment, Region `ap-southeast-1`. State lives at
`s3://prompt-patrol-tfstate-420974348257/app/terraform.tfstate`, locked with
S3's native lockfile (no DynamoDB table).

## Layout

One root, one state, files split by area per the
[Terraform style guide](https://developer.hashicorp.com/terraform/language/style#file-names):

| File | Holds |
|---|---|
| `terraform.tf` | `required_version`, `required_providers` |
| `backend.tf` | S3 backend |
| `providers.tf` | AWS provider, account guard, default tags |
| `variables.tf` / `terraform.tfvars` | inputs / their committed values |
| `network.tf` | VPC, subnets, NAT, route tables |
| `endpoints.tf` | VPC endpoints and their security group |
| `tests/` | `terraform test` files (mock provider, run in CI) |

Later steps add one file per area (`database.tf`, `compute.tf`, `edge.tf`).
A module goes in `modules/` only when it is a real repeated concept. The
planned one is `modules/fargate-service/`, used by the API, Worker and
detector. A module used once is just a folder of resources with extra
input/output wiring. Add `outputs.tf` when something needs an output.

## Prerequisites

- Terraform `~> 1.16` (CI pins `1.16.x`).
- AWS CLI v2 with the `prompt-patrol` profile, signed in through IAM Identity
  Center: `aws login --profile prompt-patrol`. Sessions expire; re-run it when
  Terraform reports expired or missing credentials.
- `AWS_PROFILE=prompt-patrol` set as a user environment variable (set it once,
  then restart your editor so its terminals inherit it). The provider and
  backend deliberately have no `profile` argument: CI supplies OIDC
  credentials through the environment instead.

The S3 backend reads `aws login` sessions directly (Terraform ≥ 1.16, AWS
provider ≥ 6.23). No `credential_process` fallback profile is needed.

```powershell
terraform init
terraform plan
terraform apply
```

`allowed_account_ids` in `providers.tf` makes any run against another account
fail before it touches anything.

## Pausing the environment

Everything billed by the hour (today: the NAT gateway, its Elastic IP and the
five interface endpoints in both zones, about $4.70/day) is gated on `paused`. To stop paying
for it, set this in `terraform.tfvars`, apply, and commit:

```hcl
paused = true
```

Set it back to `false` and apply to resume (about 5 minutes). Free resources
(VPC, subnets, route tables, internet gateway, S3 gateway endpoint, security
groups) stay up either way, so nothing that depends on them is rebuilt.

- Change it in `terraform.tfvars`, never with `-var`: the CD apply reads the
  committed file, so a `-var` pause would be undone by the next deploy.
- Resuming gets a new NAT IP address. Nothing allowlists it today.
- New hourly-billed resources must follow the same rule (`count` or `for_each`
  on `var.paused`). Stateful ones (RDS) don't; they need their own plan.

## The state bucket is not managed here

The bucket was created once by hand in the console and is deliberately outside
Terraform state. The backend can't be managed by the configuration that stores
its state in it without a separate bootstrap root or an import, and for one
account that's not worth it. Side benefit: `terraform destroy` can never delete
the bucket.

So nothing detects drift on it. If someone changes it in the console, compare it
against this checklist:

| Setting                             | Expected                                                                                  |
| ----------------------------------- | ----------------------------------------------------------------------------------------- |
| Region                              | `ap-southeast-1`                                                                          |
| Versioning                          | Enabled                                                                                   |
| Lifecycle rule `state-housekeeping` | noncurrent versions expire after 90 days; incomplete multipart uploads abort after 7 days |
| Default encryption                  | SSE-S3 (`AES256`)                                                                         |
| Block Public Access                 | all four settings on                                                                      |
| Object Ownership                    | Bucket owner enforced (ACLs disabled)                                                     |
| Bucket policy                       | denies `s3:*` when `aws:SecureTransport` is `false`                                       |
| Tags                                | `Project=prompt-patrol`, `ManagedBy=manual`, `Purpose=terraform-state`                    |

Read-only check (works in PowerShell or bash):

```powershell
$b = "prompt-patrol-tfstate-420974348257"
aws s3api get-bucket-location            --bucket $b
aws s3api get-bucket-versioning          --bucket $b
aws s3api get-bucket-lifecycle-configuration --bucket $b
aws s3api get-bucket-encryption          --bucket $b
aws s3api get-public-access-block        --bucket $b
aws s3api get-bucket-ownership-controls  --bucket $b
aws s3api get-bucket-policy              --bucket $b
aws s3api get-bucket-tagging             --bucket $b
```

## Credentials and secrets

- **No AWS access keys anywhere**: `aws login` locally, GitHub OIDC in CI.
- **Never put a secret in a variable, a `.tfvars` file or a resource argument
  that is saved to state.** Anyone who can read the bucket can read state, and
  `sensitive = true` only hides values from terminal output.
- RDS uses `manage_master_user_password = true`. For other secrets (Auth0
  client secret, M2M credentials), Terraform creates the Secrets Manager secret
  and the value is set outside Terraform, or through a write-only `*_wo`
  argument fed by an `ephemeral` variable (never written to state).
- `terraform.tfvars` is committed and holds non-secret config only.
  `*.secret.tfvars` is gitignored as a safety net, not as permission.

## Tags

The provider's `default_tags` stamp `Project=prompt-patrol` and
`ManagedBy=terraform` on everything. Anything made by hand gets
`Project=prompt-patrol` and `ManagedBy=manual`.

## Locking

Every `plan`/`apply` takes `app/terraform.tfstate.tflock` with a conditional
write. A second run at the same time fails with `Error acquiring the state
lock` (HTTP 412). That's working as intended: wait for the other run.

If a run crashed and left the lock behind, **first confirm nobody else is
running Terraform**, then:

```powershell
terraform force-unlock <LOCK_ID>   # the ID is printed in the lock error
```

## Recovering a bad state

The bucket is versioned, so earlier state is kept for 90 days. Make sure no one
is running Terraform, then:

```powershell
$b = "prompt-patrol-tfstate-420974348257"
aws s3api list-object-versions --bucket $b --prefix app/terraform.tfstate `
  --query "Versions[].[VersionId,LastModified,Size]" --output table
aws s3api copy-object --bucket $b --key app/terraform.tfstate `
  --copy-source "$b/app/terraform.tfstate?versionId=<VERSION_ID>"
terraform plan   # check the restored state against reality before applying
```

## CI

- `lint-infra` (`.github/workflows/ci.yml`) runs `terraform fmt -check` and
  `terraform validate` with `init -backend=false` on every push. It has no AWS
  credentials and never touches state.
- The CD role (built in step 3) needs exactly this on the state bucket:
  - `s3:ListBucket` on `arn:aws:s3:::prompt-patrol-tfstate-420974348257`
  - `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` on
    `arn:aws:s3:::prompt-patrol-tfstate-420974348257/app/*` (the lock file is
    created and deleted on every run)
