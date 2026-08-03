def test_create_docker_registry_secret_from_missing_file_fails(cli, k8s_client, kubectl_bin, tmp_path):
    secret_name = f"sec-cr-ne02-{tmp_path.name.replace('_', '-').lower()[:30]}"
    result = cli(
        "create",
        "secret",
        "docker-registry",
        secret_name,
        "--from-file=" + str(tmp_path / "missing.json"),
        "-n",
        "default",
    )
    assert result.returncode == 1
    stderr_lower = result.stderr.lower()
    assert "no such file" in stderr_lower or "not exist" in stderr_lower
