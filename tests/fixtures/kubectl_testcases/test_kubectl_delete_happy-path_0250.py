def test_delete_pod_0250_by_file(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Pod\nmetadata:\n  name: dfpo-0250\n  namespace: default\nspec:\n  containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("delete", "-f", str(manifest))
    assert result.returncode == 0, result.stderr
    names = {o.metadata.name for o in k8s_client.list_namespaced_pod(namespace="default").items}
    assert "dfpo-0250" not in names
