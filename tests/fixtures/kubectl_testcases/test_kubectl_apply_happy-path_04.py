def test_apply_idempotent_second_apply_unchanged(cli, k8s_client, tmp_path):
    pod_name = f"pod-apply-hp04-{tmp_path.name.replace('_', '-').lower()[:30]}"
    manifest = tmp_path / f"{pod_name}.yaml"
    manifest.write_text(
        f"apiVersion: v1\nkind: Pod\nmetadata:\n  name: {pod_name}\n  namespace: default\n"
        "spec:\n  containers: [{name: c, image: nginx}]\n"
    )
    first = cli("apply", "-f", str(manifest))
    assert first.returncode == 0, first.stderr
    assert f"pod/{pod_name}" in first.stdout
    second = cli("apply", "-f", str(manifest))
    assert second.returncode == 0, second.stderr
    assert "unchanged" in second.stdout or "configured" in second.stdout
    pods = k8s_client.list_namespaced_pod(namespace="default").items
    assert any(p.metadata.name == pod_name for p in pods)
