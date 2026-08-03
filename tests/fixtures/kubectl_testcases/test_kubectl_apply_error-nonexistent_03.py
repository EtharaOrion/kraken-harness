def test_apply_view_last_applied_nonexistent_deployment_returns_error(cli, tmp_path):
    dep_name = f"dep-apply-ne03-{tmp_path.name.replace('_', '-').lower()[:30]}"
    manifest = tmp_path / f"{dep_name}.yaml"
    manifest.write_text(
        f"apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: {dep_name}\n  namespace: default\n"
        f"spec:\n  replicas: 1\n  selector: {{matchLabels: {{app: {dep_name}}}}}\n"
        f"  template:\n    metadata: {{labels: {{app: {dep_name}}}}}\n"
        "    spec:\n      containers: [{name: c, image: nginx}]\n"
    )
    seed = cli("apply", "-f", str(manifest))
    assert seed.returncode == 0, seed.stderr
    result = cli("apply", "view-last-applied", "deployment", "nonexistent-dep-ne03", "-n", "default")
    assert result.returncode == 1
    assert "not found" in result.stderr.lower()
