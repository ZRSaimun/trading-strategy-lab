"""Synthetic regressions for the repo's manual-only, free Render Blueprint."""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from check_render_release_policy import check_blueprint  # noqa: E402

BLUEPRINT = (ROOT / "render.yaml").read_text(encoding="utf-8")


def test_current_blueprint_declares_manual_free_release():
    assert check_blueprint(BLUEPRINT) == []


@pytest.mark.parametrize("unsafe", [
    lambda t: t.replace("autoDeployTrigger: 'off'", "autoDeployTrigger: checksPass"),
    lambda t: t.replace("autoDeployTrigger: 'off'", "autoDeployTrigger: 'off'\n    autoDeployTrigger: commit"),
    lambda t: t.replace("plan: free", "plan: starter"),
    lambda t: t + "\ndatabases:\n  - name: paid-db\n    plan: starter\n",
    lambda t: t + "\n    disk:\n      sizeGB: 5\n",
    lambda t: t.replace("healthCheckPath: /api/health", "healthCheckPath: /wrong"),
    lambda t: t.replace("      - key: DATABASE_URL\n        sync: false",
                        "      - key: DATABASE_URL\n        value: plaintext-not-a-secret"),
    lambda t: t.replace('value: "true"', 'value: "false"'),
    lambda t: t.replace("  - type: web", "  - type: worker"),
    lambda t: t + "\n    autoDeploy: true\n",
    lambda t: t.replace("services:\n", "previews:\n  generation: automatic\nservices:\n"),
    lambda t: t + "\n    numInstances: 2\n",
    lambda t: t.replace("    plan: free", "    plan: free\n    plan: free"),
    lambda t: t.replace("    plan: free", "\tplan: free"),
    lambda t: t.replace("      - key: OWNER_PASSWORD_HASH\n        sync: false",
                        "      - key: OWNER_PASSWORD_HASH\n        sync: false\n      - key: OWNER_PASSWORD_HASH\n        sync: false"),
    lambda t: t.replace("      - key: DATABASE_URL\n        sync: false",
                        "      - key: DATABASE_URL\n        sync: false\n        value: secret-in-git"),
    lambda t: t + "\n      - key: BROKER_SECRET\n        value: forbidden\n",
    lambda t: t + "\n    buildCommand: unreviewed-command\n",
])
def test_unsafe_blueprint_is_rejected(unsafe):
    assert check_blueprint(unsafe(BLUEPRINT))


def test_oversize_and_nontext_rejected():
    assert check_blueprint("x" * 16385) == ["BLUEPRINT_SIZE_OR_TYPE"]
    assert check_blueprint(None) == ["BLUEPRINT_SIZE_OR_TYPE"]

def test_blueprint_key_order_cannot_be_rearranged():
    # An unordered line-multiset check accepts both of these despite the
    # source no longer matching the reviewed Blueprint layout.
    swapped_docker = BLUEPRINT.replace(
        "    dockerfilePath: ./deploy/free.Dockerfile\n    dockerContext: .",
        "    dockerContext: .\n    dockerfilePath: ./deploy/free.Dockerfile",
    )
    assert swapped_docker != BLUEPRINT
    assert "UNREVIEWED_BLUEPRINT_STRUCTURE" in check_blueprint(swapped_docker)

    swapped_service = BLUEPRINT.replace(
        "    autoDeployTrigger: 'off'\n    healthCheckPath: /api/health",
        "    healthCheckPath: /api/health\n    autoDeployTrigger: 'off'",
    )
    assert swapped_service != BLUEPRINT
    assert "UNREVIEWED_BLUEPRINT_STRUCTURE" in check_blueprint(swapped_service)


def test_blueprint_reordering_whole_env_blocks_is_rejected():
    first = '      - key: DEPLOYMENT_PROFILE\n        value: free-cloud'
    second = '      - key: FREE_ONLY\n        value: "true"'
    assert first in BLUEPRINT and second in BLUEPRINT
    rearranged = BLUEPRINT.replace(first + "\n" + second, second + "\n" + first)
    assert rearranged != BLUEPRINT
    assert "UNREVIEWED_BLUEPRINT_STRUCTURE" in check_blueprint(rearranged)
