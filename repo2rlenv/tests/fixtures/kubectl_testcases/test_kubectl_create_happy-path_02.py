def test_create_configmap_from_literal_succeeds(cli, k8s_client, kubectl_bin, tmp_path):
    cm_name = f"cm-cr-hp02-{tmp_path.name.replace('_', '-').lower()[:30]}"
    result = cli("create", "configmap", cm_name, "--from-literal=key=val", "-n", "default")
    assert result.returncode == 0, result.stderr
    cms = k8s_client.list_namespaced_config_map(namespace="default").items
    matching = [c for c in cms if c.metadata.name == cm_name]
    assert len(matching) == 1
    assert matching[0].data == {"key": "val"}
