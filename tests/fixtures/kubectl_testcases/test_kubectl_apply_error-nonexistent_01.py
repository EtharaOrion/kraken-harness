def test_apply_pod_to_nonexistent_namespace_returns_error(cli, k8s_client, tmp_path):
    pod_name = f"pod-apply-ne01-{tmp_path.name.replace('_', '-').lower()[:30]}"
    manifest = tmp_path / f"{pod_name}.yaml"
    manifest.write_text(
        f"apiVersion: v1\nkind: Pod\nmetadata:\n  name: {pod_name}\n  namespace: default\n"
        "spec:\n  containers: [{name: c, image: nginx}]\n"
    )
    result = cli("apply", "-f", str(manifest), "-n", "nonexistent-ns-ne01")
    assert result.returncode == 1
    stderr = result.stderr.lower()
    assert "not found" in stderr or "notfound" in stderr
