def test_create_configmap_in_nonexistent_namespace_fails(cli, k8s_client, kubectl_bin, tmp_path):
    cm_name = f"cm-cr-ne01-{tmp_path.name.replace('_', '-').lower()[:30]}"
    result = cli(
        "create",
        "configmap",
        cm_name,
        "--from-literal=k=v",
        "-n",
        "nonexistent-cr-ne01",
    )
    assert result.returncode == 1
    stderr_lower = result.stderr.lower()
    assert "not found" in stderr_lower or "notfound" in stderr_lower
