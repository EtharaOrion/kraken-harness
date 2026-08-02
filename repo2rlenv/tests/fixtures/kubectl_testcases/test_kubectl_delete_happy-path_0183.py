def test_delete_pod_0183_grace_period_force(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Pod\nmetadata:\n  name: dgp-0183\n  namespace: default\nspec:\n  containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("delete", "pod", "dgp-0183", "-n", "default", "--grace-period=0", "--force")
    assert result.returncode == 0, result.stderr
    pods = k8s_client.list_namespaced_pod(namespace="default").items
    assert not any(p.metadata.name == "dgp-0183" for p in pods)
