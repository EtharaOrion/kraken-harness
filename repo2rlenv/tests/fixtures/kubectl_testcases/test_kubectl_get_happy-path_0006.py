def test_get_pod_0006_by_name(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Pod\nmetadata:\n  name: gpo-0006\n  namespace: default\nspec:\n  containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "pod", "gpo-0006", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "gpo-0006" in result.stdout
    names = {o.metadata.name for o in k8s_client.list_namespaced_pod(namespace="default").items}
    assert "gpo-0006" in names
