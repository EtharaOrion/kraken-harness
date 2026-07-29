def test_create_configmap_in_deleted_namespace_fails(cli, k8s_client, kubectl_bin, tmp_path):
    ns_name = f"ns-cr-ne03-{tmp_path.name.replace('_', '-').lower()[:30]}"
    cm_name = f"cm-cr-ne03-{tmp_path.name.replace('_', '-').lower()[:30]}"
    seed_create = kubectl_bin(["create", "namespace", ns_name])
    assert seed_create.returncode == 0, seed_create.stderr
    seed_delete = kubectl_bin(["delete", "namespace", ns_name, "--wait=true"])
    assert seed_delete.returncode == 0, seed_delete.stderr
    result = cli("create", "configmap", cm_name, "--from-literal=k=v", "-n", ns_name)
    assert result.returncode == 1
    stderr_lower = result.stderr.lower()
    assert "not found" in stderr_lower or "notfound" in stderr_lower
