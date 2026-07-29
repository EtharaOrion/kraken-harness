def test_delete_pod_0099_grace_period_force(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Pod\nmetadata:\n  name: dgp-0099\n  namespace: default\nspec:\n  containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("delete", "pod", "dgp-0099", "-n", "default", "--grace-period=0", "--force")
    assert result.returncode == 0, result.stderr
    pods = k8s_client.list_namespaced_pod(namespace="default").items
    assert not any(p.metadata.name == "dgp-0099" for p in pods)
