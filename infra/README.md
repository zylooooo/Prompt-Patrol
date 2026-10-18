# infra

The single Terraform root for Prompt Patrol's AWS deployment. One account
(`420974348257`), one environment, Region `ap-southeast-1`. State lives at
`s3://prompt-patrol-tfstate-420974348257/app/terraform.tfstate`, locked with
S3's native lockfile (no DynamoDB table).

## Layout

One root, one state, files split by area per the
[Terraform style guide](https://developer.hashicorp.com/terraform/language/style#file-names):

| File                                | Holds                                                       |
| ----------------------------------- | ----------------------------------------------------------- |
| `terraform.tf`                      | `required_version`, `required_providers`                    |
| `backend.tf`                        | S3 backend                                                  |
| `providers.tf`                      | AWS provider, account guard, default tags                   |
| `variables.tf` / `terraform.tfvars` | inputs / their committed values                             |
| `network.tf`                        | VPC, subnets, NAT, route tables                             |
| `endpoints.tf`                      | VPC endpoints and their security group                      |
| `ecr.tf`                            | ECR repositories and lifecycle policies                     |
| `compute.tf`                        | ECS cluster, services, IAM, security groups, purge schedule |
| `edge.tf`                           | ALB, VPC origin, SPA bucket, CloudFront                     |
| `github-oidc.tf`                    | GitHub OIDC provider and the deploy role                    |
| `tests/`                            | `terraform test` files (mock provider, run in CI)           |

`compute.tf` and `edge.tf` are step 5. There are no modules: every resource is
hand-written per service (api, worker, detector) for granular control. Add
`outputs.tf` entries when something needs an output.

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

Everything billed by the hour is gated on `paused`: the NAT gateway, its
Elastic IP and the five interface endpoints (about $4.70/day), the RDS
instance, and since step 5 the ALB, the CloudFront VPC origin, the three ECS
services and their task definitions, and the nightly session-purge schedule
(about $5/day more). To stop paying
for it, set this in `terraform.tfvars`, apply, and commit:

```hcl
paused = true
```

Set it back to `false` and apply to resume (about 5 minutes). Free resources
(VPC, subnets, route tables, internet gateway, S3 gateway endpoint, security
groups, ECS cluster, CloudFront distribution, SPA bucket, log groups) stay up either way, so nothing that depends on them is rebuilt.

- Change it in `terraform.tfvars`, never with `-var`: the CD apply reads the
  committed file, so a `-var` pause would be undone by the next deploy.
- Resuming gets a new NAT IP address. Nothing allowlists it today.
- Resuming creates a new, empty database. Once the services settle, run the
  migration and seed the root admin again (steps 5 and 6 of
  [Compute and edge](#compute-and-edge-step-5)); Auth0 keeps the admin's
  login, so no new invite is sent.
- New hourly-billed resources must follow the same rule (`count` or `for_each`
  on `var.paused`). Stateful ones (RDS) don't; they need their own plan.

## Images and deploys

```text
push to main ─► CI builds api / worker / detector ─► GHCR (tag = commit SHA)
                                │
                 deploy job waits on the `production` environment
                                │  ◄── a reviewer clicks Approve
                                ▼
         OIDC → role prompt-patrol-deploy → copy images GHCR ─► ECR (by digest)
```

- **Nothing reaches AWS without an approval.** The `deploy` job in
  `.github/workflows/ci.yml` runs in the GitHub `production` environment, which
  requires a reviewer. The role trusts only
  `repo:zylooooo/Prompt-Patrol:environment:production` (`github-oidc.tf`); no
  AWS keys are stored in GitHub.
- **Which branches can deploy** is the environment's deployment-branch rule
  (GitHub → Settings → Environments → production), not the IAM role.
- **AWS runs only from ECR.** Isolated-tier tasks have no internet route, so
  they can't pull from `ghcr.io`; ECR is reached through the VPC endpoints.
- **Copy by digest:** the image in ECR is byte-for-byte the one CI built.
  ECR tags are immutable; re-running a deploy skips images already copied.
- **Roll back:** re-run the `deploy` job of an older CI run.
- GHCR packages are **public** (private storage on the free plan is 500 MB;
  the detector alone is several GB).
- ECR keeps the newest 10 images per repo; GHCR keeps every build.
- The detector image is `apps/detector/Dockerfile.desklib`.

## Compute and edge (step 5)

`compute.tf` runs api, worker and detector on Fargate in cluster
`prompt-patrol`; `edge.tf` puts CloudFront (SPA from S3, `/api/*` to the
internal ALB through a VPC origin) in front. Bringing it up is manual and
ordered. **Run every command here in Git Bash**: PowerShell 5.1 mangles the
inline JSON in the one-off task commands. All AWS commands carry
`--profile prompt-patrol --region ap-southeast-1`; `terraform` runs from
`infra/`.

1. **Images.** Commit, let CI's `deploy` job copy that commit's images to ECR,
   then set `image_tag` in `terraform.tfvars` to the commit SHA.
2. **Apply** with `paused = false`:

   ```bash
   terraform apply
   ```

   The services fail to start until step 3 (the redirect secret is empty).
   That is expected. If the first apply fails reading the security group
   `CloudFront-VPCOrigins-Service-SG`, it simply didn't exist yet (AWS creates
   it when the VPC origin does): run `terraform apply` once more.
3. **Redirect secret.** Fill `prompt-patrol/AUTH0_REDIRECT_URI` with the output
   of `terraform output -raw auth0_callback_url`, (the other
   five `AUTH0_*` secrets are already set):

   ```bash
   aws secretsmanager put-secret-value --profile prompt-patrol --region ap-southeast-1 \
     --secret-id prompt-patrol/AUTH0_REDIRECT_URI \
     --secret-string "$(terraform output -raw auth0_callback_url)"
   ```

   The URL is not a secret, so it goes straight from the output; no `read`
   needed. (Or paste it in the console's Plaintext tab.) Then, in the Auth0
   application, add that callback URL to **Allowed Callback URLs**, and
   `terraform output -raw frontend_url` plus `<frontend_url>/login` to
   **Allowed Logout URLs**. Logout redirects to `FRONTEND_URL` or
   `FRONTEND_URL/login?error=...` (`auth_routes.py`); add both URLs and test a
   logout rather than relying on Auth0 ignoring the query string.
4. **Pick up the secret.** Secrets are read at task start, and on first
   bring-up api and worker have been failing without `AUTH0_REDIRECT_URI`, so
   restart both:

   ```bash
   for s in api worker; do
     aws ecs update-service --profile prompt-patrol --region ap-southeast-1 \
       --cluster prompt-patrol --service $s --force-new-deployment
   done
   ```

   Then let the rollouts settle. The Fargate vCPU quota is 6 and a full rollout
   peaks at 5.5, so a one-off task started mid-rollout fails to place. Wait
   until each service shows `runningCount` equal to `desiredCount` and no
   pending deployment:

   ```bash
   aws ecs describe-services --profile prompt-patrol --region ap-southeast-1 \
     --cluster prompt-patrol --services api worker detector \
     --query "services[].[serviceName,desiredCount,runningCount,deployments[].rolloutState]"
   ```

5. **Migrate, only after the rollouts settle.** Between the restart and the
   migration the api may serve against an unmigrated DB; that is harmless, as
   there are no users yet.

   Run the migration, then wait for it to stop with exit code 0 (this is the
   first proof the `DB_URL` password works). Take the commands from
   `terraform output -raw` (plain `terraform output` adds quotes and escapes
   that break the shell):

   ```bash
   eval "$(terraform output -raw migrate_command) --query 'tasks[0].taskArn' --output text"   # prints the task ARN
   aws ecs wait tasks-stopped --profile prompt-patrol --region ap-southeast-1 \
     --cluster prompt-patrol --tasks <task-arn>
   aws ecs describe-tasks --profile prompt-patrol --region ap-southeast-1 \
     --cluster prompt-patrol --tasks <task-arn> \
     --query "tasks[0].containers[0].[exitCode,reason]"
   ```

   Logs are in `/ecs/prompt-patrol/api`.
6. **Seed the root admin.** `provision_admin_command` contains an `<email>`
   placeholder: replace it, then run it the same way as the migration.

   ```bash
   terraform output -raw provision_admin_command   # copy, replace <email>, append --query 'tasks[0].taskArn' --output text, run
   ```

7. **Ship the SPA.** Needs Node 24 (Node 25 breaks the toolchain):

   ```bash
   (cd ../apps/web && npm ci && npm run build)
   aws s3 sync ../apps/web/dist/ "s3://$(terraform output -raw web_bucket_name)" --delete \
     --profile prompt-patrol --region ap-southeast-1
   aws cloudfront create-invalidation --profile prompt-patrol --region ap-southeast-1 \
     --distribution-id "$(terraform output -raw cloudfront_distribution_id)" --paths "/*"
   ```

8. Open `terraform output -raw frontend_url`, sign in, run one check. Then pause.

Known gaps until step 6 of the CD plan: no WAF, no CSP or other security
headers, and batch CSV upload fails (the batches bucket has no CORS rule).

**Cost.** Step 5 adds about $5/day (detector about $0.145/h, api $0.031/h,
worker $0.015/h, ALB $0.025/h). With the NAT/endpoints and RDS the whole stack
is about $10/day, or about $310/month: over the $100 budget if left running.
Run it in test windows and [pause](#pausing-the-environment) between them.

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
aws s3api get-bucket-location     \
       --bucket $b
aws s3api get-bucket-versioning   \
       --bucket $b
aws s3api get-bucket-lifecycle-configuration --bucket $b
aws s3api get-bucket-encryption   \
       --bucket $b
aws s3api get-public-access-block \
       --bucket $b
aws s3api get-bucket-ownership-controls  --bucket $b
aws s3api get-bucket-policy       \
       --bucket $b
aws s3api get-bucket-tagging      \
       --bucket $b
```

## Credentials and secrets

- **No AWS access keys anywhere**: `aws login` locally, GitHub OIDC in CI.
- **Never put a secret in a variable, a `.tfvars` file or a resource argument
  that is saved to state.** Anyone who can read the bucket can read state, and
  `sensitive = true` only hides values from terminal output.
- The DB password is generated by an `ephemeral "random_password"`
  (`hashicorp/random`) and written write-only (`password_wo`,
  `secret_string_wo`) to both the RDS instance and `prompt-patrol/DB_URL` in
  the same apply, so it is never in state or plan. `SESSION_SECRET` is
  generated and written the same way (bump `secret_string_wo_version` to
  rotate).
- The six `prompt-patrol/AUTH0_*` secrets are set by hand (console or
  `aws secretsmanager put-secret-value`); Terraform creates the containers
  only and never reads or writes their values.
- The DB follows `paused` and is deleted with no final snapshot. For the demo
  build set `db_deletion_protection = true` in `terraform.tfvars`, which makes
  a pause or destroy fail instead (and the plan refuses `paused = true` while
  it is set). Leaving the demo build takes two applies: (1) set
  `db_deletion_protection = false` with `paused = false` and apply, so the
  live instance loses its protection; (2) then set `paused = true` and apply.
  Flipping both in one apply fails the DB destroy after `DB_URL` left state;
  recover by bumping `db_password_version` (below).
- If `DB_URL` and the DB disagree, bump `db_password_version` in
  `database.tf` and apply. Running tasks keep the old secret, so then run
  `aws ecs update-service --cluster prompt-patrol --service <api|worker>
  --force-new-deployment` for both api and worker.
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
