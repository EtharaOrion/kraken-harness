def test_apply_pod_manifest_creates_pod(cli, k8s_client, tmp_path):
    pod_name = f"pod-apply-hp01-{tmp_path.name.replace('_', '-').lower()[:30]}"
    manifest = tmp_path / f"{pod_name}.yaml"
    manifest.write_text(
        f"apiVersion: v1\nkind: Pod\nmetadata:\n  name: {pod_name}\n  namespace: default\n"
        "spec:\n  containers: [{name: c, image: nginx}]\n"
    )
    result = cli("apply", "-f", str(manifest))
    assert result.returncode == 0, result.stderr
    assert f"pod/{pod_name}" in result.stdout
    assert "created" in result.stdout or "configured" in result.stdout
    pods = k8s_client.list_namespaced_pod(namespace="default").items
    assert any(p.metadata.name == pod_name for p in pods)
