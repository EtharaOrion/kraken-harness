def test_apply_limitrange_0013_creates(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: LimitRange\nmetadata:\n  name: ali-0013\n  namespace: default\nspec:\n  limits:\n  - type: Container\n    default: {cpu: 100m}\n    defaultRequest: {cpu: 50m}\n')
    result = cli("apply", "-f", str(manifest))
    assert result.returncode == 0, result.stderr
    assert "ali-0013" in result.stdout
    names = {o.metadata.name for o in k8s_client.list_namespaced_limit_range(namespace="default").items}
    assert "ali-0013" in names
