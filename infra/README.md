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
| `ecr.tf`                            | ECR repositories, lifecycle policies, scan-on-push rule     |
| `compute.tf`                        | ECS cluster, services, IAM, security groups, purge schedule |
| `edge.tf`                           | ALB, VPC origin, SPA bucket, CloudFront, domain + ACM cert  |
| `email.tf`                          | SES domain identity, DKIM/DMARC records, Auth0's SES user   |
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
- **Roll back:** see [Releases](#releases).
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

1. **Images.** Bring-up deploys the SHA already in SSM
   `/prompt-patrol/image-tag` (seeded in `release.tf`; there is no `image_tag`
   variable), so its images must still be in ECR (it keeps the last 10). The
   `deploy` job can't copy new ones now: the stack is paused, so it fails with
   `stack is paused`. To move to a newer commit, bring the stack up first,
   then push and approve a deploy. A brand-new account needs a running stack
   for its first deploy.
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
   there are no users yet. Run it by hand as in [Break glass](#break-glass),
   and wait for exit code 0 (the first proof the `DB_URL` password works).
   Logs are in `/ecs/prompt-patrol/api`.
6. **Seed the root admin.** `provision_admin_command` contains an `<email>`
   placeholder: replace it, then run it the same way as the migration.

   ```bash
   terraform output -raw provision_admin_command   # copy, replace <email>, append --query 'tasks[0].taskArn' --output text, run
   ```

7. **Ship the SPA.** From now on, push and approve the `deploy` job
   ([Releases](#releases)); the by-hand commands are under
   [Break glass](#break-glass).

8. Open `terraform output -raw frontend_url`, sign in, run one check. Then pause.

## Releases

Push, then approve the `deploy` job (environment `production`). Nothing
reaches AWS before approval. Order: check, copy, migrate, roll out, record,
publish, smoke. The SPA is built earlier, in the `build-web` job, which holds
no AWS credentials; the deploy job only downloads it.

1. **Check:** fails with `stack is paused` if the api service is not ACTIVE,
   before any write.
2. **Copy** this commit's images from GHCR to ECR, by the digest
   `docker-build` pushed (not the GHCR tag, which can be repointed).
3. **Migrate** on a new api task definition revision; on failure it
   deregisters the revisions it registered and prints the task log.
4. **Roll out** api, worker and detector on new revisions (the latest ACTIVE
   revision with only the image swapped); waits up to 30 min and fails if ECS
   rolled back.
5. **Record** the SHA in `/prompt-patrol/image-tag`, as soon as the services
   run it: a later failure (SPA publish, smoke) can't leave SSM naming the
   previous image, which an un-pause would bring back on a migrated schema.
6. **Publish** the SPA to S3 and invalidate CloudFront.
7. **Smoke** through CloudFront: `/` must serve this build's entry chunk and an
   unauthenticated `/api/auth/me` must be the api's own 401 (retries for about
   5 min while the invalidation lands). A failure here means the release is
   live but broken: fix forward or roll back.

- **Terraform and the SHA.** Services ignore `task_definition` changes, so
  `terraform apply` never rolls an image. Terraform reads the SHA from the SSM
  parameter at refresh (a `-refresh=false` plan or a `-target` apply uses the
  stale state value). Un-pausing therefore restores the SHA last recorded.
- **Terraform-only changes** (env, sizing) reach the services on the next
  deploy: re-run the latest deploy to apply them now.
- **Roll back:** re-run a deploy made after step 7, within ~30 days, while the
  image is still among the last 10 in ECR. A re-run across a migration fails
  at the migrate step by design (down-migrations are manual). Re-running a
  deploy from before step 7 only copies images: don't use it. A re-run reuses
  that run's image digests and SPA artifact (kept 30 days, the re-run window).
- **Plan after a deploy** shows one replaced task definition per service, with
  the same image. This is expected; the services don't roll.

### Break glass

By hand, in Git Bash from `infra/`, when the pipeline can't be used.
`migrate_command` runs the family (`prompt-patrol-api`), so it uses the
latest revision. After a circuit-breaker rollback the failed revision stays
the latest ACTIVE one in the family, so these commands and the purge schedule
run that image until the next successful deploy (the schema is already
migrated, so this is consistent). Take commands from `terraform output -raw` (plain
`terraform output` adds quotes and escapes that break the shell):

```bash
eval "$(terraform output -raw migrate_command) --query 'tasks[0].taskArn' --output text"   # prints the task ARN
aws ecs wait tasks-stopped --profile prompt-patrol --region ap-southeast-1 \
  --cluster prompt-patrol --tasks <task-arn>
aws ecs describe-tasks --profile prompt-patrol --region ap-southeast-1 \
  --cluster prompt-patrol --tasks <task-arn> \
  --query "tasks[0].containers[0].[exitCode,reason]"
```

SPA (needs Node 24; Node 25 breaks the toolchain):

```bash
(cd ../apps/web && npm ci && npm run build)
aws s3 sync ../apps/web/dist/ "s3://$(terraform output -raw web_bucket_name)" --delete \
  --profile prompt-patrol --region ap-southeast-1
aws cloudfront create-invalidation --profile prompt-patrol --region ap-southeast-1 \
  --distribution-id "$(terraform output -raw cloudfront_distribution_id)" --paths "/*"
```

**Cost.** Step 5 adds about $5/day (detector about $0.123/h, api $0.031/h,
worker $0.015/h, ALB $0.025/h). With the NAT/endpoints and RDS the whole stack
is about $10/day, or about $295/month: over the $100 budget if left running.
Run it in test windows and [pause](#pausing-the-environment) between them.

## WAF, headers and CORS (step 6)

**What the WAF does.** Web ACL `prompt-patrol` (in `us-east-1`, as CloudFront
requires) filters at the edge: IP reputation list, a per-IP rate limit of
2000 requests / 5 min on everything, a per-IP limit of 300 / 5 min on API
writes (POST/PUT/PATCH/DELETE on `/api/`), and the Common Rule Set and Known
Bad Inputs set for headers, URI and query string. **It never blocks on
request bodies**: student answers contain code and run to 12,000 characters,
so every `*_BODY` rule is forced to Count (`local.crs_body_rules` and
`local.kbi_body_rules` in `waf.tf`). It is an outer filter; the app still
checks session and CSRF itself. L3/L4 floods are covered by Shield Standard,
which CloudFront includes. A blocked request gets CloudFront's own non-JSON
`403`. The ACL is removed while [paused](#pausing-the-environment); the
headers policy and CORS rule are free and always stay.

**Cost.** About $10/month prorated while running ($5 ACL + $1 per rule) plus
$0.60 per million requests.

**Reading metrics.** CloudWatch, Region `us-east-1`, namespace `AWS/WAFV2`,
dimensions `WebACL=prompt-patrol` + `Rule=ALL` (whole ACL) or `Rule=<metric
name>` (e.g. `CrossSiteScripting_BODY`, `prompt-patrol-rate-writes`); there is
no `Region` dimension for CloudFront. `BlockedRequests` on a rule means it
blocked (the metric doesn't exist until the first block); `CountedRequests` on
the body rules is expected.

**Sampled requests are off** on purpose: a sample keeps the full request,
including the `__Host-session` cookie, for about 3 hours in the console, and
redaction does not apply. To debug a suspected false positive, set
`sampled_requests_enabled = true` on that one rule's `visibility_config`,
apply, look, then set it back and apply. There is no WAF logging.

**Flip a rule to Count** (to stop it blocking while you investigate): for a
managed group, change its `override_action { none {} }` to `{ count {} }` (or
add one rule to its `rule_action_override` with `count {}`); for a rate rule,
change `action { block {} }` to `action { count {} }`. Apply.

**New `*_BODY` rule from AWS.** If AWS adds a body rule to a managed group, it
blocks until the local list is refreshed. Check with:

```bash
aws wafv2 describe-managed-rule-group --scope CLOUDFRONT --region us-east-1 \
  --vendor-name AWS --name AWSManagedRulesCommonRuleSet \
  --query "Rules[].Name" --profile prompt-patrol
```

(repeat for `AWSManagedRulesKnownBadInputsRuleSet`), then add any new
`*_BODY` names to the matching local list in `waf.tf` and apply.

**Rate-limit tests: only from a disposable IP** (a phone hotspot). Never from
campus or any shared network: the block would lock out everyone behind that
IP. It lifts on its own once the rate drops.

**Headers and CSP.** The CloudFront response headers policy
`prompt-patrol-security` (in `edge.tf`) mirrors `apps/web/nginx.conf`. Change
the CSP in both places together (HSTS differs on purpose: 1 year at
CloudFront, 86400 in nginx, and none locally since it is plain http).
`connect-src` lists the batches bucket's global and regional hosts so the
browser's presigned PUT passes CSP; the bucket's CORS rule (in `storage.tf`) allows `PUT` from `frontend_url`.
Both are only enforced by a real browser, so test batch upload in one.

## Domain and email

`prompt-patrol.com` was registered by hand in Route 53 (auto-renew off on
purpose; it lapses 2027-10-20). The registrar made the hosted zone, so
Terraform reads it (`data.aws_route53_zone.main`) instead of managing it.

**App hostname.** `local.app_hostname` (`app.prompt-patrol.com`) is the app's
identity: it is the CloudFront alias, the ACM cert's name (us-east-1, DNS
validated, renews itself), and `frontend_url`. Every other host, including
the distribution's `*.cloudfront.net` name, gets a 301 to it from
`spa_rewrite`. Changing it is a cutover, in this order: add the new URLs in
Auth0 (callback, logout, web origin), write `AUTH0_REDIRECT_URI`, change
`app_hostname` and apply, then roll api and worker to the new revision (the
services ignore `task_definition`, so the apply alone changes nothing that is
running):

```bash
for s in api worker; do
  aws ecs update-service --profile prompt-patrol --region ap-southeast-1 \
    --cluster prompt-patrol --service $s --task-definition prompt-patrol-$s
done
```

The api refuses to start when `FRONTEND_URL` and `AUTH0_REDIRECT_URI`
disagree on host, so keep the gap between the secret and the apply short.
Also update the smoke test's `FRONTEND_URL` in `.github/workflows/ci.yml`.

**Email.** Auth0 sends the invite and password emails through SES as
`no-reply@prompt-patrol.com`. The IAM user `prompt-patrol-auth0-ses` may send
only as that address. Its access key is made by hand
(`aws iam create-access-key`) and pasted into Auth0 > Branding > Email
Provider, so it never enters state. Rotate it the same way, then delete the
old key. SES must be out of the sandbox before Auth0 is switched to it: the
sandbox only delivers to verified addresses.

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
