def test_get_namespace_0124_output_yaml(cli, kubectl_bin):
    seed = kubectl_bin(["create", "namespace", "gfna-0124"])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "namespace", "gfna-0124", "-o", "yaml")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""
