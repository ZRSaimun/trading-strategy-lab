"""Conservative, read-only guard for this repo's small Render Blueprint.

This is deliberately a *narrow text-policy check*, not a YAML parser, Render
schema validation, service-state attestation, backup drill or deployment gate.
Unknown service layouts should be reviewed rather than silently accepted.
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
BLUEPRINT = ROOT / "render.yaml"


def check_blueprint(text: str) -> list[str]:
    """Return policy violations without ever printing source values/secrets."""
    errors: list[str] = []
    if not isinstance(text, str) or not text or len(text.encode("utf-8")) > 16384:
        return ["BLUEPRINT_SIZE_OR_TYPE"]
    if "\t" in text or "\r" in text:
        errors.append("NONCANONICAL_WHITESPACE")

    def require_one(pattern: str, label: str) -> None:
        if len(re.findall(pattern, text, flags=re.MULTILINE)) != 1:
            errors.append(label)

    require_one(r"^services:$", "SERVICES_ROOT_NOT_UNIQUE")
    require_one(r"^  - type: web$", "EXPECTED_SINGLE_WEB_SERVICE")
    require_one(r"^    name: trading-strategy-lab-private$", "EXPECTED_SERVICE_NAME")
    require_one(r"^    runtime: docker$", "EXPECTED_DOCKER_RUNTIME")
    require_one(r"^    plan: free$", "FREE_PLAN_REQUIRED")
    require_one(r"^    dockerfilePath: \./deploy/free\.Dockerfile$", "EXPECTED_DOCKERFILE")
    require_one(r"^    autoDeployTrigger: 'off'$", "MANUAL_DEPLOY_REQUIRED")
    require_one(r"^    healthCheckPath: /api/health$", "HEALTH_PATH_REQUIRED")
    require_one(r"^      - key: DEPLOYMENT_PROFILE\n        value: free-cloud$", "FREE_PROFILE_REQUIRED")
    require_one(r'^      - key: FREE_ONLY\n        value: "true"$', "FREE_ONLY_REQUIRED")
    require_one(r'^      - key: TWELVEDATA_ENABLED\n        value: "false"$', "PAID_FEED_DISABLED_REQUIRED")
    require_one(r"^      - key: DATABASE_SCHEMA\n        value: tsl_private$", "PRIVATE_SCHEMA_REQUIRED")
    for secret in ("DATABASE_URL", "DATABASE_CA_PEM", "OWNER_PASSWORD_HASH"):
        require_one(r"^      - key: " + secret + r"\n        sync: false$",
                    "SECRET_REFERENCE_REQUIRED_" + secret)

    # A second service, alternative plan or duplicate YAML key can override
    # the above narrow allowlist. Refuse rather than trust parser precedence.
    checks = (
        (r"^\s*- type:\s*", 1, "UNEXPECTED_RESOURCE_TYPE"),
        (r"^\s*plan:\s*", 1, "UNEXPECTED_PLAN"),
        (r"^\s*autoDeployTrigger:\s*", 1, "DUPLICATE_AUTO_DEPLOY"),
        (r"^\s*healthCheckPath:\s*", 1, "DUPLICATE_HEALTH_PATH"),
        (r"^\s*name:\s*trading-strategy-lab-private\s*$", 1, "DUPLICATE_SERVICE_NAME"),
    )
    for pattern, expected, label in checks:
        if len(re.findall(pattern, text, flags=re.MULTILINE)) != expected:
            errors.append(label)
    for pattern, label in (
        (r"^\s*(?:databases|envVarGroups|projects|ungrouped|previews):", "UNREVIEWED_BLUEPRINT_RESOURCE"),
        (r"^\s*(?:disk|scaling|numInstances|preDeployCommand|initialDeployHook):", "UNREVIEWED_DEPLOY_CAPABILITY"),
        (r"^\s*autoDeploy:\s*", "DEPRECATED_AUTO_DEPLOY_OVERRIDE"),
        (r"^\s*- type:\s*(?:worker|cron|pserv|keyvalue|redis)\b", "NON_WEB_RESOURCE"),
    ):
        if re.search(pattern, text, flags=re.MULTILINE):
            errors.append(label)
    # Fail closed on unexpected environment entries and extra YAML fields in
    # a secret block. This is still a narrow policy check, not a YAML parser.
    expected_env = {"DEPLOYMENT_PROFILE", "FREE_ONLY", "TWELVEDATA_ENABLED",
                    "DATABASE_SCHEMA", "DATABASE_URL", "DATABASE_CA_PEM",
                    "OWNER_PASSWORD_HASH"}
    found_env = re.findall(r"^      - key: ([A-Z_]+)$", text, flags=re.MULTILINE)
    if len(found_env) != len(expected_env) or set(found_env) != expected_env:
        errors.append("UNREVIEWED_ENVIRONMENT_KEY")
    for secret in ("DATABASE_URL", "DATABASE_CA_PEM", "OWNER_PASSWORD_HASH"):
        block = re.search(r"^      - key: " + secret +
                          r"$\n(?P<body>(?:        [^\n]*\n)*)", text,
                          flags=re.MULTILINE)
        if block is None or block.group("body") != "        sync: false\n":
            errors.append("SECRET_BLOCK_NOT_EXACT_" + secret)
    # The three secret references must not be accompanied by hardcoded values.
    # This guard deliberately never includes a potentially secret value in errors.
    for secret in ("DATABASE_URL", "DATABASE_CA_PEM", "OWNER_PASSWORD_HASH"):
        if len(re.findall(r"^\s*- key: " + secret + r"$", text, flags=re.MULTILINE)) != 1:
            errors.append("DUPLICATE_OR_MISSING_SECRET_KEY_" + secret)
    return sorted(set(errors))


def main() -> int:
    try:
        issues = check_blueprint(BLUEPRINT.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        issues = ["BLUEPRINT_UNREADABLE"]
    if issues:
        print("FAIL_STATIC_BLUEPRINT_POLICY: " + ", ".join(issues))
        return 1
    print("PASS_STATIC_BLUEPRINT_ONLY: manual deploy declared; live Render settings, backup, rollback and health unverified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
