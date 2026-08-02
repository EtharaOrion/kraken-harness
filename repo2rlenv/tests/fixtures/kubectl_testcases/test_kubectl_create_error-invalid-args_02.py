def test_create_deployment_missing_name_and_image_fails(cli, k8s_client, kubectl_bin, tmp_path):
    result = cli("create", "deployment")
    assert result.returncode == 1
    stderr_lower = result.stderr.lower()
    assert (
        "required" in stderr_lower
        or "name" in stderr_lower
        or "usage" in stderr_lower
        or "image" in stderr_lower
    )
