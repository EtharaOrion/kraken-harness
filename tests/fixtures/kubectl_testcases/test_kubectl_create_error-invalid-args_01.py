def test_create_configmap_invalid_flag_fails(cli, k8s_client, kubectl_bin, tmp_path):
    result = cli("create", "configmap", "cm-name", "--invalid-flag", "-n", "default")
    assert result.returncode == 1
    stderr_lower = result.stderr.lower()
    assert "unknown" in stderr_lower or "invalid" in stderr_lower
