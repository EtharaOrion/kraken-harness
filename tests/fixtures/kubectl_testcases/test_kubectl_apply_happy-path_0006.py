def test_apply_pod_0006_creates(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Pod\nmetadata:\n  name: apo-0006\n  namespace: default\nspec:\n  containers: [{name: c, image: nginx}]\n')
    result = cli("apply", "-f", str(manifest))
    assert result.returncode == 0, result.stderr
    assert "apo-0006" in result.stdout
    names = {o.metadata.name for o in k8s_client.list_namespaced_pod(namespace="default").items}
    assert "apo-0006" in names
