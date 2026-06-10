# Infrastructure & IaC Security Pack

## Scope

This pack audits Infrastructure-as-Code files for security and misconfiguration issues. It covers Dockerfiles, Terraform HCL, Kubernetes manifests, and CloudFormation templates. It does NOT audit application source code, dependency vulnerabilities, or secret management systems outside of IaC configuration.

**Pack ID:** `ccgm/infra-iac`
**Applies when:** `["has_iac"]`

---

## applies_when Rationale

| Condition | Reason |
|-----------|--------|
| `has_iac` | Pack is only useful when IaC files exist; running on repos without Dockerfiles, Terraform, k8s manifests, or CloudFormation templates produces zero signal. `has_iac` is true when any of these IaC file types are detected by the ecosystem detector. |

---

## Checks

---

### `iac/dockerfile-root-user`

**Severity:** `high`
**Confidence:** `high`
**Detection:** `hybrid`

#### Detection

Detects Dockerfiles that run container processes as root (no `USER` directive, or `USER root` set without a subsequent non-root `USER` directive).

**Tool (detection = hybrid):**
`hadolint`

Rule / rule-id: `DL3002` — Avoid running as root in the final image.

Fallback when tool absent: `grep` — scan for absence of `USER` directive or presence of `USER root` as last USER line.

**LLM instruction (hybrid fallback confirmation):**

```
Review each Dockerfile for root user execution risk. A container runs as root if:
1. No USER directive is present at all.
2. The last USER directive sets "root" or uid 0.

Flag each Dockerfile that runs as root. Do NOT flag Dockerfiles where USER is set
to a non-root user as the final USER instruction. Report: file path, line number
of the relevant USER directive (or line 1 if no USER directive exists), and a
brief description of why this is a finding.
```

#### Spine Wiring

hadolint emits its own rule IDs (e.g. `DL3002`). The parse-hadolint.py normalizer maps all hadolint findings to check_id `iac/dockerfile-issue` with `rule_id` carrying the hadolint code. Pack-level check_id `iac/dockerfile-root-user` is the conceptual owner; the spine emits the underlying hadolint rule_id for traceability.

```yaml
check_id: iac/dockerfile-root-user
detection: hybrid
tool: hadolint
rule: DL3002
fallback: grep
```

#### Severity / Confidence

**Severity rationale:** HIGH — Running a container as root means any process escape grants root access on the host (if the host namespace is shared or if container isolation is broken). Direct path to privilege escalation.

**Confidence rationale:** HIGH — hadolint DL3002 is a deterministic check with very low false-positive rate; the USER directive presence/absence is unambiguous.

**Rubric entry:** `iac/dockerfile-root-user`

#### Fixture

**True positive** (`Dockerfile`):

```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY . .
RUN npm install
# FINDS: No USER directive — runs as root
CMD ["node", "index.js"]
```

**True negative** (should produce NO finding):

```dockerfile
FROM node:20-alpine
WORKDIR /app
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
COPY . .
RUN npm install
USER appuser
CMD ["node", "index.js"]
```

---

### `iac/dockerfile-latest-tag`

**Severity:** `medium`
**Confidence:** `high`
**Detection:** `tool`

#### Detection

Detects Dockerfile `FROM` directives that use the `:latest` tag or no tag at all, making builds non-reproducible.

**Tool (detection = tool):**
`hadolint`

Rule / rule-id: `DL3007` — Using latest is prone to errors if the image will ever be updated. Pin the version explicitly to a release tag.

Fallback when tool absent: `none — skip check`

#### Spine Wiring

```yaml
check_id: iac/dockerfile-latest-tag
detection: tool
tool: hadolint
rule: DL3007
```

#### Severity / Confidence

**Severity rationale:** MEDIUM — Non-reproducible builds can introduce unexpected changes on rebuild, including security regressions. Does not directly expose a vulnerability but degrades the security posture over time.

**Confidence rationale:** HIGH — hadolint DL3007 is a deterministic check on the FROM line tag.

**Rubric entry:** `iac/dockerfile-latest-tag`

#### Fixture

**True positive** (`Dockerfile`):

```dockerfile
# FINDS: :latest tag is non-deterministic
FROM node:latest
WORKDIR /app
```

**True negative** (should produce NO finding):

```dockerfile
# OK: pinned to a specific version
FROM node:20.11.0-alpine3.19
WORKDIR /app
```

---

### `iac/public-ingress`

**Severity:** `high`
**Confidence:** `medium`
**Detection:** `hybrid`

#### Detection

Detects security group or firewall rules in IaC (Terraform, CloudFormation) that allow unrestricted inbound access from `0.0.0.0/0` or `::/0` on sensitive ports or all ports.

**Tool (detection = hybrid):**
`checkov`

Rule / rule-id: Various checkov rules including `CKV_AWS_25` (unrestricted security group), `CKV_AWS_24`, and similar cloud-provider checks.

Fallback when tool absent: `llm`

**LLM instruction (hybrid fallback / confirmation):**

```
Scan all Terraform (.tf), CloudFormation (.yaml/.json), and Kubernetes manifest
files for network ingress rules that permit unrestricted access from 0.0.0.0/0
(IPv4) or ::/0 (IPv6).

Flag each resource that:
1. Defines a security group, firewall rule, network ACL, or k8s NetworkPolicy that
   allows inbound traffic from 0.0.0.0/0 or ::/0.
2. The rule applies to ALL ports (port range 0-65535 or equivalent) OR to a
   sensitive port (22/SSH, 3389/RDP, 3306/MySQL, 5432/PostgreSQL, 27017/MongoDB,
   6379/Redis, 9200/Elasticsearch).

Do NOT flag rules that restrict source CIDRs to known non-public ranges
(10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16).

Report: file path, line number, resource name, and which CIDR/port combination
triggered the finding.
```

#### Spine Wiring

checkov findings are emitted with check_id `iac/checkov-violation` and the checkov rule_id in the `rule_id` field (e.g. `CKV_AWS_25`). The pack-level check_id `iac/public-ingress` is the conceptual grouping; post-processing can filter by rule_id pattern to isolate ingress-related findings.

```yaml
check_id: iac/public-ingress
detection: hybrid
tool: checkov
fallback: llm
```

#### Severity / Confidence

**Severity rationale:** HIGH — Unrestricted public ingress on sensitive ports or all ports directly exposes services to the internet, enabling brute force, exploitation, or unauthorized access with no network-level mitigation.

**Confidence rationale:** MEDIUM — checkov's automated rules catch the most common patterns; unusual resource structures or custom abstractions may evade automated detection, hence hybrid with LLM fallback.

**Rubric entry:** `iac/public-ingress`

#### Fixture

**True positive** (`main.tf`):

```hcl
# FINDS: security group allows all inbound from 0.0.0.0/0
resource "aws_security_group" "web" {
  ingress {
    from_port   = 0
    to_port     = 65535
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
```

**True negative** (should produce NO finding):

```hcl
# OK: restricted to known internal range
resource "aws_security_group" "internal" {
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/8"]
  }
}
```

---

### `iac/missing-encryption`

**Severity:** `medium`
**Confidence:** `medium`
**Detection:** `tool`

#### Detection

Detects IaC resources (S3 buckets, RDS instances, EBS volumes, SQS queues, etc.) that do not have encryption at rest configured.

**Tool (detection = tool):**
`checkov`

Rule / rule-id: Various checkov rules including `CKV_AWS_19` (S3 encryption), `CKV_AWS_17` (RDS encryption), `CKV_AWS_3` (EBS encryption), and similar.

Fallback when tool absent: `none — skip check`

#### Spine Wiring

```yaml
check_id: iac/missing-encryption
detection: tool
tool: checkov
```

#### Severity / Confidence

**Severity rationale:** MEDIUM — Unencrypted storage means data is readable if the underlying infrastructure is compromised. Significant compliance risk; moderate operational security risk depending on data sensitivity.

**Confidence rationale:** MEDIUM — checkov accurately detects when encryption flags are absent from resource definitions; however, some resources may inherit encryption from account-level defaults not visible in the IaC files alone.

**Rubric entry:** `iac/missing-encryption`

#### Fixture

**True positive** (`main.tf`):

```hcl
# FINDS: S3 bucket with no server-side encryption configured
resource "aws_s3_bucket" "data" {
  bucket = "my-data-bucket"
}
```

**True negative** (should produce NO finding):

```hcl
# OK: encryption enabled
resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
  }
}
```

---

### `iac/hardcoded-secret-in-iac`

**Severity:** `high`
**Confidence:** `medium`
**Detection:** `hybrid`

#### Detection

Detects hardcoded credentials, API keys, passwords, or other secrets embedded directly in IaC configuration files rather than referenced from a secrets manager.

**Tool (detection = hybrid):**
`checkov`

Rule / rule-id: `CKV_SECRET_*` family — checkov's secrets detection rules scan for common credential patterns in IaC files.

Fallback when tool absent: `grep` — pattern-match for `password`, `secret`, `api_key`, `access_key`, `private_key` assignments containing non-variable literal values.

**LLM instruction (hybrid fallback confirmation):**

```
Scan all IaC files (.tf, .yaml, .yml, .json) for hardcoded secrets. A hardcoded
secret is a literal string value assigned to a field whose name suggests it holds
a credential (password, secret, key, token, credential, api_key, access_key,
private_key, auth_token).

Flag each occurrence where:
1. The field name matches the patterns above.
2. The value is a non-empty literal string (not a variable reference like
   ${var.password} or !Ref MySecret or a placeholder like "CHANGEME").

Do NOT flag:
- Variable references (${...}, !Ref, !Sub with only references)
- Empty strings ("")
- Obvious placeholder values ("CHANGEME", "PLACEHOLDER", "TODO", "your-secret-here")
- KMS key ARNs or resource ARNs (these are identifiers, not secrets)

Report: file path, line number, field name, and first 4 characters of the value
(do not include the full value in the report).
```

#### Spine Wiring

```yaml
check_id: iac/hardcoded-secret-in-iac
detection: hybrid
tool: checkov
fallback: grep
```

#### Severity / Confidence

**Severity rationale:** HIGH — Hardcoded credentials in IaC files are committed to source control, accessible to everyone with repo access, and persist in git history even after removal. Direct credential exposure.

**Confidence rationale:** MEDIUM — Automated pattern matching has false positives on placeholder values and false negatives on obfuscated or non-standard credential field names. LLM confirmation reduces noise.

**Rubric entry:** `iac/hardcoded-secret-in-iac`

#### Fixture

**True positive** (`main.tf`):

```hcl
# FINDS: hardcoded database password
resource "aws_db_instance" "main" {
  engine   = "postgres"
  password = "supersecret123!"
}
```

**True negative** (should produce NO finding):

```hcl
# OK: password sourced from a variable (not hardcoded)
resource "aws_db_instance" "main" {
  engine   = "postgres"
  password = var.db_password
}
```

---

## Quality Checklist

- [x] Each check-id in this file exactly matches `pack.json`'s `checks[].id`
- [x] Every check with `detection: tool` or `detection: hybrid` names a real spine tool
- [x] Every check with `detection: llm` or `detection: hybrid` has a filled-in LLM instruction
- [x] Each fixture has both a true positive AND a true negative
- [x] Severity / confidence rationale is present for every check
- [x] `applies_when` rationale table is complete
- [x] `scripts/lint-pack.py` passes on this pack
