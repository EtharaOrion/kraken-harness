def test_create_configmap_from_missing_file_fails(cli, k8s_client, kubectl_bin, tmp_path):
    cm_name = f"cm-cr-ia03-{tmp_path.name.replace('_', '-').lower()[:30]}"
    result = cli(
        "create",
        "configmap",
        cm_name,
        "--from-file=" + str(tmp_path / "does-not-exist.txt"),
        "-n",
        "default",
    )
    assert result.returncode == 1
    stderr_lower = result.stderr.lower()
    assert (
        "no such file" in stderr_lower
        or "not exist" in stderr_lower
        or "cannot" in stderr_lower
        or "unable" in stderr_lower
    )
